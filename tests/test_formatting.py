"""Padronização Global do Sistema (2026-08-07, pedido do usuário) --
formatadores centralizados de moeda/número/percentual
(app/services/formatting.py), registrados como filtros Jinja
(usd/num/pct). Casos de teste tirados direto da especificação que o
usuário forneceu.
"""
from __future__ import annotations

from app.services.crm_service import parse_dollars_to_cents
from app.services.formatting import format_number, format_percent, format_usd, format_usd_input


def test_format_usd_examples_from_spec():
    assert format_usd(0) == "$0"
    assert format_usd(50) == "$0.50"
    assert format_usd(100) == "$1"
    assert format_usd(1000) == "$10"
    assert format_usd(100000) == "$1,000"
    assert format_usd(598000) == "$5,980"
    assert format_usd(598050) == "$5,980.50"
    assert format_usd(598055) == "$5,980.55"
    assert format_usd(5196100) == "$51,961"
    assert format_usd(-1195500) == "-$11,955"
    assert format_usd(-1195550) == "-$11,955.50"
    assert format_usd(100000000) == "$1,000,000"


def test_format_usd_negative_sign_before_dollar_not_after():
    result = format_usd(-500)
    assert result == "-$5"
    assert not result.startswith("$-")


def test_format_usd_none_is_em_dash():
    assert format_usd(None) == "—"


def test_format_usd_rounds_fractional_cents():
    assert format_usd(100.6) == "$1.01"


def test_format_number_examples_from_spec():
    assert format_number(1000) == "1,000"
    assert format_number(12500) == "12,500"
    assert format_number(1250000) == "1,250,000"
    assert format_number(25.00) == "25"
    assert format_number(25.50) == "25.5"
    assert format_number(25.75) == "25.75"
    assert format_number(-1000) == "-1,000"


def test_format_number_none_is_em_dash():
    assert format_number(None) == "—"


def test_format_percent_examples_from_spec():
    assert format_percent(0) == "0%"
    assert format_percent(25) == "25%"
    assert format_percent(25.5) == "25.5%"
    assert format_percent(25.55) == "25.55%"
    assert format_percent(-5) == "-5%"


def test_format_percent_drops_trailing_zero_decimals():
    assert format_percent(100.0) == "100%"


def test_format_percent_none_is_em_dash():
    assert format_percent(None) == "—"


def test_filters_registered_on_app(app):
    assert app.jinja_env.filters["usd"] is format_usd
    assert app.jinja_env.filters["usd_input"] is format_usd_input
    assert app.jinja_env.filters["num"] is format_number
    assert app.jinja_env.filters["pct"] is format_percent


def test_format_usd_input_examples():
    assert format_usd_input(None) == ""
    assert format_usd_input(0) == ""
    assert format_usd_input(180000) == "1,800.00"
    assert format_usd_input(180050) == "1,800.50"
    assert format_usd_input(-1195500) == "-11,955.00"


def test_format_usd_input_round_trips_through_parser():
    for cents in (0, 100, 180000, 180050, 5196100, -1195550, 50):
        if cents == 0:
            continue
        formatted = format_usd_input(cents)
        assert parse_dollars_to_cents(formatted) == cents


def test_parser_tolerates_dollar_sign_and_thousands_comma():
    assert parse_dollars_to_cents("$1,800.50") == 180050
    assert parse_dollars_to_cents("1,800.50") == 180050
    assert parse_dollars_to_cents("$5,980") == 598000
    assert parse_dollars_to_cents("1800.50") == 180050


def test_parser_period_is_always_the_decimal_separator():
    """A tolerância antiga de vírgula-como-decimal (europeia) foi
    removida de propósito -- agora vírgula é sempre separador de
    milhar. "1800,50" não pode mais virar $1800.50."""
    assert parse_dollars_to_cents("1,800") == 180000
    assert parse_dollars_to_cents("") is None
    assert parse_dollars_to_cents(None) is None
    assert parse_dollars_to_cents("not a number") is None
