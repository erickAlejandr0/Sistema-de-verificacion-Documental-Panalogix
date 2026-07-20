"""Compatibilidad: generación de URL firmada vive en ``api_handler``.

La ruta canónica es ``POST /verificaciones/generar-url`` en
``app.handlers.api_handler``.
"""

from app.handlers.api_handler import handler

__all__ = ["handler"]
