"""Painel do cliente "Meu Plano Financeiro" -- somente leitura, espelha
app/crm_client.py (Fase 1, "Meu Caso") pro módulo de Coaching Financeiro.

Isolamento (mesmo ponto sensível de app/crm_client.py): a busca do
FinancialClient é SEMPRE por `FinancialClient.user_id == current_user.id`,
nunca aceita id vindo de querystring/form.
"""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.crm_financial_models import FinancialClient
from app.db import SessionLocal
from app.services import crm_financial_service as fsvc

crm_financial_client_bp = Blueprint("crm_financial_client", __name__)


def _financial_client_for_current_user() -> FinancialClient | None:
    if not current_user.is_authenticated:
        return None
    return SessionLocal.query(FinancialClient).filter_by(user_id=current_user.id).first()


@crm_financial_client_bp.app_context_processor
def _inject_has_financial_plan():
    return {"has_financial_plan": _financial_client_for_current_user() is not None}


@crm_financial_client_bp.route("/meu-plano-financeiro")
@login_required
def meu_plano():
    from app.i18n import t

    fc = _financial_client_for_current_user()
    if fc is None:
        flash(t("my_financial_plan_none_yet"), "success")
        return redirect(url_for("wizard.dashboard"))

    return render_template(
        "meu_plano_financeiro.html", fc=fc,
        sessions_completed=fsvc.sessions_completed(fc),
        sessions_remaining=fsvc.sessions_remaining(fc),
        completion_pct=fsvc.completion_pct(fc),
        last_session_at=fsvc.last_session_at(fc),
        next_session_at=fsvc.next_session_at(fc),
        pending_tasks=fsvc.pending_financial_tasks(fc),
        remaining_balance_cents=fsvc.remaining_balance_cents(fc))
