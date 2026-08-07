"""API de polling do widget de notificação do painel do colaborador
(estilo "Dynamic Island", ver app/static/notifications.js,
app/templates/_notification_widget.html). Notificações em si são criadas
por app/services/notification_service.py::notify(), nunca aqui -- este
blueprint só lê e marca como lidas."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app.crm_models import Notification
from app.db import SessionLocal

staff_notifications_bp = Blueprint("staff_notifications", __name__, url_prefix="/staff/notifications")


@staff_notifications_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "url": n.url,
        "created_at": n.created_at.isoformat(),
        "read": n.read_at is not None,
    }


@staff_notifications_bp.route("/poll")
def poll():
    """`since_id`: devolve só notificações mais novas que esse id (uso do
    polling em loop). Sem `since_id` (ou 0): devolve as últimas `limit`
    (uso do carregamento inicial do widget/histórico).

    `recipient_user_id IS NULL` -- só os avisos pra equipe toda (ver
    app/services/notification_service.py::notify). Desde 2026-08-06
    também existem notificações PRIVADAS de um cliente específico
    (recipient_user_id preenchido, ver app/client_notifications.py) --
    esse filtro é o que impede uma delas de vazar pro widget da equipe."""
    since_id = request.args.get("since_id", type=int) or 0
    limit = min(request.args.get("limit", default=20, type=int), 50)

    query = SessionLocal.query(Notification).filter(Notification.recipient_user_id.is_(None))
    if since_id:
        query = query.filter(Notification.id > since_id).order_by(Notification.id.asc())
    else:
        query = query.order_by(Notification.id.desc()).limit(limit)
    rows = query.all()
    if not since_id:
        rows = list(reversed(rows))

    latest = (
        SessionLocal.query(Notification)
        .filter(Notification.recipient_user_id.is_(None))
        .order_by(Notification.id.desc()).first()
    )
    unread_count = SessionLocal.query(Notification).filter(
        Notification.recipient_user_id.is_(None), Notification.read_at.is_(None)).count()

    return jsonify({
        "notifications": [_serialize(n) for n in rows],
        "latest_id": latest.id if latest else 0,
        "unread_count": unread_count,
    })


@staff_notifications_bp.route("/marcar-lidas", methods=["POST"])
def mark_read():
    now = datetime.now(timezone.utc)
    SessionLocal.query(Notification).filter(
        Notification.recipient_user_id.is_(None), Notification.read_at.is_(None)
    ).update({"read_at": now}, synchronize_session=False)
    SessionLocal.commit()
    return jsonify({"ok": True})
