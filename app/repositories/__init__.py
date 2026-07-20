"""Capa de repositorios del SVD (psycopg2 + boto3, sin ORM)."""

from app.repositories.exceptions import (
    DocumentNotFoundError,
    HistorialNotFoundError,
    PatternNotFoundError,
    RepositoryError,
    S3ObjectNotFoundError,
    S3RepositoryError,
)
from app.repositories.patron import PatronRepository
from app.repositories.s3 import S3Repository
from app.repositories.verificacion import VerificacionRepository

__all__ = [
    "DocumentNotFoundError",
    "HistorialNotFoundError",
    "PatternNotFoundError",
    "PatronRepository",
    "RepositoryError",
    "S3ObjectNotFoundError",
    "S3Repository",
    "S3RepositoryError",
    "VerificacionRepository",
]
