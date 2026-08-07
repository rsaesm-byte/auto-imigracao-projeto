"""Metadados/versionamento/exclusão lógica de arquivos (Seção 10, CRM SAES).

Camada nova e independente do upload ad hoc que já existe em
app/services/case_documents.py (Document.file_path, app/crm_models.py) --
aquele guarda um único caminho de disco por documento pedido no
checklist do caso, sem versão e sem exclusão lógica. Esta camada é a
Seção 10 propriamente dita: qualquer tipo de arquivo (formulário
preenchido, contrato, comprovante, assinatura, ...) com histórico de
versões e nunca apagado de fato. As duas convivem por ora; unificar é
trabalho futuro, fora do escopo desta tarefa.

Duas tabelas, cada uma carregando metade dos campos pedidos:

- `DocumentoArquivo` -- a identidade lógica do documento (caso_id +
  tipo_documento). Não muda entre uploads.
- `DocumentoArquivoVersao` -- um upload específico: nome_original,
  mime_type, tamanho_bytes, hash e a chave de storage. Muda a cada
  upload, por isso mora numa linha própria em vez de ser sobrescrito.

`storage_key` é sempre a chave opaca "documentos/{caso_id}/{uuid}" que
app/services/storage/base.py::StorageBackend devolve -- nunca um caminho
de disco. Ver app/services/document_storage_service.py pela orquestração
(upload/download/exclusão) e app/services/storage/ pela interface de
storage plugável.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentoArquivo(Base):
    """Identidade lógica de um documento dentro de um caso. `deleted_at`
    é a exclusão lógica: nunca None -> apagado; sempre populado por
    `DocumentStorageService.excluir`, nunca por DELETE no banco."""

    __tablename__ = "document_storage_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    caso_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), index=True)
    # String aberta (não enum.Enum como DocumentType em crm_models.py) --
    # esta tabela cobre categorias que não são só "documento pedido ao
    # cliente" (I-130, contrato, comprovante, assinatura, ...) e a lista
    # cresce sem precisar de migração.
    tipo_documento: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, index=True)

    versoes: Mapped[list["DocumentoArquivoVersao"]] = relationship(
        back_populates="documento",
        cascade="all, delete-orphan",
        order_by="DocumentoArquivoVersao.numero_versao",
    )

    @property
    def versao_corrente(self) -> "DocumentoArquivoVersao | None":
        return next((v for v in self.versoes if v.is_current), None)


class DocumentoArquivoVersao(Base):
    """Um upload específico de um DocumentoArquivo. Nunca é sobrescrita:
    um novo upload cria uma nova linha com `numero_versao` incrementado
    e `is_current=True`, e `DocumentStorageService.upload` vira
    `is_current=False` na versão anterior na mesma transação. Versões
    antigas continuam com sua `storage_key` própria, recuperáveis via
    `DocumentStorageService.download(documento_id, numero_versao=N)`."""

    __tablename__ = "document_storage_versions"
    __table_args__ = (
        UniqueConstraint("documento_id", "numero_versao", name="uq_document_storage_versao_numero"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("document_storage_files.id"), index=True)
    numero_versao: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Chave opaca devolvida por StorageBackend.salvar -- formato
    # "documentos/{caso_id}/{uuid}". Nunca um caminho de disco.
    storage_key: Mapped[str] = mapped_column(String(255))

    nome_original: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(127))
    tamanho_bytes: Mapped[int] = mapped_column(Integer)
    hash: Mapped[str] = mapped_column(String(64), index=True)  # sha-256 hex do conteúdo

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    documento: Mapped[DocumentoArquivo] = relationship(back_populates="versoes")
