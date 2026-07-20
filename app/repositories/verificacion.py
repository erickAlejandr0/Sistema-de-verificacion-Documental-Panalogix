"""Repositorio de documentos, historial y correcciones (schema verificaciones)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.models.alerta import Alerta, AlertaCreate
from app.models.correccion import Correccion, CorreccionCreate
from app.models.documento import Documento, DocumentoCreate
from app.models.enums import DiasAviso, EstadoAlerta, ResultadoVerificacion
from app.models.fields import CampoCifrado, PlaintextPiiPayload
from app.models.historial import Historial, HistorialCreate
from app.models.views import DocumentoConUltimoHistorial
from app.repositories.db import get_connection
from app.repositories.exceptions import (
    DocumentNotFoundError,
    HistorialNotFoundError,
    RepositoryError,
)
from app.utils.encryption import PiiEncryptor
from app.utils.logging import get_logger

logger = get_logger(__name__)

_PII_EXTRAIDOS_FORBIDDEN = frozenset({"cedula", "cédula", "nombre", "nombre_titular", "nombre_completo"})


def _jsonb(value: Any) -> Json:
    """Envuelve un valor Python para columna JSONB."""
    return Json(value, dumps=lambda obj: json.dumps(obj, default=str))


def _historial_from_row(row: dict[str, Any]) -> Historial:
    """Hidrata un ``Historial`` desde una fila RealDict."""
    return Historial.model_validate(dict(row))


class VerificacionRepository:
    """Acceso a datos de verificación documental (sin reglas de negocio).

    Args:
        encryptor: Cifrador PII. Si es ``None``, se crea con settings.
    """

    def __init__(self, encryptor: PiiEncryptor | None = None) -> None:
        """Inicializa el repositorio.

        Args:
            encryptor: Instancia de ``PiiEncryptor`` inyectable.
        """
        self._encryptor = encryptor or PiiEncryptor()

    def crear_documento(self, data: DocumentoCreate) -> Documento:
        """Persiste un documento físico subido.

        Args:
            data: Datos de creación.

        Returns:
            Documento persistido.

        Raises:
            RepositoryError: Si falla el INSERT.
        """
        sql = """
            INSERT INTO verificaciones.documentos (
                transportista_id, tipo_documento, s3_key_raw, s3_key_verified
            )
            VALUES (%s, %s, %s, %s)
            RETURNING
                id, transportista_id, tipo_documento, s3_key_raw, s3_key_verified,
                subido_en, eliminar_despues
        """
        params = (
            str(data.transportista_id),
            data.tipo_documento,
            data.s3_key_raw,
            data.s3_key_verified,
        )
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
            return Documento.model_validate(dict(row))
        except psycopg2.Error as exc:
            logger.error(
                "crear_documento_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise RepositoryError("no se pudo crear el documento") from exc

    def obtener_documento(self, documento_id: UUID) -> Documento:
        """Obtiene un documento por id.

        Args:
            documento_id: UUID del documento.

        Returns:
            Documento persistido.

        Raises:
            DocumentNotFoundError: Si no existe.
            RepositoryError: Si falla la consulta.
        """
        sql = """
            SELECT
                id, transportista_id, tipo_documento, s3_key_raw, s3_key_verified,
                subido_en, eliminar_despues
            FROM verificaciones.documentos
            WHERE id = %s
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (str(documento_id),))
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudo obtener el documento") from exc

        if row is None:
            raise DocumentNotFoundError(f"documento {documento_id} no encontrado")
        return Documento.model_validate(dict(row))

    def obtener_extraccion_idempotente(
        self,
        documento_id: UUID,
        prompt_hash: str,
        version_extraccion: str,
    ) -> Historial | None:
        """Busca historial ya persistido para la misma configuración de extracción.

        Args:
            documento_id: Documento procesado.
            prompt_hash: Hash del prompt (pre-Claude).
            version_extraccion: Versión del pipeline.

        Returns:
            Historial existente o ``None``.
        """
        sql = """
            SELECT
                id, documento_id, tipo_detectado, campos_extraidos, campos_cifrados,
                resultado, score_lectura, score_autenticidad, modelo_usado,
                version_extraccion, prompt_hash, costo_api, fecha_vencimiento,
                procesado_en
            FROM verificaciones.historial
            WHERE documento_id = %s
              AND prompt_hash = %s
              AND version_extraccion = %s
            ORDER BY procesado_en DESC
            LIMIT 1
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        sql,
                        (str(documento_id), prompt_hash, version_extraccion),
                    )
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError(
                "no se pudo consultar extracción idempotente"
            ) from exc

        if row is None:
            return None
        return _historial_from_row(dict(row))

    def obtener_reglas_validacion(self, tipo_codigo: str) -> dict[str, Any]:
        """Carga ``reglas_validacion`` JSONB de un tipo de documento.

        Args:
            tipo_codigo: Código en ``tipos_documento``.

        Returns:
            Dict de reglas, o ``{}`` si el tipo no existe.
        """
        sql = """
            SELECT reglas_validacion
            FROM verificaciones.tipos_documento
            WHERE codigo = %s
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (tipo_codigo,))
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudieron cargar reglas_validacion") from exc

        if row is None:
            return {}
        raw = row.get("reglas_validacion")
        if isinstance(raw, dict):
            return raw
        return {}

    def actualizar_s3_key_verified(self, documento_id: UUID, key: str) -> None:
        """Actualiza la clave verified-docs del documento.

        Args:
            documento_id: Documento aprobado.
            key: Clave S3 en verified-docs.

        Raises:
            DocumentNotFoundError: Si no existe.
            RepositoryError: Si falla el UPDATE.
        """
        sql = """
            UPDATE verificaciones.documentos
            SET s3_key_verified = %s
            WHERE id = %s
            RETURNING id
        """
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (key, str(documento_id)))
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError(
                "no se pudo actualizar s3_key_verified"
            ) from exc

        if row is None:
            raise DocumentNotFoundError(f"documento {documento_id} no encontrado")

    def try_registrar_alerta(self, data: AlertaCreate) -> Alerta | None:
        """Inserta una alerta; si ya existe (UNIQUE), retorna ``None``.

        Inserta con ``enviada_en = NULL`` para permitir republicar SNS si
        la publicación falla tras el INSERT (véase ``marcar_alerta_enviada``).

        Args:
            data: Datos de la alerta.

        Returns:
            Alerta insertada, o ``None`` si ya existía (conflicto UNIQUE).
        """
        sql = """
            INSERT INTO verificaciones.alertas (
                historial_id, dias_aviso, estado, enviada_en
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (historial_id, dias_aviso) DO NOTHING
            RETURNING id, historial_id, dias_aviso, estado, enviada_en
        """
        params = (
            str(data.historial_id),
            int(data.dias_aviso) if not isinstance(data.dias_aviso, int) else data.dias_aviso,
            data.estado if isinstance(data.estado, str) else data.estado.value,
            data.enviada_en,
        )
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudo registrar la alerta") from exc

        if row is None:
            return None
        return Alerta.model_validate(dict(row))

    def obtener_alerta(
        self,
        historial_id: UUID,
        dias_aviso: int,
    ) -> Alerta | None:
        """Obtiene una alerta por historial y umbral.

        Args:
            historial_id: Extracción asociada.
            dias_aviso: Umbral (30, 7 o 0).

        Returns:
            Alerta o ``None``.
        """
        sql = """
            SELECT id, historial_id, dias_aviso, estado, enviada_en
            FROM verificaciones.alertas
            WHERE historial_id = %s AND dias_aviso = %s
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (str(historial_id), dias_aviso))
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudo obtener la alerta") from exc

        if row is None:
            return None
        return Alerta.model_validate(dict(row))

    def marcar_alerta_enviada(self, alerta_id: UUID) -> None:
        """Marca una alerta como enviada (``enviada_en = now()``).

        Args:
            alerta_id: ID de la alerta.

        Raises:
            RepositoryError: Si falla el UPDATE o no existe.
        """
        sql = """
            UPDATE verificaciones.alertas
            SET enviada_en = now(), estado = %s
            WHERE id = %s
            RETURNING id
        """
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (EstadoAlerta.ENVIADA.value, str(alerta_id)))
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudo marcar alerta enviada") from exc

        if row is None:
            raise RepositoryError(f"alerta {alerta_id} no encontrada")

    def registrar_extraccion(
        self,
        data: HistorialCreate,
        *,
        pii_plaintext: PlaintextPiiPayload | None = None,
    ) -> Historial:
        """Registra una extracción; cifra PII antes de persistir.

        Args:
            data: Datos de la extracción (sin PII en claro en campos_extraidos).
            pii_plaintext: PII en claro a cifrar hacia ``campos_cifrados``.

        Returns:
            Historial persistido (``campos_cifrados`` cifrado).

        Raises:
            RepositoryError: Si hay PII en claro en campos_extraidos o falla el INSERT.
        """
        extraidos = {
            key: value.model_dump(mode="json")
            for key, value in data.campos_extraidos.items()
        }
        forbidden = _PII_EXTRAIDOS_FORBIDDEN.intersection(k.lower() for k in extraidos)
        if forbidden:
            raise RepositoryError(
                f"PII no permitido en campos_extraidos: {sorted(forbidden)}"
            )

        cifrados: dict[str, Any] = {}
        if data.campos_cifrados:
            cifrados = {
                key: value.model_dump(mode="json")
                for key, value in data.campos_cifrados.items()
            }

        if pii_plaintext is not None:
            cifrados["cedula"] = CampoCifrado(
                valor_cifrado=self._encryptor.encrypt(pii_plaintext.cedula),
                confianza=Decimal("1.000"),
            ).model_dump(mode="json")
            cifrados["nombre_titular"] = CampoCifrado(
                valor_cifrado=self._encryptor.encrypt(pii_plaintext.nombre_titular),
                confianza=Decimal("1.000"),
            ).model_dump(mode="json")

        sql = """
            INSERT INTO verificaciones.historial (
                documento_id, tipo_detectado, campos_extraidos, campos_cifrados,
                resultado, score_lectura, score_autenticidad, modelo_usado,
                version_extraccion, prompt_hash, costo_api, fecha_vencimiento
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING
                id, documento_id, tipo_detectado, campos_extraidos, campos_cifrados,
                resultado, score_lectura, score_autenticidad, modelo_usado,
                version_extraccion, prompt_hash, costo_api, fecha_vencimiento,
                procesado_en
        """
        params = (
            str(data.documento_id),
            data.tipo_detectado,
            _jsonb(extraidos),
            _jsonb(cifrados) if cifrados else None,
            data.resultado,
            data.score_lectura,
            data.score_autenticidad,
            data.modelo_usado,
            data.version_extraccion,
            data.prompt_hash,
            data.costo_api,
            data.fecha_vencimiento,
        )
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
            return _historial_from_row(dict(row))
        except psycopg2.Error as exc:
            logger.error(
                "registrar_extraccion_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise RepositoryError("no se pudo registrar la extracción") from exc

    def obtener_extraccion(
        self,
        historial_id: UUID,
        *,
        decrypt_pii: bool = False,
    ) -> tuple[Historial, PlaintextPiiPayload | None]:
        """Obtiene una extracción por id.

        Args:
            historial_id: ID del historial.
            decrypt_pii: Si True, descifra cédula/nombre_titular a plaintext.

        Returns:
            Par ``(Historial, PlaintextPiiPayload | None)``.

        Raises:
            HistorialNotFoundError: Si no existe.
            RepositoryError: Si falla la consulta o el descifrado.
        """
        sql = """
            SELECT
                id, documento_id, tipo_detectado, campos_extraidos, campos_cifrados,
                resultado, score_lectura, score_autenticidad, modelo_usado,
                version_extraccion, prompt_hash, costo_api, fecha_vencimiento,
                procesado_en
            FROM verificaciones.historial
            WHERE id = %s
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (str(historial_id),))
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudo obtener la extracción") from exc

        if row is None:
            raise HistorialNotFoundError(f"historial {historial_id} no encontrado")

        historial = _historial_from_row(dict(row))
        plaintext: PlaintextPiiPayload | None = None
        if decrypt_pii and historial.campos_cifrados:
            cedula_field = historial.campos_cifrados.get("cedula")
            nombre_field = historial.campos_cifrados.get("nombre_titular")
            if cedula_field and nombre_field:
                plaintext = PlaintextPiiPayload(
                    cedula=self._encryptor.decrypt(cedula_field.valor_cifrado),
                    nombre_titular=self._encryptor.decrypt(nombre_field.valor_cifrado),
                )
        return historial, plaintext

    def obtener_por_transportista(self, transportista_id: UUID) -> list[Documento]:
        """Lista documentos de un transportista.

        Args:
            transportista_id: ID en Panalogix.

        Returns:
            Lista de documentos.
        """
        sql = """
            SELECT
                id, transportista_id, tipo_documento, s3_key_raw, s3_key_verified,
                subido_en, eliminar_despues
            FROM verificaciones.documentos
            WHERE transportista_id = %s
            ORDER BY subido_en DESC
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (str(transportista_id),))
                    rows = cur.fetchall()
            return [Documento.model_validate(dict(r)) for r in rows]
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudieron listar documentos") from exc

    def listar_con_ultimo_historial(
        self,
        transportista_id: UUID,
    ) -> list[DocumentoConUltimoHistorial]:
        """Lista documentos del transportista con su último historial.

        Args:
            transportista_id: ID en Panalogix.

        Returns:
            Lista de pares documento + historial más reciente (o None).
        """
        sql = """
            SELECT
                d.id AS doc_id,
                d.transportista_id,
                d.tipo_documento,
                d.s3_key_raw,
                d.s3_key_verified,
                d.subido_en,
                d.eliminar_despues,
                h.id AS historial_id,
                h.documento_id,
                h.tipo_detectado,
                h.campos_extraidos,
                h.campos_cifrados,
                h.resultado,
                h.score_lectura,
                h.score_autenticidad,
                h.modelo_usado,
                h.version_extraccion,
                h.prompt_hash,
                h.costo_api,
                h.fecha_vencimiento,
                h.procesado_en
            FROM verificaciones.documentos d
            LEFT JOIN LATERAL (
                SELECT *
                FROM verificaciones.historial h2
                WHERE h2.documento_id = d.id
                ORDER BY h2.procesado_en DESC
                LIMIT 1
            ) h ON TRUE
            WHERE d.transportista_id = %s
            ORDER BY d.subido_en DESC
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (str(transportista_id),))
                    rows = cur.fetchall()
        except psycopg2.Error as exc:
            raise RepositoryError(
                "no se pudieron listar documentos con historial"
            ) from exc

        result: list[DocumentoConUltimoHistorial] = []
        for row in rows:
            data = dict(row)
            documento = Documento.model_validate(
                {
                    "id": data["doc_id"],
                    "transportista_id": data["transportista_id"],
                    "tipo_documento": data["tipo_documento"],
                    "s3_key_raw": data["s3_key_raw"],
                    "s3_key_verified": data["s3_key_verified"],
                    "subido_en": data["subido_en"],
                    "eliminar_despues": data["eliminar_despues"],
                }
            )
            historial: Historial | None = None
            if data.get("historial_id") is not None:
                historial = _historial_from_row(
                    {
                        "id": data["historial_id"],
                        "documento_id": data["documento_id"],
                        "tipo_detectado": data["tipo_detectado"],
                        "campos_extraidos": data["campos_extraidos"],
                        "campos_cifrados": data["campos_cifrados"],
                        "resultado": data["resultado"],
                        "score_lectura": data["score_lectura"],
                        "score_autenticidad": data["score_autenticidad"],
                        "modelo_usado": data["modelo_usado"],
                        "version_extraccion": data["version_extraccion"],
                        "prompt_hash": data["prompt_hash"],
                        "costo_api": data["costo_api"],
                        "fecha_vencimiento": data["fecha_vencimiento"],
                        "procesado_en": data["procesado_en"],
                    }
                )
            result.append(
                DocumentoConUltimoHistorial(documento=documento, historial=historial)
            )
        return result

    def listar_pendientes_revision(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Historial]:
        """Lista extracciones en estado REVISION_MANUAL (paginado).

        Args:
            limit: Máximo de filas (1–200).
            offset: Desplazamiento (>= 0).

        Returns:
            Lista de historiales pendientes.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit debe estar entre 1 y 200")
        if offset < 0:
            raise ValueError("offset debe ser >= 0")

        sql = """
            SELECT
                id, documento_id, tipo_detectado, campos_extraidos, campos_cifrados,
                resultado, score_lectura, score_autenticidad, modelo_usado,
                version_extraccion, prompt_hash, costo_api, fecha_vencimiento,
                procesado_en
            FROM verificaciones.historial
            WHERE resultado = %s
            ORDER BY procesado_en ASC
            LIMIT %s OFFSET %s
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, ("REVISION_MANUAL", limit, offset))
                    rows = cur.fetchall()
            return [_historial_from_row(dict(r)) for r in rows]
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudieron listar pendientes") from exc

    def actualizar_resultado_historial(
        self,
        historial_id: UUID,
        resultado: ResultadoVerificacion | str,
    ) -> Historial:
        """Actualiza el resultado de una extracción a APROBADO o RECHAZADO.

        Args:
            historial_id: Extracción a actualizar.
            resultado: Nuevo resultado (solo APROBADO o RECHAZADO).

        Returns:
            Historial actualizado.

        Raises:
            ValueError: Si el resultado no es APROBADO/RECHAZADO.
            HistorialNotFoundError: Si no existe.
            RepositoryError: Si falla el UPDATE.
        """
        value = (
            resultado.value
            if isinstance(resultado, ResultadoVerificacion)
            else str(resultado)
        )
        if value not in {
            ResultadoVerificacion.APROBADO.value,
            ResultadoVerificacion.RECHAZADO.value,
        }:
            raise ValueError("resultado debe ser APROBADO o RECHAZADO")

        sql = """
            UPDATE verificaciones.historial
            SET resultado = %s
            WHERE id = %s
            RETURNING
                id, documento_id, tipo_detectado, campos_extraidos, campos_cifrados,
                resultado, score_lectura, score_autenticidad, modelo_usado,
                version_extraccion, prompt_hash, costo_api, fecha_vencimiento,
                procesado_en
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (value, str(historial_id)))
                    row = cur.fetchone()
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudo actualizar el resultado") from exc

        if row is None:
            raise HistorialNotFoundError(f"historial {historial_id} no encontrado")
        return _historial_from_row(dict(row))

    def marcar_alertas_pendientes_atendidas(self, historial_id: UUID) -> int:
        """Marca alertas PENDIENTE del historial como ATENDIDA.

        Args:
            historial_id: Extracción asociada.

        Returns:
            Número de filas actualizadas.
        """
        sql = """
            UPDATE verificaciones.alertas
            SET estado = %s
            WHERE historial_id = %s AND estado = %s
        """
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql,
                        (
                            EstadoAlerta.ATENDIDA.value,
                            str(historial_id),
                            EstadoAlerta.PENDIENTE.value,
                        ),
                    )
                    return int(cur.rowcount or 0)
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudieron marcar alertas atendidas") from exc

    def registrar_correccion(self, data: CorreccionCreate) -> Correccion:
        """Persiste una corrección humana sobre una extracción.

        Args:
            data: Datos de la corrección.

        Returns:
            Corrección persistida.
        """
        sql = """
            INSERT INTO verificaciones.correcciones (
                historial_id, campo_corregido, valor_modelo, valor_correcto, corregido_por
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING
                id, historial_id, campo_corregido, valor_modelo, valor_correcto,
                corregido_por, corregido_en
        """
        params = (
            str(data.historial_id),
            data.campo_corregido,
            data.valor_modelo,
            data.valor_correcto,
            data.corregido_por,
        )
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
            return Correccion.model_validate(dict(row))
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudo registrar la corrección") from exc

    def documentos_por_vencer(self, dias: int) -> list[Historial]:
        """Lista extracciones aprobadas candidatas a alerta de vencimiento.

        Camino A: incluye documentos **aún no vencidos** y **ya vencidos**.
        Condición: ``(fecha_vencimiento - CURRENT_DATE) <= dias`` (sin piso en 0).
        Así, si el cron falla varios días, los vencidos siguen siendo candidatos;
        el handler P4.3 clasifica umbrales 30/7/0 y usa alerta de 0 días para
        diferencias negativas (idempotencia vía UNIQUE historial_id+dias_aviso).

        Args:
            dias: Techo de la ventana en días (p. ej. 30). Debe ser ``>= 0``.

        Returns:
            Historiales con ``resultado = APROBADO`` y fecha de vencimiento
            dentro o por debajo del techo indicado.

        Raises:
            ValueError: Si ``dias`` es negativo.
            RepositoryError: Si falla la consulta.
        """
        if dias < 0:
            raise ValueError("dias debe ser >= 0")

        sql = """
            SELECT
                id, documento_id, tipo_detectado, campos_extraidos, campos_cifrados,
                resultado, score_lectura, score_autenticidad, modelo_usado,
                version_extraccion, prompt_hash, costo_api, fecha_vencimiento,
                procesado_en
            FROM verificaciones.historial
            WHERE resultado = %s
              AND fecha_vencimiento IS NOT NULL
              AND (fecha_vencimiento - CURRENT_DATE) <= %s
            ORDER BY fecha_vencimiento ASC
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, ("APROBADO", dias))
                    rows = cur.fetchall()
            return [_historial_from_row(dict(r)) for r in rows]
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudieron listar documentos por vencer") from exc

    def eliminar_datos_transportista(self, transportista_id: UUID) -> int:
        """Borra datos del transportista (Ley 81) en una transacción.

        Orden: alertas → correcciones → historial → documentos.

        Args:
            transportista_id: ID del transportista.

        Returns:
            Número de documentos eliminados.
        """
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM verificaciones.alertas
                        WHERE historial_id IN (
                            SELECT h.id
                            FROM verificaciones.historial h
                            JOIN verificaciones.documentos d ON d.id = h.documento_id
                            WHERE d.transportista_id = %s
                        )
                        """,
                        (str(transportista_id),),
                    )
                    cur.execute(
                        """
                        DELETE FROM verificaciones.correcciones
                        WHERE historial_id IN (
                            SELECT h.id
                            FROM verificaciones.historial h
                            JOIN verificaciones.documentos d ON d.id = h.documento_id
                            WHERE d.transportista_id = %s
                        )
                        """,
                        (str(transportista_id),),
                    )
                    cur.execute(
                        """
                        DELETE FROM verificaciones.historial
                        WHERE documento_id IN (
                            SELECT id FROM verificaciones.documentos
                            WHERE transportista_id = %s
                        )
                        """,
                        (str(transportista_id),),
                    )
                    cur.execute(
                        """
                        DELETE FROM verificaciones.documentos
                        WHERE transportista_id = %s
                        """,
                        (str(transportista_id),),
                    )
                    deleted = cur.rowcount
            logger.info(
                "eliminar_datos_transportista_ok",
                extra={
                    "context": {
                        "transportista_id": str(transportista_id),
                        "documentos_borrados": deleted,
                    }
                },
            )
            return deleted
        except psycopg2.Error as exc:
            logger.error(
                "eliminar_datos_transportista_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise RepositoryError(
                "no se pudieron eliminar los datos del transportista"
            ) from exc
