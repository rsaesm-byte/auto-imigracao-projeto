"""Fase 2 do SAES_Financial_Planning_Master_Spec -- anexos financeiros
(comprovantes/recibos/extratos), reusando o StorageBackend plugável
(app/services/storage/, Seção 10 do CRM) pelos bytes de verdade. Sem
versionamento (diferente de app/services/document_storage_service.py) --
um anexo financeiro substitui por reenvio simples (excluir o antigo,
anexar o novo), não é um documento oficial com histórico de revisões.

Nenhuma rota usa isto ainda nesta rodada (Fase 2 não tem um recibo pra
anexar em accounts/transactions/categories/income_sources) -- fica
pronto pra quando Bills (Fase 5) precisar de comprovante de pagamento,
sem precisar inventar uma tabela de anexo nova."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import FinancialAttachment
from app.services.storage import StorageBackend, get_storage_backend


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FinancialAttachmentService:
    def __init__(self, session=SessionLocal, storage: StorageBackend | None = None):
        self.session = session
        self.storage = storage or get_storage_backend()

    def upload(
        self, workspace: FinancialWorkspace, *, record_type: str, record_id: int,
        original_filename: str, mime_type: str, conteudo: bytes, uploaded_by,
    ) -> FinancialAttachment:
        chave = f"financeiro/{workspace.id}/{uuid.uuid4().hex}"
        self.storage.salvar(conteudo, chave)

        attachment = FinancialAttachment(
            financial_workspace_id=workspace.id, record_type=record_type, record_id=record_id,
            storage_key=chave, original_filename=original_filename, mime_type=mime_type,
            file_size_bytes=len(conteudo), file_hash=hashlib.sha256(conteudo).hexdigest(),
            uploaded_by_id=getattr(uploaded_by, "id", None),
        )
        self.session.add(attachment)
        self.session.commit()
        return attachment

    def download(self, attachment: FinancialAttachment) -> bytes:
        return self.storage.ler(attachment.storage_key)

    def delete(self, attachment: FinancialAttachment) -> None:
        """Exclusão lógica -- nunca apaga o arquivo físico (mesma
        disciplina de app/document_storage_models.py)."""
        attachment.deleted_at = _utcnow()
        self.session.commit()
