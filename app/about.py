"""Blueprint da página pública "Sobre Nós": missão, estatísticas, equipe,
bio da fundadora e contato -- conteúdo institucional real da Saes
Professional Services, sourced de saesprofessional.com/about/ (ver
data/about_page.json). Página inteiramente estática (sem login)."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, render_template

about_bp = Blueprint("about", __name__, url_prefix="/sobre")

ROOT = Path(__file__).resolve().parent.parent
_CONTENT_PATH = ROOT / "data" / "about_page.json"


def _pick(obj: dict, key: str, lang: str):
    """Mesmo padrão de app/medical_exam.py e app/wizard.py::_load_service_content:
    campo base em pt, com override opcional '<key>_en'/'<key>_es'."""
    if lang != "pt":
        alt = obj.get(f"{key}_{lang}")
        if alt is not None:
            return alt
    return obj.get(key)


def _localize(content: dict, lang: str) -> dict:
    team = [
        {"name": member["name"], "role": _pick(member, "role", lang), "photo": member["photo"]}
        for member in content["team"]
    ]

    founder_raw = content["founder"]
    founder = {
        "name": founder_raw["name"],
        "role": _pick(founder_raw, "role", lang),
        "photo": founder_raw["photo"],
        "bio": _pick(founder_raw, "bio", lang),
        "credentials_title": _pick(founder_raw, "credentials_title", lang),
        "credentials": [
            {"title": _pick(item, "title", lang), "org": item["org"]}
            for item in founder_raw["credentials"]
        ],
    }

    stats = [
        {"number": item["number"], "label": _pick(item, "label", lang)}
        for item in content["stats"]
    ]

    return {
        "hero_eyebrow": _pick(content, "hero_eyebrow", lang),
        "hero_title": _pick(content, "hero_title", lang),
        "mission": _pick(content, "mission", lang),
        "stats": stats,
        "team_title": _pick(content, "team_title", lang),
        "team_subtitle": _pick(content, "team_subtitle", lang),
        "team_intro": _pick(content, "team_intro", lang),
        "team": team,
        "founder": founder,
        "contact_title": _pick(content, "contact_title", lang),
        "contact_phone_label": _pick(content, "contact_phone_label", lang),
        "contact_email_label": _pick(content, "contact_email_label", lang),
        "contact_address_label": _pick(content, "contact_address_label", lang),
        "contact": {
            "phone": content["contact"]["phone"],
            "phone_href": content["contact"]["phone_href"],
            "email": content["contact"]["email"],
            "address": _pick(content["contact"], "address", lang),
        },
        "cta_title": _pick(content, "cta_title", lang),
        "cta_subtitle": _pick(content, "cta_subtitle", lang),
    }


@about_bp.route("/")
def index():
    from app.i18n import get_lang

    raw = json.loads(_CONTENT_PATH.read_text(encoding="utf-8"))
    content = _localize(raw, get_lang())
    return render_template("about.html", content=content)
