"""Upload do arquivo de um Document (app/crm_models.py, "Documentos do
Caso") pelo próprio cliente -- pedido do usuário 2026-08-06: até aqui
`Document.file_path` existia no banco mas nenhuma rota (cliente ou staff)
jamais escrevia nele; o cliente só via o NOME do documento pedido, sem
como enviar o arquivo de verdade contra aquele pedido específico (só
existia esse caminho para o checklist separado de onboarding, ver
app/onboarding.py). Mesma convenção de upload de app/services/
case_messages.py::save_attachment -- nome aleatório em instance/,
extensão validada por allowlist."""
from __future__ import annotations

import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CASE_DOCUMENTS_DIR = ROOT / "instance" / "case_documents"
CASE_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_CASE_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".doc", ".docx"}


def save_case_document(file_storage) -> str:
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in ALLOWED_CASE_DOCUMENT_EXTENSIONS:
        raise ValueError("extensao_invalida")
    dest = CASE_DOCUMENTS_DIR / f"{uuid.uuid4().hex}{ext}"
    file_storage.save(dest)
    return str(dest)
