"""Calculadoras de janela de protocolo (data-math puro, sem I/O) para as
duas páginas de serviço que pedem isso explicitamente:

- N-400 (Cidadania): USCIS permite protocolar até 90 dias antes de completar
  o tempo de residência exigido -- 5 anos na regra geral, ou 3 anos se
  cônjuge de cidadão(ã) americano(a) (INA 316(a) / 319(a)). Texto oficial
  fonte: a própria página do formulário N-400 em uscis.gov.
- I-751 (Removal of Conditions): a janela de protocolo é os 90 dias
  imediatamente antes da data de expiração do Green Card condicional --
  mesma lógica, cálculo mais simples (só subtração). Fonte oficial:
  https://www.uscis.gov/forms/when-to-file-your-petition-to-remove-conditions
  (a mesma "Filing Date Calculator" que a própria página do USCIS oferece).

Mesmo espírito das outras calculadoras públicas deste projeto
(app/services/income_calculator.py, app/services/eligibility_rules.py):
informativo, nunca uma determinação oficial -- ver references/compliance.md.
"""
from __future__ import annotations

from datetime import date, timedelta

FILING_WINDOW_DAYS = 90


class InvalidDateError(ValueError):
    pass


def parse_mdy(month: str, day: str, year: str) -> date:
    try:
        m, d, y = int(month), int(day), int(year)
        return date(y, m, d)
    except (TypeError, ValueError) as exc:
        raise InvalidDateError(str(exc)) from exc


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29 de fevereiro em ano não bissexto no destino.
        return d.replace(month=2, day=28, year=d.year + years)


def compute_n400_filing_window(gc_date: date, years: int) -> dict:
    """`years` é 5 (regra geral) ou 3 (cônjuge de cidadão(ã) americano(a),
    INA 319(a)) -- quem decide qual se aplica é a página, não esta função."""
    eligible_date = _add_years(gc_date, years)
    window_start = eligible_date - timedelta(days=FILING_WINDOW_DAYS)
    today = date.today()
    return {
        "eligible_date": eligible_date,
        "window_start": window_start,
        "can_file_now": today >= window_start,
        "years": years,
    }


def compute_i751_filing_date(expiration_date: date) -> dict:
    earliest_filing_date = expiration_date - timedelta(days=FILING_WINDOW_DAYS)
    today = date.today()
    return {
        "expiration_date": expiration_date,
        "earliest_filing_date": earliest_filing_date,
        "can_file_now": today >= earliest_filing_date,
    }
