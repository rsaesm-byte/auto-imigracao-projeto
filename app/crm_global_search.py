"""Busca global do CRM (Ctrl+K, estilo Notion) -- pedido do usuário
2026-08-06. Um único endpoint JSON consultado pelo modal em
app/static/global-search.js, que vive em app/templates/staff_base.html
(disponível em toda tela do staff, não só numa página específica).

Cobre os "bancos de dados" principais do CRM: Clientes, Leads, Casos,
Tarefas, Documentos, Tradutores. Cada tipo devolve no máximo
`_LIMIT_PER_TYPE` resultados -- é busca rápida de navegação, não um
relatório completo (isso já existe nas listas/filtros de cada módulo).
"""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request, url_for
from flask_login import current_user, login_required

from app.crm_models import Case, Client, Document, Lead, Task, Translator
from app.db import SessionLocal

crm_search_bp = Blueprint("crm_search", __name__, url_prefix="/staff")

_LIMIT_PER_TYPE = 6
_MIN_QUERY_LENGTH = 2


@crm_search_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


@crm_search_bp.route("/busca")
def search():
    q = request.args.get("q", "").strip()
    results: list[dict] = []
    if len(q) < _MIN_QUERY_LENGTH:
        return jsonify(results=results)

    like = f"%{q}%"

    for c in (SessionLocal.query(Client)
              .filter((Client.full_name.ilike(like)) | (Client.email.ilike(like)))
              .order_by(Client.full_name).limit(_LIMIT_PER_TYPE)):
        results.append({
            "type": "Client", "label": c.full_name, "sublabel": c.email or "",
            "url": url_for("crm_pipeline.client_detail", client_id=c.id),
        })

    for l in (SessionLocal.query(Lead).filter(Lead.name.ilike(like))
              .order_by(Lead.name).limit(_LIMIT_PER_TYPE)):
        results.append({
            "type": "Lead", "label": l.name, "sublabel": l.stage.value.replace("_", " ").title(),
            "url": url_for("crm_pipeline.lead_detail", lead_id=l.id),
        })

    for cs in (SessionLocal.query(Case).filter(Case.title.ilike(like))
               .order_by(Case.title).limit(_LIMIT_PER_TYPE)):
        results.append({
            "type": "Case", "label": cs.title, "sublabel": cs.client.full_name,
            "url": url_for("crm_pipeline.client_detail", client_id=cs.client_id),
        })

    for t in (SessionLocal.query(Task).filter(Task.title.ilike(like))
              .order_by(Task.title).limit(_LIMIT_PER_TYPE)):
        results.append({
            "type": "Task", "label": t.title, "sublabel": t.status.value.replace("_", " ").title(),
            "url": url_for("crm_ops.tasks"),
        })

    for d in (SessionLocal.query(Document).filter(Document.name.ilike(like))
              .order_by(Document.name).limit(_LIMIT_PER_TYPE)):
        results.append({
            "type": "Document", "label": d.name,
            "sublabel": d.client.full_name if d.client else "",
            "url": url_for("crm_ops.case_documents", case_id=d.case_id),
        })

    for tr in (SessionLocal.query(Translator).filter(Translator.full_name.ilike(like))
               .order_by(Translator.full_name).limit(_LIMIT_PER_TYPE)):
        results.append({
            "type": "Translator", "label": tr.full_name, "sublabel": "",
            "url": url_for("crm_translations.translator_detail", translator_id=tr.id),
        })

    return jsonify(results=results)
