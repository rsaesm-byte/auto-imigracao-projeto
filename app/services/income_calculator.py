"""Motor de cálculo da Calculadora de Renda do Patrocinador (Form I-864).

Mesmo espírito do motor de elegibilidade (app/services/eligibility_rules.py):
isto é uma ferramenta informativa de pré-triagem, nunca uma determinação
oficial -- o valor real só é confirmado quando a equipe monta o I-864 de
verdade com os documentos comprobatórios (declarações de imposto, cartas do
empregador etc.). As regras abaixo (tabela de renda mínima, multiplicador de
ativos) são públicas e vêm do próprio USCIS (I-864P e 8 CFR 213a.2) -- ver
data/poverty_guidelines_i864p.json para a fonte e a data em que foi conferida.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_TABLE_PATH = ROOT / "data" / "poverty_guidelines_i864p.json"

REGIONS = ["48_states", "alaska", "hawaii"]


def _load_table() -> dict:
    return json.loads(_TABLE_PATH.read_text(encoding="utf-8"))


def _threshold(region: dict, household_size: int, use_100_pct: bool) -> int:
    amounts = region["amounts_100"] if use_100_pct else region["amounts_125"]
    increment = region["increment_100"] if use_100_pct else region["increment_125"]
    base = region["base_household_size"]
    idx = household_size - base
    if idx < 0:
        idx = 0
    if idx < len(amounts):
        return amounts[idx]
    extra = household_size - (base + len(amounts) - 1)
    return amounts[-1] + extra * increment


def evaluate(answers: dict) -> dict:
    """`answers` keys: regiao, tamanho_domicilio (int), militar_conjuge_filho
    (bool), renda_patrocinador (number), renda_adicional (number, default 0),
    conjuge_ou_filho_de_cidadao (bool), valor_ativos (number or None).

    Returns a dict with: threshold, total_income, verdict (one of
    "atende_renda" / "atende_com_ativos" / "insuficiente"), shortfall,
    required_assets (or None if no shortfall), multiplier.
    """
    table = _load_table()
    region = table["regions"][answers["regiao"]]

    household_size = max(int(answers["tamanho_domicilio"]), 2)
    use_100_pct = bool(answers.get("militar_conjuge_filho"))
    threshold = _threshold(region, household_size, use_100_pct)

    sponsor_income = float(answers.get("renda_patrocinador") or 0)
    additional_income = float(answers.get("renda_adicional") or 0)
    total_income = sponsor_income + additional_income

    result = {
        "region_label": region["label"],
        "region_label_en": region["label_en"],
        "household_size": household_size,
        "use_100_pct": use_100_pct,
        "threshold": threshold,
        "sponsor_income": sponsor_income,
        "additional_income": additional_income,
        "total_income": total_income,
    }

    if total_income >= threshold:
        result["verdict"] = "atende_renda"
        result["shortfall"] = 0
        result["required_assets"] = None
        result["multiplier"] = None
        return result

    shortfall = threshold - total_income
    is_citizen_spouse_or_child = bool(answers.get("conjuge_ou_filho_de_cidadao"))
    multiplier = 3 if is_citizen_spouse_or_child else 5
    required_assets = shortfall * multiplier

    result["shortfall"] = shortfall
    result["multiplier"] = multiplier
    result["required_assets"] = required_assets

    assets_raw = answers.get("valor_ativos")
    asset_value = float(assets_raw) if assets_raw not in (None, "") else None
    result["asset_value"] = asset_value

    if asset_value is not None and asset_value >= required_assets:
        result["verdict"] = "atende_com_ativos"
    else:
        result["verdict"] = "insuficiente"

    return result
