"""Excepciones de dominio de la capa de repositorios."""


class RepositoryError(Exception):
    """Error base de acceso a datos."""


class DocumentNotFoundError(RepositoryError):
    """No existe el documento solicitado."""


class HistorialNotFoundError(RepositoryError):
    """No existe la extracción (historial) solicitada."""


class PatternNotFoundError(RepositoryError):
    """No existe el patrón solicitado."""


class S3RepositoryError(RepositoryError):
    """Error al operar sobre objetos S3."""


class S3ObjectNotFoundError(S3RepositoryError):
    """El objeto S3 solicitado no existe."""
