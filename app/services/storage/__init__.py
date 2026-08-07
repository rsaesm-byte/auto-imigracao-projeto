"""Ponto único de escolha do backend de storage (Seção 10).

Todo o resto do sistema (DocumentStorageService, rotas) chama
`get_storage_backend()` em vez de instanciar LocalDiskStorage ou
S3Storage diretamente -- trocar o backend em produção é mudar a env var
abaixo, não editar código.
"""
from __future__ import annotations

import os

from app.services.storage.base import StorageBackend
from app.services.storage.local_disk import LocalDiskStorage

__all__ = ["StorageBackend", "LocalDiskStorage", "get_storage_backend"]


def get_storage_backend() -> StorageBackend:
    """DOCUMENT_STORAGE_BACKEND=local (padrão, hoje o único que funciona)
    ou =s3 (Seção 10 -- ver app/services/storage/s3.py, ainda levanta
    NotImplementedError até as credenciais chegarem)."""
    backend = os.environ.get("DOCUMENT_STORAGE_BACKEND", "local")
    if backend == "local":
        return LocalDiskStorage()
    if backend == "s3":
        from app.services.storage.s3 import S3Storage
        return S3Storage()
    raise ValueError(f"DOCUMENT_STORAGE_BACKEND desconhecido: {backend!r}")
