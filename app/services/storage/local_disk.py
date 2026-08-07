"""Implementação em disco local de StorageBackend (app/services/storage/base.py)
-- backend padrão enquanto a Seção 10 não tem credenciais de S3.

Guarda cada chave "documentos/{caso_id}/{uuid}" como um arquivo dentro de
instance/document_storage/, espelhando a própria chave como caminho
relativo. Ninguém fora desta classe deveria nunca montar esse caminho à
mão -- é exatamente o que a interface StorageBackend existe para evitar.
"""
from __future__ import annotations

from pathlib import Path

from app.services.storage.base import StorageBackend

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_STORAGE_DIR = ROOT / "instance" / "document_storage"


class ChaveInvalidaError(ValueError):
    pass


class LocalDiskStorage(StorageBackend):
    def __init__(self, base_dir: Path | str | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else DEFAULT_STORAGE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolver_caminho(self, chave: str) -> Path:
        # Chave é opaca pra quem chama, mas aqui dentro ela vira caminho de
        # disco -- validar contra path traversal (ex.: "../../etc/passwd")
        # antes de tocar o filesystem é obrigatório, já que quem gera a
        # chave inclui um caso_id que em tese poderia vir de entrada externa.
        candidato = (self.base_dir / chave).resolve()
        try:
            candidato.relative_to(self.base_dir.resolve())
        except ValueError:
            raise ChaveInvalidaError(f"chave fora do diretório de storage: {chave!r}") from None
        return candidato

    def salvar(self, dados: bytes, chave: str) -> str:
        caminho = self._resolver_caminho(chave)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(dados)
        return chave

    def ler(self, chave: str) -> bytes:
        return self._resolver_caminho(chave).read_bytes()

    def excluir(self, chave: str) -> None:
        caminho = self._resolver_caminho(chave)
        caminho.unlink(missing_ok=True)

    def existe(self, chave: str) -> bool:
        return self._resolver_caminho(chave).is_file()
