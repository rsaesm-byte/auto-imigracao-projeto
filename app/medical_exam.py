"""Blueprint da página pública "Exame Médico": conteúdo de referência sobre o
exame médico de imigração para os dois caminhos do Green Card -- Ajuste de
Status (Formulário I-693, civil surgeon) e Processamento Consular (panel
physician). Página inteiramente estática (sem login, sem formulário) --
não preenchemos nem agendamos nenhum dos dois exames, ver
data/medical_exam_page.json::legal_note."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, render_template

medical_exam_bp = Blueprint("medical_exam", __name__, url_prefix="/exame-medico")

ROOT = Path(__file__).resolve().parent.parent
_CONTENT_PATH = ROOT / "data" / "medical_exam_page.json"


def _pick(obj: dict, key: str, lang: str):
    if lang == "en":
        alt = obj.get(f"{key}_en")
        if alt is not None:
            return alt
    return obj.get(key)


def _localize(content: dict, lang: str) -> dict:
    """Resolve todo o conteúdo (próprio, não overlay de tradução) para o
    idioma da sessão -- mesmo padrão usado em wizard._load_service_content()."""

    def loc_section(section: dict) -> dict:
        out = {}
        for key in list(section.keys()):
            if key.endswith("_en"):
                continue
            out[key] = _pick(section, key, lang)
        return out

    return {
        "hero_tagline": _pick(content, "hero_tagline", lang),
        "aos": loc_section(content["aos"]),
        "consular": loc_section(content["consular"]),
        "comparison_table": [
            {
                "aspect": _pick(row, "aspect", lang),
                "aos": _pick(row, "aos", lang),
                "consular": _pick(row, "consular", lang),
            }
            for row in content["comparison_table"]
        ],
        "faq": [
            {"q": _pick(item, "q", lang), "a": _pick(item, "a", lang)}
            for item in content["faq"]
        ],
        "references": [
            {"label": _pick(item, "label", lang), "url": item["url"]}
            for item in content["references"]
        ],
        "legal_note": _pick(content, "legal_note", lang),
    }


@medical_exam_bp.route("/")
def index():
    from app.i18n import get_lang

    raw = json.loads(_CONTENT_PATH.read_text(encoding="utf-8"))
    content = _localize(raw, get_lang())
    return render_template("medical_exam.html", content=content)
