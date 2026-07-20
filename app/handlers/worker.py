"""Handler del worker de verificación documental.

Reexporta el orquestador M-ORQ (`lambda_handler.handler`) para
herramientas / SAM que referencien este módulo.
"""

from app.handlers.lambda_handler import handler

__all__ = ["handler"]
