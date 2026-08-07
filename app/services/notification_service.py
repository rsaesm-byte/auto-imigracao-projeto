"""Ponto central pra criar notificações -- painel do colaborador (widget
estilo "Dynamic Island", ver app/staff_notifications.py,
app/static/notifications.js) E, desde 2026-08-06, o cliente (mesmo
widget, ver app/client_notifications.py, incluído em base.html). Qualquer
parte do sistema que precise avisar alguém em tempo (quase) real chama
`notify()` -- não grava direto no model `Notification` (app/crm_models.py)."""
from __future__ import annotations

from app.crm_models import Notification
from app.db import SessionLocal


def notify(kind: str, title: str, body: str | None = None, url: str | None = None,
           recipient_user_id: int | None = None) -> Notification:
    """Cria e comita uma notificação. Quem chama já deve estar dentro de
    uma transação em andamento (ou não) -- este commit é o único ponto de
    persistência, seguro de chamar isoladamente.

    `recipient_user_id=None` (padrão) -- aviso pra equipe toda, mesmo
    comportamento original. Preenchido -- privado pra ESSE usuário (hoje
    só usado pra avisar um cliente que um documento dele está pronto pra
    tradução, ver app/crm_staff_ops.py::required_document_translation_toggle),
    nunca aparece no widget da equipe nem no de outro cliente."""
    n = Notification(kind=kind, title=title, body=body, url=url, recipient_user_id=recipient_user_id)
    SessionLocal.add(n)
    SessionLocal.commit()
    return n
