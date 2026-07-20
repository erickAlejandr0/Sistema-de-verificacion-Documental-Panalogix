"""Handler de alertas de vencimiento documental.

Reexporta el orquestador M-ALERT (`expiration_handler.handler`) para
herramientas / SAM que referencien este módulo.
"""

from app.handlers.expiration_handler import handler

__all__ = ["handler"]
