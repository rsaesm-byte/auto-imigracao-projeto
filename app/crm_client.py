"""Painel do cliente "Meu Caso" -- somente leitura, mostra o(s) Case(s) do
CRM (app/crm_models.py) vinculados ao usuário logado via Client.user_id.

Isolamento (o ponto mais sensível deste módulo): a busca do Client é SEMPRE
por `Client.user_id == current_user.id` -- esta rota nunca aceita
client_id/case_id vindo de querystring ou form. Um cliente jamais pode ver
o caso de outro cliente através daqui.
"""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.crm_models import Client
from app.db import SessionLocal
from app.services.crm_service import case_pending_documents

crm_client_bp = Blueprint("crm_client", __name__)


def _client_for_current_user() -> Client | None:
    if not current_user.is_authenticated:
        return None
    return SessionLocal.query(Client).filter_by(user_id=current_user.id).first()


@crm_client_bp.app_context_processor
def _inject_has_crm_case():
    # Blueprint.app_context_processor injeta contexto pra TODA a aplicação
    # (não só nas rotas deste blueprint) -- é assim que base.html decide
    # mostrar o link "Meu Caso" sem app/__init__.py precisar saber deste
    # módulo (o registro do blueprint em si é feito numa etapa separada).
    return {"has_crm_case": _client_for_current_user() is not None}


@crm_client_bp.route("/meu-caso")
@login_required
def meu_caso():
    from app.i18n import t

    client = _client_for_current_user()
    if client is None:
        flash(t("my_case_none_yet"), "success")
        return redirect(url_for("wizard.dashboard"))

    cases = [
        {"case": case, "pending_documents": case_pending_documents(case)}
        for case in client.cases
    ]
    recent_communications = sorted(
        client.communications, key=lambda c: c.occurred_at, reverse=True)[:5]

    return render_template(
        "meu_caso.html", client=client, cases=cases,
        recent_communications=recent_communications)
