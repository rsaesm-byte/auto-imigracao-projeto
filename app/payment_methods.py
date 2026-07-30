"""Blueprint da página pública "Formas de Pagamento": Zelle, Venmo, wire
transfer e cartão de crédito à vista -- dados reais de recebimento da Saes
Professional Services (ver data/payment_methods.json). Página inteiramente
estática (sem login)."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, render_template

payment_methods_bp = Blueprint("payment_methods", __name__, url_prefix="/formas-pagamento")

ROOT = Path(__file__).resolve().parent.parent
_CONTENT_PATH = ROOT / "data" / "payment_methods.json"


def _pick(obj: dict, key: str, lang: str):
    if lang != "pt":
        alt = obj.get(f"{key}_{lang}")
        if alt is not None:
            return alt
    return obj.get(key)


def _localize(content: dict, lang: str) -> dict:
    keys = [
        "hero_eyebrow", "hero_title", "hero_subtitle", "safety_note",
        "zelle_title", "zelle_enrolled_label", "zelle_note",
        "venmo_title",
        "wire_title", "wire_subtitle", "wire_account_label",
        "wire_routing_title", "wire_routing_paper_note", "wire_routing_wires_note",
        "card_title", "card_body",
    ]
    out = {key: _pick(content, key, lang) for key in keys}
    # Campos que não variam por idioma (números, handles, nomes próprios, imagens).
    out.update({
        "zelle_phone": content["zelle_phone"],
        "zelle_enrolled_name": content["zelle_enrolled_name"],
        "zelle_qr": content["zelle_qr"],
        "venmo_name": content["venmo_name"],
        "venmo_handle": content["venmo_handle"],
        "venmo_qr": content["venmo_qr"],
        "wire_account_number": content["wire_account_number"],
        "wire_routing_paper_label": content["wire_routing_paper_label"],
        "wire_routing_paper_number": content["wire_routing_paper_number"],
        "wire_routing_wires_label": content["wire_routing_wires_label"],
        "wire_routing_wires_number": content["wire_routing_wires_number"],
    })
    return out


@payment_methods_bp.route("/")
def index():
    from app.i18n import get_lang

    raw = json.loads(_CONTENT_PATH.read_text(encoding="utf-8"))
    content = _localize(raw, get_lang())
    return render_template("payment_methods.html", content=content)
