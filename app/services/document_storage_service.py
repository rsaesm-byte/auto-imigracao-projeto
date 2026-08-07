"""Serviço da Seção 10: junta app/document_storage_models.py (metadados/
versão/exclusão lógica) com app/services/storage/ (bytes físicos).

Fluxo de upload: gera a chave opaca "documentos/{caso_id}/{uuid}", manda
o backend de storage gravar os bytes sob essa chave, só então grava a
linha de versão apontando pra ela -- se a gravação em disco falhar, a
transação de banco nunca chega a acontecer. Cada upload sobre um
documento já existente cria uma nova versão em vez de sobrescrever;
nenhuma chave antiga é reaproveitada nem apagada.

Rotas HTTP nunca devem chamar app/services/storage/ diretamente nem
montar uma storage_key à mão -- sempre por aqui.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.document_storage_models import DocumentoArquivo, DocumentoArquivoVersao
from app.services.storage import StorageBackend, get_storage_backend


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentoNaoEncontradoError(Exception):
    pass


class DocumentoExcluidoError(Exception):
    """Levantado ao tentar adicionar uma versão a um documento já
    excluído logicamente -- reative com `restaurar` primeiro se for
    intencional."""


class VersaoNaoEncontradaError(Exception):
    pass


class DocumentStorageService:
    def __init__(self, session: Session, storage: StorageBackend | None = None):
        self.session = session
        self.storage = storage or get_storage_backend()

    def upload(
        self,
        *,
        caso_id: int,
        tipo_documento: str,
        nome_original: str,
        mime_type: str,
        conteudo: bytes,
        documento_id: int | None = None,
    ) -> DocumentoArquivoVersao:
        """`documento_id=None` (padrão) cria um documento lógico novo, na
        versão 1. Passar o `documento_id` de um documento existente cria
        mais uma versão sobre ele (precisa ser do mesmo `caso_id` --
        cross-caso é sempre erro de aplicação, não um caso de uso real)."""
        if documento_id is None:
            documento = DocumentoArquivo(caso_id=caso_id, tipo_documento=tipo_documento)
            self.session.add(documento)
            self.session.flush()  # popula documento.id pra usar na chave e na FK da versão
            numero_versao = 1
        else:
            documento = self.session.get(DocumentoArquivo, documento_id)
            if documento is None:
                raise DocumentoNaoEncontradoError(f"documento {documento_id} não existe")
            if documento.caso_id != caso_id:
                raise ValueError(
                    f"documento {documento_id} pertence ao caso {documento.caso_id}, não {caso_id}")
            if documento.deleted_at is not None:
                raise DocumentoExcluidoError(f"documento {documento_id} está excluído")
            numero_versao = max((v.numero_versao for v in documento.versoes), default=0) + 1
            for versao_anterior in documento.versoes:
                versao_anterior.is_current = False

        chave = f"documentos/{caso_id}/{uuid.uuid4().hex}"
        self.storage.salvar(conteudo, chave)

        versao = DocumentoArquivoVersao(
            documento_id=documento.id,
            numero_versao=numero_versao,
            storage_key=chave,
            nome_original=nome_original,
            mime_type=mime_type,
            tamanho_bytes=len(conteudo),
            hash=hashlib.sha256(conteudo).hexdigest(),
            is_current=True,
        )
        self.session.add(versao)
        documento.updated_at = _utcnow()
        self.session.commit()
        return versao

    def download(
        self, documento_id: int, *, numero_versao: int | None = None,
    ) -> tuple[bytes, DocumentoArquivoVersao]:
        """`numero_versao=None` baixa a versão corrente. Funciona mesmo
        se o documento estiver excluído logicamente -- a exclusão some
        da listagem padrão, não bloqueia acesso direto por id (auditoria,
        tela de "lixeira", etc.)."""
        versao = self._buscar_versao(documento_id, numero_versao)
        return self.storage.ler(versao.storage_key), versao

    def listar_versoes(self, documento_id: int) -> list[DocumentoArquivoVersao]:
        documento = self._buscar_documento(documento_id)
        return list(documento.versoes)

    def listar_documentos(self, caso_id: int, *, incluir_excluidos: bool = False) -> list[DocumentoArquivo]:
        query = self.session.query(DocumentoArquivo).filter_by(caso_id=caso_id)
        if not incluir_excluidos:
            query = query.filter(DocumentoArquivo.deleted_at.is_(None))
        return query.order_by(DocumentoArquivo.created_at.desc()).all()

    def excluir(self, documento_id: int) -> None:
        """Exclusão lógica: marca `deleted_at`, nunca apaga a linha nem
        chama `storage.excluir` em nenhuma versão. Reversível via
        `restaurar`."""
        documento = self._buscar_documento(documento_id)
        documento.deleted_at = _utcnow()
        self.session.commit()

    def restaurar(self, documento_id: int) -> None:
        documento = self._buscar_documento(documento_id)
        documento.deleted_at = None
        self.session.commit()

    def _buscar_documento(self, documento_id: int) -> DocumentoArquivo:
        documento = self.session.get(DocumentoArquivo, documento_id)
        if documento is None:
            raise DocumentoNaoEncontradoError(f"documento {documento_id} não existe")
        return documento

    def _buscar_versao(self, documento_id: int, numero_versao: int | None) -> DocumentoArquivoVersao:
        documento = self._buscar_documento(documento_id)
        if numero_versao is None:
            versao = documento.versao_corrente
        else:
            versao = next((v for v in documento.versoes if v.numero_versao == numero_versao), None)
        if versao is None:
            raise VersaoNaoEncontradaError(
                f"documento {documento_id} não tem versão "
                f"{'corrente' if numero_versao is None else numero_versao}")
        return versao
