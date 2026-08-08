"""Blueprint do CRM (staff) -- área administrativa de Propriedades
Personalizadas (Prompt Mestre, Fase 5), 2026-08-06. Suporta "Case", "Lead"
e "Client" desde o início/extensões do mesmo dia, e "Task" desde 2026-08-08
(pedido do usuário via PDF de revisão de consistência) -- o model já era
genérico o bastante (ver docstring de CustomFieldDefinition em
app/crm_models.py) pra outra entidade sem migração nova, só faltava a UI
reconhecer mais um `entity_type`. Selecionado via `?entity=Case|Lead|
Client|Task` (padrão "Case"), mesma aba única com um seletor no topo --
não uma página separada por entidade, pra reusar tudo (criar/editar/
reordenar/arquivar/excluir) sem duplicar rota nenhuma.
"""
from __future__ import annotations

import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import AuditSource, CustomFieldDefinition, CustomFieldType
from app.db import SessionLocal
from app.services import audit_service
from app.services import custom_fields_service as cfsvc
from app.services import crm_service as svc
from app.staff_permissions import require_area

crm_custom_fields_bp = Blueprint("crm_custom_fields", __name__, url_prefix="/staff/crm/campos-personalizados")

SUPPORTED_ENTITY_TYPES = ["Case", "Lead", "Client", "Task"]

# "Visible to client" só faz sentido em entidades que têm alguma tela
# client-facing pra mostrar o valor -- Case (Meu Caso, por caso) e Client
# (Meu Caso, no topo, nível conta) têm; Lead não tem (lead não vira
# cliente logado até ser convertido).
ENTITY_TYPES_WITH_CLIENT_VISIBILITY = ["Case", "Client"]


@crm_custom_fields_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)
    require_area("customize_system")


def _entity_type() -> str:
    entity = request.values.get("entity", "Case")
    return entity if entity in SUPPORTED_ENTITY_TYPES else "Case"


@crm_custom_fields_bp.route("/")
def index():
    entity_type = _entity_type()
    return render_template(
        "crm_custom_fields.html", entity_type=entity_type, entity_types=SUPPORTED_ENTITY_TYPES,
        fields=cfsvc.active_fields(entity_type), archived=cfsvc.archived_fields(entity_type),
        field_types=list(CustomFieldType), options_for=cfsvc.options_for,
        affected_records_count=cfsvc.affected_records_count,
        show_client_visible=entity_type in ENTITY_TYPES_WITH_CLIENT_VISIBILITY)


@crm_custom_fields_bp.route("/novo", methods=["POST"])
def field_new():
    entity_type = _entity_type()
    label = request.form.get("label", "").strip()
    field_type = svc.parse_enum(CustomFieldType, request.form.get("field_type"))
    if not label or field_type is None:
        flash("Label and type are required.", "error")
        return redirect(url_for("crm_custom_fields.index", entity=entity_type))

    # Checagem de duplicidade (pedido do documento) -- bloqueia sem
    # confirmação explícita, mesmo padrão já usado em lead_convert pra
    # cliente duplicado (crm_staff_pipeline.py).
    similar = cfsvc.find_similar_field(entity_type, label)
    if similar and request.form.get("confirm_duplicate") != "1":
        flash(f'A similar field already exists: "{similar.label}". Review below before creating a new one.', "error")
        return redirect(url_for("crm_custom_fields.index", entity=entity_type))

    options_raw = [o.strip() for o in request.form.get("options", "").split("\n") if o.strip()]
    max_position = SessionLocal.query(CustomFieldDefinition).filter_by(entity_type=entity_type).count()

    field = CustomFieldDefinition(
        entity_type=entity_type, key=cfsvc.slugify_key(entity_type, label), label=label,
        field_type=field_type, required=bool(request.form.get("required")),
        default_value=request.form.get("default_value", "").strip() or None,
        options_json=json.dumps(options_raw) if options_raw else None,
        client_visible=bool(request.form.get("client_visible")),
        position=max_position, created_by_user_id=current_user.id,
    )
    SessionLocal.add(field)
    SessionLocal.flush()
    audit_service.log_change(
        "CustomFieldDefinition", field.id, "create",
        description=f"Field '{label}' ({field_type.value}) created for {entity_type}",
        user_id=current_user.id, source=AuditSource.manual)
    SessionLocal.commit()
    flash(f'Field "{label}" created.', "success")
    return redirect(url_for("crm_custom_fields.index", entity=entity_type))


_FIELD_TRACKED = ["label", "required", "default_value", "options_json", "client_visible"]


@crm_custom_fields_bp.route("/<int:field_id>/salvar", methods=["POST"])
def field_save(field_id: int):
    field = SessionLocal.get(CustomFieldDefinition, field_id)
    if field is None:
        abort(404)
    before = {f: getattr(field, f) for f in _FIELD_TRACKED}

    label = request.form.get("label", "").strip()
    if not label:
        flash("Label is required.", "error")
        return redirect(url_for("crm_custom_fields.index", entity=field.entity_type))

    options_raw = [o.strip() for o in request.form.get("options", "").split("\n") if o.strip()]

    field.label = label
    field.required = bool(request.form.get("required"))
    field.default_value = request.form.get("default_value", "").strip() or None
    field.options_json = json.dumps(options_raw) if options_raw else None
    field.client_visible = bool(request.form.get("client_visible"))

    changes = {f: (before[f], getattr(field, f)) for f in _FIELD_TRACKED}
    audit_service.log_field_changes("CustomFieldDefinition", field.id, changes, user_id=current_user.id)
    SessionLocal.commit()
    flash(f'Field "{label}" updated.', "success")
    return redirect(url_for("crm_custom_fields.index", entity=field.entity_type))


@crm_custom_fields_bp.route("/reordenar", methods=["POST"])
def field_reorder():
    entity_type = _entity_type()
    ids = request.form.getlist("stage_value")
    for position, raw_id in enumerate(ids):
        field = SessionLocal.get(CustomFieldDefinition, svc.parse_int(raw_id))
        if field is not None and field.entity_type == entity_type:
            field.position = position
    SessionLocal.commit()
    return redirect(url_for("crm_custom_fields.index", entity=entity_type))


@crm_custom_fields_bp.route("/<int:field_id>/arquivar", methods=["POST"])
def field_archive(field_id: int):
    field = SessionLocal.get(CustomFieldDefinition, field_id)
    if field is None:
        abort(404)
    field.archived = True
    audit_service.log_change("CustomFieldDefinition", field.id, "archive",
                              description=f"Field '{field.label}' archived", user_id=current_user.id)
    SessionLocal.commit()
    flash(f'Field "{field.label}" archived.', "success")
    return redirect(url_for("crm_custom_fields.index", entity=field.entity_type))


@crm_custom_fields_bp.route("/<int:field_id>/reativar", methods=["POST"])
def field_reactivate(field_id: int):
    field = SessionLocal.get(CustomFieldDefinition, field_id)
    if field is None:
        abort(404)
    field.archived = False
    field.position = SessionLocal.query(CustomFieldDefinition).filter_by(
        entity_type=field.entity_type, archived=False).count()
    audit_service.log_change("CustomFieldDefinition", field.id, "reactivate",
                              description=f"Field '{field.label}' reactivated", user_id=current_user.id)
    SessionLocal.commit()
    flash(f'Field "{field.label}" reactivated.', "success")
    return redirect(url_for("crm_custom_fields.index", entity=field.entity_type))


@crm_custom_fields_bp.route("/<int:field_id>/excluir", methods=["POST"])
def field_delete(field_id: int):
    """Exclusão permanente -- exige exclusão lógica primeiro (pedido
    explícito do documento: "utilizar exclusão lógica antes da exclusão
    permanente")."""
    field = SessionLocal.get(CustomFieldDefinition, field_id)
    if field is None:
        abort(404)
    if not field.archived:
        flash("Archive this field first before deleting it permanently.", "error")
        return redirect(url_for("crm_custom_fields.index", entity=field.entity_type))

    label = field.label
    entity_type = field.entity_type
    from app.crm_models import CustomFieldValue
    SessionLocal.query(CustomFieldValue).filter_by(field_id=field.id).delete()
    SessionLocal.delete(field)
    audit_service.log_change("CustomFieldDefinition", field_id, "delete",
                              description=f"Field '{label}' permanently deleted", user_id=current_user.id)
    SessionLocal.commit()
    flash(f'Field "{label}" permanently deleted.', "success")
    return redirect(url_for("crm_custom_fields.index", entity=entity_type))
