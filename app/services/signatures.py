"""Salva a assinatura capturada no canvas de app/templates/meu_contrato.html
(um data URL base64 PNG, ex. "data:image/png;base64,iVBORw0KG...") em disco
-- mesma convenção de diretório de app/services/case_messages.py (nome
aleatório em instance/, sem nome original de arquivo pra guardar aqui, já
que não é upload de arquivo do usuário, é um canvas exportado)."""
from __future__ import annotations

import base64
import binascii
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SIGNATURES_DIR = ROOT / "instance" / "contract_signatures"
SIGNATURES_DIR.mkdir(parents=True, exist_ok=True)

_MIN_BYTES = 100  # a blank/near-empty canvas still exports a tiny valid PNG


def save_signature_png(data_url: str) -> str | None:
    """Retorna None (em vez de levantar) pra qualquer entrada inválida ou
    claramente em branco -- a rota chamadora trata isso como "assinatura
    não fornecida" e pede de novo, não como um erro de servidor."""
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return None
    raw_b64 = data_url.split(",", 1)[1]
    try:
        raw_bytes = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw_bytes) < _MIN_BYTES:
        return None
    dest = SIGNATURES_DIR / f"{uuid.uuid4().hex}.png"
    dest.write_bytes(raw_bytes)
    return str(dest)
