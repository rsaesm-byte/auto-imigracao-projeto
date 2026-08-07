"""Upload de comprovante de pagamento (PaymentLedgerEntry.receipt_file_path
-- pedido do usuário 2026-08-06, "Attach Receipt"). Mesma convenção de
app/services/case_messages.py::save_attachment (nome aleatório em
instance/, extensão validada por allowlist), diretório próprio porque é
um anexo financeiro, não um anexo de mensagem.
"""
from __future__ import annotations

import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RECEIPTS_DIR = ROOT / "instance" / "payment_receipts"
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_RECEIPT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"}


def save_receipt(file_storage) -> str:
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        raise ValueError("extensao_invalida")
    dest = RECEIPTS_DIR / f"{uuid.uuid4().hex}{ext}"
    file_storage.save(dest)
    return str(dest)
