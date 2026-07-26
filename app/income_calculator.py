"""Blueprint da Calculadora de Renda do Patrocinador (Form I-864).

Ferramenta pública de pré-triagem, sem login e sem persistência em banco --
mesmo padrão de privacidade de app/eligibility.py e app/civics.py: os dados
financeiros digitados aqui (renda, ativos) nunca deveriam ficar guardados
mais tempo do que o necessário para mostrar o resultado na mesma requisição,
então nem sessão usamos -- é puro request-in/response-out, como uma
calculadora de verdade. O resultado é sempre framed como estimativa
informativa, nunca uma pré-aprovação -- ver income_calculator_income_disclaimer
em app/translations/{pt,en}.json e references/compliance.md.
"""
from __future__ import annotations

from flask import Blueprint, render_template, request

from app.services.income_calculator import REGIONS, evaluate

income_calculator_bp = Blueprint(
    "income_calculator", __name__, url_prefix="/calculadora-renda"
)


def _to_number(raw: str) -> float | None:
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@income_calculator_bp.route("/", methods=["GET", "POST"])
def index():
    result = None
    errors = []
    form = {
        "regiao": "48_states",
        "tamanho_domicilio": "2",
        "militar_conjuge_filho": "nao",
        "renda_patrocinador": "",
        "renda_adicional": "",
        "conjuge_ou_filho_de_cidadao": "nao",
        "valor_ativos": "",
    }

    if request.method == "POST":
        form["regiao"] = request.form.get("regiao", "48_states")
        form["tamanho_domicilio"] = request.form.get("tamanho_domicilio", "")
        form["militar_conjuge_filho"] = request.form.get("militar_conjuge_filho", "nao")
        form["renda_patrocinador"] = request.form.get("renda_patrocinador", "")
        form["renda_adicional"] = request.form.get("renda_adicional", "")
        form["conjuge_ou_filho_de_cidadao"] = request.form.get("conjuge_ou_filho_de_cidadao", "nao")
        form["valor_ativos"] = request.form.get("valor_ativos", "")

        from app.i18n import t

        household_size = _to_number(form["tamanho_domicilio"])
        sponsor_income = _to_number(form["renda_patrocinador"])

        if form["regiao"] not in REGIONS:
            errors.append(t("income_calc_error_region"))
        if household_size is None or household_size < 2:
            errors.append(t("income_calc_error_household"))
        if sponsor_income is None or sponsor_income < 0:
            errors.append(t("income_calc_error_income"))

        additional_income = _to_number(form["renda_adicional"]) or 0
        asset_value_raw = form["valor_ativos"]
        asset_value = _to_number(asset_value_raw) if asset_value_raw.strip() else None

        if not errors:
            result = evaluate({
                "regiao": form["regiao"],
                "tamanho_domicilio": household_size,
                "militar_conjuge_filho": form["militar_conjuge_filho"] == "sim",
                "renda_patrocinador": sponsor_income,
                "renda_adicional": additional_income,
                "conjuge_ou_filho_de_cidadao": form["conjuge_ou_filho_de_cidadao"] == "sim",
                "valor_ativos": asset_value,
            })

    return render_template(
        "income_calculator.html",
        form=form,
        result=result,
        errors=errors,
    )
