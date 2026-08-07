"""Prompt Mestre, Fase 5 ("Propriedades e campos personalizados"),
2026-08-06 -- área administrativa pra criar campos novos em uma entidade
do CRM sem precisar de migração. Primeira versão só ligada a "Case" (ver
docstring de CustomFieldDefinition em app/crm_models.py pro porquê do
escopo reduzido frente aos 23 tipos/recursos do documento original).
"""
from __future__ import annotations

import json
import re
from datetime import date

from app.crm_models import CustomFieldDefinition, CustomFieldType, CustomFieldValue
from app.db import SessionLocal


def slugify_key(entity_type: str, label: str) -> str:
    """Identificador interno estável a partir do rótulo, único por
    entidade -- pedido do documento ("verificar identificador interno").
    Nunca reexpõe acento/espaço/maiúscula; se colidir com um campo já
    existente (mesmo arquivado -- a UNIQUE constraint cobre os dois),
    acrescenta um sufixo numérico."""
    base = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_") or "campo"
    key = base
    n = 2
    while SessionLocal.query(CustomFieldDefinition).filter_by(entity_type=entity_type, key=key).first() is not None:
        key = f"{base}_{n}"
        n += 1
    return key


def active_fields(entity_type: str) -> list[CustomFieldDefinition]:
    return (
        SessionLocal.query(CustomFieldDefinition)
        .filter_by(entity_type=entity_type, archived=False)
        .order_by(CustomFieldDefinition.position).all()
    )


def archived_fields(entity_type: str) -> list[CustomFieldDefinition]:
    return (
        SessionLocal.query(CustomFieldDefinition)
        .filter_by(entity_type=entity_type, archived=True)
        .order_by(CustomFieldDefinition.label).all()
    )


def options_for(field: CustomFieldDefinition) -> list[str]:
    if not field.options_json:
        return []
    try:
        return json.loads(field.options_json)
    except (json.JSONDecodeError, TypeError):
        return []


def parse_multi_select(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def find_similar_field(entity_type: str, label: str, exclude_id: int | None = None) -> CustomFieldDefinition | None:
    """Checagem de duplicidade ao criar/renomear (pedido do documento:
    "verificar nomes semelhantes... alertar o usuário"). Simples de
    propósito (substring case-insensitive nos dois sentidos, não fuzzy
    matching de verdade) -- mesma filosofia já usada em
    crm_service.py::find_possible_duplicate_clients: melhor avisar demais
    (um clique a mais confirmando) do que deixar passar batido."""
    label_norm = label.strip().lower()
    if not label_norm:
        return None
    query = SessionLocal.query(CustomFieldDefinition).filter_by(entity_type=entity_type, archived=False)
    if exclude_id is not None:
        query = query.filter(CustomFieldDefinition.id != exclude_id)
    for existing in query.all():
        existing_norm = existing.label.strip().lower()
        if existing_norm == label_norm or label_norm in existing_norm or existing_norm in label_norm:
            return existing
    return None


def affected_records_count(field: CustomFieldDefinition) -> int:
    """"Quantidade de registros afetados" (pedido do documento, antes de
    uma alteração perigosa) -- quantos registros já têm um valor
    preenchido pra este campo."""
    return (
        SessionLocal.query(CustomFieldValue)
        .filter_by(field_id=field.id)
        .filter(CustomFieldValue.value_text.isnot(None), CustomFieldValue.value_text != "")
        .count()
    )


def values_for_entity(entity_type: str, entity_id: int) -> dict[int, str | None]:
    """{field_id: value_text} pra este registro -- sempre string crua
    (quem exibe decide como formatar por tipo, ver `display_value`)."""
    rows = (
        SessionLocal.query(CustomFieldValue)
        .filter_by(entity_type=entity_type, entity_id=entity_id).all()
    )
    return {v.field_id: v.value_text for v in rows}


def display_value(field: CustomFieldDefinition, raw: str | None) -> str:
    """Formata `value_text` cru pro tipo do campo -- usado tanto na ficha
    do staff (modo leitura fora do form) quanto na tela do cliente."""
    if raw is None or raw == "":
        return "—"
    if field.field_type == CustomFieldType.checkbox:
        return "Yes" if raw == "1" else "No"
    if field.field_type == CustomFieldType.currency:
        try:
            return f"${float(raw):,.2f}"
        except ValueError:
            return raw
    if field.field_type == CustomFieldType.percent:
        try:
            return f"{float(raw):g}%"
        except ValueError:
            return raw
    if field.field_type == CustomFieldType.date:
        try:
            return date.fromisoformat(raw).strftime("%m/%d/%Y")
        except ValueError:
            return raw
    if field.field_type == CustomFieldType.multi_select:
        try:
            return ", ".join(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return raw
    return raw


def save_values(entity_type: str, entity_id: int, fields: list[CustomFieldDefinition], form) -> None:
    """Grava os valores de TODOS os campos ativos de uma vez (um form só
    na ficha do registro) -- `form` é o `request.form` do Flask
    (werkzeug MultiDict, pra `getlist` funcionar em multi_select). Não
    comita sozinha, mesma convenção do resto de app/services/."""
    for field in fields:
        key = f"custom_{field.id}"
        if field.field_type == CustomFieldType.checkbox:
            raw = "1" if form.get(key) else "0"
        elif field.field_type == CustomFieldType.multi_select:
            selected = form.getlist(key)
            raw = json.dumps(selected) if selected else None
        else:
            text = form.get(key, "").strip()
            raw = text or None

        existing = (
            SessionLocal.query(CustomFieldValue)
            .filter_by(field_id=field.id, entity_type=entity_type, entity_id=entity_id).first()
        )
        if existing is None:
            if raw is not None:
                SessionLocal.add(CustomFieldValue(
                    field_id=field.id, entity_type=entity_type, entity_id=entity_id, value_text=raw))
        else:
            existing.value_text = raw
