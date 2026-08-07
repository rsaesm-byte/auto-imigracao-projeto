"""Registro de histórico/auditoria genérico (reforma do CRM, Fase 0).

Convenção deste projeto (mesmo padrão de app/services/crm_service.py):
as funções aqui só criam o objeto AuditLog e o adicionam à sessão, nunca
chamam `SessionLocal.commit()` sozinhas -- quem chama (a rota) decide
quando persistir, geralmente no mesmo commit da própria mudança.
"""
from __future__ import annotations

import enum
from typing import Any

from app.crm_models import AuditLog, AuditSource
from app.db import SessionLocal


def _stringify(value: Any) -> str | None:
    """`str(SomeEnum.member)` on this project's `(str, enum.Enum)` enums
    returns "SomeEnum.member" (Enum.__str__, not the plain value) on the
    Python version this runs on -- would leak ugly "ServiceMode.saes_plus"
    into every history entry. Every enum in this codebase mixes in `str`,
    so `.value` is always itself a plain string -- unwrap it explicitly
    instead of trusting str()."""
    if value is None:
        return None
    if isinstance(value, enum.Enum):
        return str(value.value)
    return str(value)


def log_change(
    entity_type: str,
    entity_id: int,
    action: str,
    *,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    description: str | None = None,
    user_id: int | None = None,
    source: AuditSource = AuditSource.manual,
) -> AuditLog:
    """Cria uma linha de auditoria para `entity_type`/`entity_id`.

    `old_value`/`new_value` aceitam qualquer valor e são convertidos para
    string na gravação (enums, datas, bool etc.) -- o log é sempre texto,
    não tenta preservar o tipo original. Para uma ação sobre o registro
    inteiro (criação, exclusão, mudança de etapa) em vez de um campo
    específico, deixe `field=None` e descreva em `description`.
    """
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        field=field,
        old_value=_stringify(old_value),
        new_value=_stringify(new_value),
        description=description,
        user_id=user_id,
        source=source,
    )
    SessionLocal.add(entry)
    return entry


def log_field_changes(
    entity_type: str,
    entity_id: int,
    changes: dict[str, tuple[Any, Any]],
    *,
    user_id: int | None = None,
    source: AuditSource = AuditSource.manual,
) -> list[AuditLog]:
    """Atalho para uma rota de edição com vários campos: `changes` é
    {nome_do_campo: (valor_antigo, valor_novo)} -- grava uma linha de
    AuditLog por campo que de fato mudou (old != new), pulando os que
    ficaram iguais, pra não poluir o histórico com "nada mudou". Pedido do
    usuário 2026-08-06: histórico de alterações em todos os módulos do
    CRM -- este helper existe pra cada rota de edição não precisar repetir
    o mesmo "for field in tracked_fields: if old != new: log_change(...)"
    na mão."""
    entries = []
    for field, (old, new) in changes.items():
        if old != new:
            entries.append(log_change(
                entity_type, entity_id, "field_update", field=field,
                old_value=old, new_value=new, user_id=user_id, source=source))
    return entries


def get_history(entity_type: str, entity_id: int) -> list[AuditLog]:
    """Linha do tempo de um registro, mais recente primeiro."""
    return (
        SessionLocal.query(AuditLog)
        .filter_by(entity_type=entity_type, entity_id=entity_id)
        .order_by(AuditLog.created_at.desc())
        .all()
    )
