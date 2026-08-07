"""Backend de storage em S3 -- AINDA NÃO IMPLEMENTADO.

TODO(Seção 10): quando as credenciais de object storage (bucket, região,
access key/secret ou role) chegarem, implementar esta classe contra a
mesma interface StorageBackend (app/services/storage/base.py) que
LocalDiskStorage já implementa (app/services/storage/local_disk.py).
Rascunho do que entra aqui:

    import boto3

    class S3Storage(StorageBackend):
        def __init__(self, bucket: str, prefix: str = "", client=None):
            self._bucket = bucket
            self._prefix = prefix
            self._client = client or boto3.client("s3")

        def salvar(self, dados: bytes, chave: str) -> str:
            self._client.put_object(Bucket=self._bucket, Key=self._prefix + chave, Body=dados)
            return chave

        def ler(self, chave: str) -> bytes:
            obj = self._client.get_object(Bucket=self._bucket, Key=self._prefix + chave)
            return obj["Body"].read()

        def excluir(self, chave: str) -> None:
            self._client.delete_object(Bucket=self._bucket, Key=self._prefix + chave)

        def existe(self, chave: str) -> bool:
            from botocore.exceptions import ClientError
            try:
                self._client.head_object(Bucket=self._bucket, Key=self._prefix + chave)
                return True
            except ClientError:
                return False

Depois de implementar: trocar `DOCUMENT_STORAGE_BACKEND=s3` (ver
app/services/storage/__init__.py::get_storage_backend) e rodar
scripts/migrate_local_to_s3.py (TODO nesse arquivo) pra reenviar os
arquivos hoje em instance/document_storage/ usando a MESMA chave que já
está gravada em document_storage_versions.storage_key -- assim nenhuma
linha do banco precisa mudar, só o backend por trás da chave.

Nada em app/services/document_storage_service.py, em
app/document_storage_models.py ou nas rotas que os usam precisa mudar
quando isso for implementado -- é exatamente o ponto de ter a interface
StorageBackend.
"""
from __future__ import annotations

from app.services.storage.base import StorageBackend


class S3Storage(StorageBackend):
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "S3Storage ainda não foi implementado -- aguardando "
            "credenciais de object storage (Seção 10). Use "
            "LocalDiskStorage (DOCUMENT_STORAGE_BACKEND=local, é o "
            "padrão) até lá. Ver o rascunho no topo deste arquivo."
        )

    def salvar(self, dados: bytes, chave: str) -> str:
        raise NotImplementedError

    def ler(self, chave: str) -> bytes:
        raise NotImplementedError

    def excluir(self, chave: str) -> None:
        raise NotImplementedError

    def existe(self, chave: str) -> bool:
        raise NotImplementedError
