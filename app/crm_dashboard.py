"""Blueprint do CRM (staff) -- aba Dashboard (Prompt Mestre, Fase 3,
2026-08-06): visão geral com widgets reorganizáveis/ocultáveis, período
selecionável, cada indicador clicável pro registro correspondente. Ver
app/services/dashboard_service.py pro registro de widgets e a lógica de
computar/persistir a customização por colaborador.
"""
from __future__ import annotations

from flask import Blueprint, abort, redirect, request, render_template, url_for
from flask_login import current_user, login_required

from app.db import SessionLocal
from app.services import dashboard_service as dsvc
from app.services import reports_service as rsvc
from app.staff_permissions import require_area

crm_dashboard_bp = Blueprint("crm_dashboard", __name__, url_prefix="/staff/dashboard")


@crm_dashboard_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)
    require_area("internal_management")


@crm_dashboard_bp.route("/")
def dashboard():
    period = request.args.get("period", "month")
    if period not in rsvc.PERIODS:
        period = "month"

    visible_keys = dsvc.resolve_visible_widgets(current_user.id)
    widgets = dsvc.compute_widgets(visible_keys, period)
    hidden_keys = [k for k in dsvc.WIDGETS if k not in visible_keys]
    hidden_widgets = [{"key": k, "title": dsvc.WIDGETS[k]["title"]} for k in hidden_keys]

    return render_template(
        "crm_dashboard.html", widgets=widgets, hidden_widgets=hidden_widgets,
        periods=rsvc.PERIODS, period=period)


@crm_dashboard_bp.route("/layout", methods=["POST"])
def layout_save():
    """Nova ordem completa dos widgets VISÍVEIS -- posta pelo drag-and-drop
    (app/static/pipeline-stage-reorder.js, reaproveitado como está: o
    campo continua se chamando "stage_value" porque é o mesmo script sem
    nenhuma modificação, só usado numa lista diferente aqui)."""
    keys = request.form.getlist("stage_value")
    dsvc.save_visible_widgets(current_user.id, keys)
    SessionLocal.commit()
    return redirect(url_for("crm_dashboard.dashboard", period=request.args.get("period", "month")))


@crm_dashboard_bp.route("/widgets/<key>/ocultar", methods=["POST"])
def widget_hide(key: str):
    if key not in dsvc.WIDGETS:
        abort(404)
    visible = [k for k in dsvc.resolve_visible_widgets(current_user.id) if k != key]
    dsvc.save_visible_widgets(current_user.id, visible)
    SessionLocal.commit()
    return redirect(url_for("crm_dashboard.dashboard", period=request.args.get("period", "month")))


@crm_dashboard_bp.route("/widgets/<key>/exibir", methods=["POST"])
def widget_show(key: str):
    if key not in dsvc.WIDGETS:
        abort(404)
    visible = dsvc.resolve_visible_widgets(current_user.id)
    if key not in visible:
        visible.append(key)
    dsvc.save_visible_widgets(current_user.id, visible)
    SessionLocal.commit()
    return redirect(url_for("crm_dashboard.dashboard", period=request.args.get("period", "month")))
