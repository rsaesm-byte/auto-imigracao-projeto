"""Visualizações salvas de filtro avançado -- genérico pros 5 boards
(Leads/Cases/Translations/Tasks/Financial Coaching), ver
app/crm_models.py::CrmSavedFilterView pro porquê de uma tabela só em vez
de uma por board. Gate é só `is_staff` (sem área própria) -- salvar um
filtro não concede acesso a nada novo, quem chega até aqui já passou pelo
gate de área do board de origem pra ver a tela que tem o botão "Save
view"."""
from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app.crm_models import CrmSavedFilterView
from app.db import SessionLocal

crm_saved_filters_bp = Blueprint("crm_saved_filters", __name__, url_prefix="/staff/crm/filtros")


@crm_saved_filters_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


@crm_saved_filters_bp.route("/<board_key>", methods=["GET"])
def list_views(board_key: str):
    """JSON -- usado pelo JS pra popular o seletor de visualizações
    salvas sem recarregar a página. Vê as próprias (`scope=personal`) +
    todas as `scope=shared` de qualquer colaborador."""
    rows = (
        SessionLocal.query(CrmSavedFilterView)
        .filter_by(board_key=board_key)
        .filter(
            (CrmSavedFilterView.scope == "shared")
            | (CrmSavedFilterView.created_by_id == current_user.id))
        .order_by(CrmSavedFilterView.name).all()
    )
    return jsonify([
        {"id": r.id, "name": r.name, "filter": json.loads(r.filter_json), "scope": r.scope,
         "mine": r.created_by_id == current_user.id}
        for r in rows
    ])


@crm_saved_filters_bp.route("/<board_key>/nova", methods=["POST"])
def new_view(board_key: str):
    name = request.form.get("name", "").strip()
    filter_raw = request.form.get("filter_json", "")
    scope = request.form.get("scope", "personal")
    if scope not in ("personal", "shared"):
        scope = "personal"

    if not name or not filter_raw:
        return jsonify({"error": "Name and filter are required."}), 400
    try:
        parsed = json.loads(filter_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid filter."}), 400
    if not isinstance(parsed, dict) or "conditions" not in parsed:
        return jsonify({"error": "Invalid filter."}), 400

    row = CrmSavedFilterView(
        board_key=board_key, name=name, filter_json=json.dumps(parsed), scope=scope,
        created_by_id=current_user.id)
    SessionLocal.add(row)
    SessionLocal.commit()
    return jsonify({"id": row.id, "name": row.name, "filter": parsed, "scope": row.scope, "mine": True})


@crm_saved_filters_bp.route("/<int:view_id>/excluir", methods=["POST"])
def delete_view(view_id: int):
    row = SessionLocal.get(CrmSavedFilterView, view_id)
    if row is None:
        abort(404)
    if row.created_by_id != current_user.id:
        return jsonify({"error": "You can only delete your own saved views."}), 403
    SessionLocal.delete(row)
    SessionLocal.commit()
    return jsonify({"ok": True})
