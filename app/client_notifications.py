"""API de polling do widget de notificação do CLIENTE -- mesmo widget e
mesmo estilo "Dynamic Island" da equipe (ver app/staff_notifications.py,
app/templates/_notification_widget.html, app/static/notifications.js),
mas escopado só às notificações PRIVADAS deste usuário
(Notification.recipient_user_id == current_user.id). Pedido do usuário
2026-08-06: quando um documento do cliente é marcado como precisando de
tradução, ele deve ser avisado com a mesma interface da equipe, sem ver
(nem poder marcar como lida) nenhuma notificação de outro cliente ou da
equipe. Notificações em si continuam sendo criadas só por
app/services/notification_service.py::notify(), nunca aqui."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.crm_models import Notification
from app.db import SessionLocal

client_notifications_bp = Blueprint(
    "client_notifications", __name__, url_prefix="/meu-caso/notifications")


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


@client_notifications_bp.route("/poll")
@login_required
def poll():
    since_id = request.args.get("since_id", type=int) or 0
    limit = min(request.args.get("limit", default=20, type=int), 50)

    query = SessionLocal.query(Notification).filter(Notification.recipient_user_id == current_user.id)
    if since_id:
        query = query.filter(Notification.id > since_id).order_by(Notification.id.asc())
    else:
        query = query.order_by(Notification.id.desc()).limit(limit)
    rows = query.all()
    if not since_id:
        rows = list(reversed(rows))

    latest = (
        SessionLocal.query(Notification)
        .filter(Notification.recipient_user_id == current_user.id)
        .order_by(Notification.id.desc()).first()
    )
    unread_count = SessionLocal.query(Notification).filter(
        Notification.recipient_user_id == current_user.id, Notification.read_at.is_(None)).count()

    return jsonify({
        "notifications": [_serialize(n) for n in rows],
        "latest_id": latest.id if latest else 0,
        "unread_count": unread_count,
    })


@client_notifications_bp.route("/marcar-lidas", methods=["POST"])
@login_required
def mark_read():
    now = datetime.now(timezone.utc)
    SessionLocal.query(Notification).filter(
        Notification.recipient_user_id == current_user.id, Notification.read_at.is_(None)
    ).update({"read_at": now}, synchronize_session=False)
    SessionLocal.commit()
    return jsonify({"ok": True})
