"""Helpers compartilhados entre app/crm_client.py (cliente, "Meu Caso") e
app/crm_staff_ops.py (staff, /staff/crm) para a thread de mensagens do caso
(CaseMessage, ver app/crm_models.py) -- módulo próprio pra nenhuma das duas
blueprints depender da outra, mesma convenção do resto do projeto.

Convenção de upload idêntica a app/onboarding.py::_save_document (nome
aleatório em instance/, extensão validada por allowlist) -- diretório
próprio porque é um anexo de mensagem, não um documento do checklist
oficial de imigração."""
from __future__ import annotations

import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ATTACHMENTS_DIR = ROOT / "instance" / "case_message_attachments"
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".doc", ".docx"}


def save_attachment(file_storage) -> str:
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError("extensao_invalida")
    dest = ATTACHMENTS_DIR / f"{uuid.uuid4().hex}{ext}"
    file_storage.save(dest)
    return str(dest)
