"""Blueprint do Estimador do Boletim de Vistos (Visa Bulletin) para
categorias de preferência familiar do I-130.

Mesmo padrão de privacidade dos outros calculadores públicos (app/
income_calculator.py, app/eligibility.py, app/civics.py): sem login, sem
persistência em banco -- request-in/response-out. Só patrocínio familiar
(o I-130 desta ferramenta não cobre patrocínio por emprego).
"""
from __future__ import annotations

import re
from datetime import date, datetime

from flask import Blueprint, render_template, request

from app.services.visa_bulletin import (
    CATEGORIES,
    classify_category,
    country_key,
    estimate_wait,
    load_bulletin,
)

visa_bulletin_bp = Blueprint("visa_bulletin", __name__, url_prefix="/estimador-boletim")

_DATE_RE = re.compile(r"^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/\d{4}$")


def _parse_form_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not _DATE_RE.match(raw):
        return None
    return datetime.strptime(raw, "%m/%d/%Y").date()


def _parse_age(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


@visa_bulletin_bp.route("/", methods=["GET", "POST"])
def index():
    result = None
    classification = None
    errors = []
    form = {
        "pet_cidadania_tipo": "cidadao",
        "rel_tipo": "conjuge",
        "ben_casado": "nao",
        "ben_idade": "",
        "ben_pais_nascimento": "",
        "priority_date": "",
    }

    if request.method == "POST":
        from app.i18n import t

        for key in form:
            form[key] = request.form.get(key, form[key])

        ben_idade = _parse_age(form["ben_idade"])
        priority_date = _parse_form_date(form["priority_date"])

        if form["priority_date"].strip() and priority_date is None:
            errors.append(t("vb_error_priority_date"))
        if form["ben_idade"].strip() and ben_idade is None:
            errors.append(t("vb_error_age"))

        if not errors:
            classification = classify_category(
                pet_status=form["pet_cidadania_tipo"],
                rel_tipo=form["rel_tipo"],
                ben_casado=form["ben_casado"] == "sim",
                ben_idade=ben_idade,
            )

            if classification["kind"] == "preference" and priority_date:
                bulletin = load_bulletin()
                country = country_key(form["ben_pais_nascimento"])
                result = estimate_wait(
                    classification["category"], country, priority_date, bulletin
                )
                result["country"] = country

    return render_template(
        "visa_bulletin.html",
        form=form,
        classification=classification,
        result=result,
        errors=errors,
        categories=CATEGORIES,
    )
