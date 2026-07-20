"""Utilidades de preprocesamiento de imagen y conversión PDF → imagen.

Contraste, orientación, redimensionado (lado mayor 1568px). PDF vía pdf2image
(poppler), alineado al Lambda Layer de P5.1. Sin llamadas a Claude ni persistencia.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# Lado mayor objetivo para Claude Vision (costo/calidad).
_MAX_EDGE_PX: int = 1568
_JPEG_QUALITY: int = 90


class ImageProcessingError(Exception):
    """Error base de preprocesamiento de documentos."""


class CorruptDocumentError(ImageProcessingError):
    """El archivo no es una imagen/PDF válida (no retryable)."""


class DocumentTooManyPagesError(ImageProcessingError):
    """El PDF excede MAX_PAGINAS_PDF (no retryable; revisión manual)."""


def _is_pdf(data: bytes) -> bool:
    """Detecta PDF por magic bytes."""
    return data[:5] == b"%PDF-"


def _open_raster(data: bytes) -> Image.Image:
    """Abre una imagen raster (JPEG/PNG/…).

    Args:
        data: Bytes de la imagen.

    Returns:
        Imagen Pillow en RGB.

    Raises:
        CorruptDocumentError: Si no se puede identificar o decodificar.
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CorruptDocumentError("documento de imagen corrupto o no soportado") from exc

    image = ImageOps.exif_transpose(image)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    return image


def _resize_max_edge(image: Image.Image, max_edge: int = _MAX_EDGE_PX) -> Image.Image:
    """Redimensiona para que el lado mayor no exceda ``max_edge``."""
    width, height = image.size
    longest = max(width, height)
    if longest <= max_edge:
        return image
    scale = max_edge / float(longest)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def preprocess_pil_image(image: Image.Image) -> bytes:
    """Aplica contraste, orientación ya corregida y resize; serializa a JPEG.

    Args:
        image: Imagen Pillow RGB.

    Returns:
        Bytes JPEG preprocesados.
    """
    enhanced = ImageOps.autocontrast(image)
    resized = _resize_max_edge(enhanced)
    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def preprocess_document_image(data: bytes) -> bytes:
    """Preprocesa una imagen raster (no PDF).

    Args:
        data: Bytes JPEG/PNG.

    Returns:
        JPEG preprocesado.
    """
    if _is_pdf(data):
        raise CorruptDocumentError(
            "preprocess_document_image no acepta PDF; use prepare_document_images"
        )
    return preprocess_pil_image(_open_raster(data))


def pdf_to_images(
    data: bytes,
    *,
    max_pages: int | None = None,
) -> list[Image.Image]:
    """Convierte un PDF a imágenes con pdf2image (poppler).

    Procesa **todas** las páginas hasta ``max_pages``. Si el documento tiene
    más páginas que el límite, lanza error (no trunca en silencio).

    Args:
        data: Bytes del PDF.
        max_pages: Tope de páginas. Si es ``None``, usa ``settings.max_pdf_pages``.

    Returns:
        Lista de imágenes Pillow (una por página), en orden.

    Raises:
        CorruptDocumentError: PDF inválido o fallo de poppler.
        DocumentTooManyPagesError: Más páginas que el máximo permitido.
    """
    from pdf2image import convert_from_bytes, pdfinfo_from_bytes
    from pdf2image.exceptions import (
        PDFInfoNotInstalledError,
        PDFPageCountError,
        PDFSyntaxError,
    )

    if max_pages is None:
        from app.config import get_worker_settings

        max_pages = get_worker_settings().max_pdf_pages

    try:
        info = pdfinfo_from_bytes(data)
        page_count = int(info.get("Pages", 0))
    except PDFInfoNotInstalledError as exc:
        raise CorruptDocumentError(
            "poppler no disponible (se requiere el Lambda Layer de poppler)"
        ) from exc
    except (PDFPageCountError, PDFSyntaxError, ValueError, OSError) as exc:
        raise CorruptDocumentError("PDF corrupto o no legible") from exc

    if page_count <= 0:
        raise CorruptDocumentError("el PDF no contiene páginas rasterizables")
    if page_count > max_pages:
        raise DocumentTooManyPagesError(
            f"el PDF tiene {page_count} páginas (máximo {max_pages}); "
            "requiere revisión manual"
        )

    try:
        pages = convert_from_bytes(data, fmt="jpeg", first_page=1, last_page=page_count)
    except PDFInfoNotInstalledError as exc:
        raise CorruptDocumentError(
            "poppler no disponible (se requiere el Lambda Layer de poppler)"
        ) from exc
    except (PDFPageCountError, PDFSyntaxError, ValueError, OSError) as exc:
        raise CorruptDocumentError("PDF corrupto o no legible") from exc

    if not pages:
        raise CorruptDocumentError("el PDF no contiene páginas rasterizables")

    return pages


def prepare_document_images(
    data: bytes,
    *,
    max_pages: int | None = None,
) -> list[bytes]:
    """Normaliza un documento (JPEG/PNG/PDF) a una o más imágenes JPEG.

    Args:
        data: Bytes del archivo subido.
        max_pages: Límite de páginas PDF (default settings).

    Returns:
        Lista de JPEGs preprocesados (una entrada por página/imagen).

    Raises:
        CorruptDocumentError: Archivo inválido.
        DocumentTooManyPagesError: PDF demasiado largo.
    """
    if _is_pdf(data):
        pages = pdf_to_images(data, max_pages=max_pages)
        return [preprocess_pil_image(page.convert("RGB")) for page in pages]

    return [preprocess_document_image(data)]
