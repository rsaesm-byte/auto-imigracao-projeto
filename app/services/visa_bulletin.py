"""Motor de estimativa do Boletim de Vistos (Visa Bulletin) para as
categorias de preferência familiar do I-130.

Mesmo espírito dos outros motores de pré-triagem (app/services/
income_calculator.py, app/services/eligibility_rules.py): ferramenta
informativa, nunca uma determinação oficial -- ver
data/visa_bulletin.json para a fonte dos dados e references/compliance.md
para o enquadramento de "não é aconselhamento jurídico".

Só cobre patrocínio familiar (Family-Sponsored) -- o I-130 desta
ferramenta não cobre patrocínio por emprego.
"""
from __future__ import annotations

import json
import unicodedata
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_TABLE_PATH = ROOT / "data" / "visa_bulletin.json"

CATEGORIES = ["F1", "F2A", "F2B", "F3", "F4"]

# Chargeability especial: só México, Filipinas, Índia e China têm coluna
# própria no boletim familiar; qualquer outro país de nascimento usa "all"
# (All Chargeability Areas Except Those Listed).
_COUNTRY_SYNONYMS = {
    "mexico": {"mexico", "méxico"},
    "philippines": {"philippines", "filipinas"},
    "india": {"india", "índia"},
    "china": {"china", "republica popular da china", "república popular da china", "prc"},
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def country_key(raw_country: str | None) -> str:
    """Mapeia um país de nascimento em texto livre (pt ou en, com ou sem
    acento) para uma das 5 colunas do boletim. Qualquer país não listado
    cai em 'all', que é a coluna correta pra maioria dos casos -- só
    México/Filipinas/Índia/China têm fila própria no boletim familiar."""
    if not raw_country:
        return "all"
    normalized = _strip_accents(raw_country.strip().lower())
    for key, synonyms in _COUNTRY_SYNONYMS.items():
        if normalized in {_strip_accents(s) for s in synonyms}:
            return key
    return "all"


def load_bulletin() -> dict:
    return json.loads(_TABLE_PATH.read_text(encoding="utf-8"))


def _age(birth: date, today: date) -> int:
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def classify_category(
    pet_status: str,
    rel_tipo: str,
    ben_casado: bool,
    ben_idade: int | None,
) -> dict:
    """pet_status: 'cidadao' | 'lpr'. rel_tipo: 'conjuge' | 'filho' |
    'pai_mae' | 'irmao'. ben_casado: beneficiário(a) está casado(a) hoje.
    ben_idade: idade do/a beneficiário(a) em anos, ou None se não informada.

    Retorna {"kind": "immediate_relative" | "preference" | "not_eligible",
    "category": um de CATEGORIES ou None, "cspa_check": bool}. "cspa_check"
    sinaliza que o resultado pode mudar por causa do Child Status
    Protection Act (idade "congela" em certos casos) -- nunca calculado
    aqui, só sinalizado para confirmação com a equipe."""
    cspa_zone = ben_idade is not None and 19 <= ben_idade <= 23

    if pet_status == "cidadao":
        if rel_tipo == "conjuge":
            return {"kind": "immediate_relative", "category": None, "cspa_check": False}
        if rel_tipo == "pai_mae":
            return {"kind": "immediate_relative", "category": None, "cspa_check": False}
        if rel_tipo == "filho":
            if ben_casado:
                return {"kind": "preference", "category": "F3", "cspa_check": False}
            if ben_idade is not None and ben_idade < 21:
                return {"kind": "immediate_relative", "category": None, "cspa_check": cspa_zone}
            return {"kind": "preference", "category": "F1", "cspa_check": cspa_zone}
        if rel_tipo == "irmao":
            return {"kind": "preference", "category": "F4", "cspa_check": False}

    elif pet_status == "lpr":
        if rel_tipo == "conjuge":
            return {"kind": "preference", "category": "F2A", "cspa_check": False}
        if rel_tipo == "filho":
            if ben_casado:
                return {"kind": "not_eligible", "category": None, "cspa_check": False}
            if ben_idade is not None and ben_idade < 21:
                return {"kind": "preference", "category": "F2A", "cspa_check": cspa_zone}
            return {"kind": "preference", "category": "F2B", "cspa_check": cspa_zone}
        if rel_tipo in ("pai_mae", "irmao"):
            return {"kind": "not_eligible", "category": None, "cspa_check": False}

    return {"kind": "unknown", "category": None, "cspa_check": False}


def _parse_cell(raw: str | None) -> date | str | None:
    """Uma célula do boletim é uma data ISO, o sentinela 'current', ou
    None (não confirmado nesta fonte)."""
    if raw is None:
        return None
    if raw == "current":
        return "current"
    return datetime.strptime(raw, "%Y-%m-%d").date()


def estimate_wait(category: str, country: str, priority_date: date, bulletin: dict | None = None, today: date | None = None) -> dict:
    """category: um de CATEGORIES. country: uma chave de country_key().
    priority_date: data em que o I-130 foi recebido pelo USCIS (do I-797C).

    Retorna um dict com o status ('current', 'waiting', 'no_data',
    'no_movement_data') e, quando aplicável, a data de corte atual, os
    meses restantes estimados, e a data de corte da Final Action (se
    disponível) só como informação complementar."""
    bulletin = bulletin or load_bulletin()
    today = today or date.today()

    chart_key = bulletin["family_filing_chart_in_use"]
    chart = bulletin[chart_key]
    current_cell = _parse_cell(chart["current_month"].get(category, {}).get(country))
    previous_cell = None
    if chart.get("previous_month"):
        previous_cell = _parse_cell(chart["previous_month"].get(category, {}).get(country))

    fa_chart = bulletin.get("final_action_dates", {})
    fa_current = None
    if fa_chart.get("current_month"):
        fa_current = _parse_cell(fa_chart["current_month"].get(category, {}).get(country))

    result = {
        "chart_used": chart_key,
        "bulletin_month": bulletin["current_month"],
        "final_action_cutoff": fa_current if isinstance(fa_current, date) else None,
        "final_action_current": fa_current == "current",
    }

    if current_cell is None:
        result["status"] = "no_data"
        return result

    if current_cell == "current":
        result["status"] = "current"
        return result

    if priority_date <= current_cell:
        result["status"] = "current"
        result["cutoff"] = current_cell
        return result

    result["status"] = "waiting"
    result["cutoff"] = current_cell
    gap_days = (priority_date - current_cell).days
    result["gap_days"] = gap_days

    if previous_cell is None or previous_cell == "current" or not isinstance(previous_cell, date):
        result["estimated_months"] = None
        return result

    movement_days = (current_cell - previous_cell).days
    if movement_days <= 0:
        result["estimated_months"] = None
        result["no_recent_movement"] = True
        return result

    result["estimated_months"] = round(gap_days / movement_days, 1)
    return result
