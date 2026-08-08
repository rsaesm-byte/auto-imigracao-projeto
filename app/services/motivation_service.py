"""Fase 10 (Motivation Board) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- galeria de itens inspiracionais (frase/afirmação/foto de
meta/hábito/lembrete), upload de imagem, favoritos e fixar no topo.

Validação de MIME/tamanho aqui (§14 "Attachments": "Validate MIME/file
size/ownership") -- `financial_attachments_service.py` (Fase 2) nunca
validou nada porque nunca teve um consumidor de verdade até agora; mesmo
padrão desta base de código de manter a allowlist de extensão por
feature (ver `app/staff.py::ALLOWED_PHOTO_EXTENSIONS`,
`app/services/payment_receipts.py::ALLOWED_RECEIPT_EXTENSIONS`) em vez
de um validador central.
"""
from __future__ import annotations

from pathlib import Path

from app.crm_financial_models import FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import FinancialAttachment, MotivationItem, MotivationItemType
from app.services import audit_service
from app.services.financial_attachments_service import FinancialAttachmentService

ALLOWED_MOTIVATION_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ALLOWED_MOTIVATION_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_MOTIVATION_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB -- galeria de imagens, não documento oficial


class MotivationValidationError(ValueError):
    pass


def list_items(workspace: FinancialWorkspace, *, favorites_only: bool = False) -> list[MotivationItem]:
    """Fixados primeiro, depois por `sort_order` -- "pinning" (§4) fixa
    no topo independente de tudo; dentro de cada bloco (fixados/não
    fixados) a ordem é a que o cliente arrastou-e-soltou na tela
    (`reorder_items`, pedido do usuário 2026-08-07 -- inicialmente esta
    fase não tinha reordenação manual, só pinning; adicionado depois)."""
    query = SessionLocal.query(MotivationItem).filter_by(financial_workspace_id=workspace.id)
    if favorites_only:
        query = query.filter_by(favorite=True)
    return query.order_by(MotivationItem.pinned.desc(), MotivationItem.sort_order.asc()).all()


def _next_sort_order(workspace: FinancialWorkspace) -> int:
    current_max = (
        SessionLocal.query(MotivationItem.sort_order)
        .filter_by(financial_workspace_id=workspace.id)
        .order_by(MotivationItem.sort_order.desc()).first()
    )
    return (current_max[0] + 1) if current_max else 0


def create_item(
    workspace: FinancialWorkspace, *, actor, title: str, item_type: MotivationItemType | None = None,
    categories: str | None = None, source_url: str | None = None, location: str | None = None,
) -> MotivationItem:
    if not title:
        raise MotivationValidationError("Title is required.")
    item = MotivationItem(
        financial_workspace_id=workspace.id, title=title, item_type=item_type,
        categories=categories or None, source_url=source_url or None, location=location or None,
        sort_order=_next_sort_order(workspace), created_by_id=getattr(actor, "id", None),
    )
    SessionLocal.add(item)
    SessionLocal.flush()
    audit_service.log_change(
        "MotivationItem", item.id, "created", user_id=getattr(actor, "id", None),
        description=f"Motivation board item \"{title}\" added.")
    SessionLocal.commit()
    return item


def update_item(
    item: MotivationItem, *, title: str, item_type: MotivationItemType | None = None,
    categories: str | None = None, source_url: str | None = None, location: str | None = None,
) -> MotivationItem:
    if not title:
        raise MotivationValidationError("Title is required.")
    item.title = title
    item.item_type = item_type
    item.categories = categories or None
    item.source_url = source_url or None
    item.location = location or None
    SessionLocal.commit()
    return item


def reorder_items(workspace: FinancialWorkspace, ordered_ids: list[int]) -> None:
    """Recebe a ordem completa (IDs) montada em JS depois de um drag-and-
    drop (app/static/motivation-reorder.js) e persiste `sort_order` pra
    todos de uma vez -- mesmo padrão de `crm_pipeline_settings.py::
    stage_reorder`/`service_interest_options_reorder`. IDs que não
    pertencem a este workspace são ignorados silenciosamente (defesa
    contra um POST forjado tentando reordenar item de outro cliente)."""
    items_by_id = {
        item.id: item for item in
        SessionLocal.query(MotivationItem).filter_by(financial_workspace_id=workspace.id).all()
    }
    for index, raw_id in enumerate(ordered_ids):
        item = items_by_id.get(raw_id)
        if item is None:
            continue
        item.sort_order = index
    SessionLocal.commit()


def set_image(item: MotivationItem, *, actor, filename: str, mime_type: str, content: bytes) -> FinancialAttachment:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_MOTIVATION_IMAGE_EXTENSIONS or mime_type not in ALLOWED_MOTIVATION_IMAGE_MIME_TYPES:
        raise MotivationValidationError("Invalid image -- upload a PNG, JPG, WEBP, or GIF.")
    if len(content) > MAX_MOTIVATION_IMAGE_BYTES:
        raise MotivationValidationError("Image is too large -- max 8 MB.")

    workspace = SessionLocal.get(FinancialWorkspace, item.financial_workspace_id)
    old_attachment_id = item.image_attachment_id

    attachment = FinancialAttachmentService().upload(
        workspace, record_type="MotivationItem", record_id=item.id,
        original_filename=filename, mime_type=mime_type, conteudo=content, uploaded_by=actor)
    item.image_attachment_id = attachment.id
    SessionLocal.commit()

    if old_attachment_id is not None:
        old = SessionLocal.get(FinancialAttachment, old_attachment_id)
        if old is not None:
            FinancialAttachmentService().delete(old)
    return attachment


def toggle_favorite(item: MotivationItem) -> MotivationItem:
    item.favorite = not item.favorite
    SessionLocal.commit()
    return item


def toggle_pinned(item: MotivationItem) -> MotivationItem:
    item.pinned = not item.pinned
    SessionLocal.commit()
    return item


def delete_item(item: MotivationItem, *, actor=None) -> None:
    """DELETE de verdade (não `deleted_at`) -- ver docstring do modelo em
    app/financial_planning_models.py sobre por que este é o único item da
    Fase 1-10 sem exclusão lógica. A imagem associada (se houver) é
    excluída logicamente, mesma disciplina de todo `FinancialAttachment`.
    A linha de auditoria é gravada ANTES do delete de verdade -- depois
    disso `item.id` deixa de apontar pra uma linha existente, mas
    `AuditLog.entity_id` nunca teve FK pra `entity_type` de propósito
    (registro de histórico sobrevive ao próprio registro apagado)."""
    audit_service.log_change(
        "MotivationItem", item.id, "deleted", user_id=getattr(actor, "id", None),
        description=f"Motivation board item \"{item.title}\" removed.")
    if item.image_attachment_id is not None:
        attachment = SessionLocal.get(FinancialAttachment, item.image_attachment_id)
        if attachment is not None:
            FinancialAttachmentService().delete(attachment)
    SessionLocal.delete(item)
    SessionLocal.commit()
