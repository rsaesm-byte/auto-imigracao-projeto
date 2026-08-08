"""Blueprint do CRM (staff) -- área administrativa de Automações
(Prompt Mestre, Seção 7 -- "Ciclo de vida dos serviços"), 2026-08-06. Ver
docstring de AutomationRule em app/crm_models.py pro escopo (2 ações,
gatilho por data do Case, sem e-mail/campanha/segmento).
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.crm_models import (AuditSource, AutomationActionType, AutomationRule,
                             AutomationTriggerField, ServiceCatalog)
from app.db import SessionLocal
from app.services import audit_service
from app.services import automation_service as autosvc
from app.services import crm_service as svc
from app.staff_permissions import require_area

crm_automations_bp = Blueprint("crm_automations", __name__, url_prefix="/staff/crm/automacoes")


@crm_automations_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)
    require_area("customize_system")


@crm_automations_bp.route("/")
def index():
    rules = SessionLocal.query(AutomationRule).order_by(AutomationRule.active.desc(), AutomationRule.name).all()
    services = SessionLocal.query(ServiceCatalog).order_by(ServiceCatalog.name).all()
    run_counts = {
        rule.id: {
            "success": sum(1 for r in rule.runs if r.status.value == "success"),
            "error": sum(1 for r in rule.runs if r.status.value == "error"),
        }
        for rule in rules
    }
    return render_template(
        "crm_automations.html", rules=rules, services=services,
        trigger_fields=list(AutomationTriggerField), action_types=list(AutomationActionType),
        run_counts=run_counts)


@crm_automations_bp.route("/novo", methods=["POST"])
def rule_new():
    name = request.form.get("name", "").strip()
    trigger_field = svc.parse_enum(AutomationTriggerField, request.form.get("trigger_field"))
    action_type = svc.parse_enum(AutomationActionType, request.form.get("action_type"))
    action_text = request.form.get("action_text", "").strip()
    if not name or trigger_field is None or action_type is None or not action_text:
        flash("Name, trigger, action, and message are required.", "error")
        return redirect(url_for("crm_automations.index"))

    rule = AutomationRule(
        name=name, service_catalog_id=svc.parse_int(request.form.get("service_catalog_id")),
        trigger_field=trigger_field, offset_days=svc.parse_int(request.form.get("offset_days")) or 0,
        action_type=action_type, action_text=action_text, created_by_user_id=current_user.id,
    )
    SessionLocal.add(rule)
    SessionLocal.flush()
    audit_service.log_change("AutomationRule", rule.id, "create",
                              description=f"Rule '{name}' created", user_id=current_user.id,
                              source=AuditSource.manual)
    SessionLocal.commit()
    flash(f'Automation "{name}" created.', "success")
    return redirect(url_for("crm_automations.index"))


_RULE_TRACKED = ["name", "service_catalog_id", "trigger_field", "offset_days", "action_type", "action_text"]


@crm_automations_bp.route("/<int:rule_id>/salvar", methods=["POST"])
def rule_save(rule_id: int):
    rule = SessionLocal.get(AutomationRule, rule_id)
    if rule is None:
        abort(404)
    before = {f: getattr(rule, f) for f in _RULE_TRACKED}

    name = request.form.get("name", "").strip()
    action_text = request.form.get("action_text", "").strip()
    if not name or not action_text:
        flash("Name and message are required.", "error")
        return redirect(url_for("crm_automations.index"))

    rule.name = name
    rule.service_catalog_id = svc.parse_int(request.form.get("service_catalog_id"))
    rule.trigger_field = svc.parse_enum(AutomationTriggerField, request.form.get("trigger_field"), default=rule.trigger_field)
    rule.offset_days = svc.parse_int(request.form.get("offset_days")) or 0
    rule.action_type = svc.parse_enum(AutomationActionType, request.form.get("action_type"), default=rule.action_type)
    rule.action_text = action_text

    changes = {f: (before[f], getattr(rule, f)) for f in _RULE_TRACKED}
    audit_service.log_field_changes("AutomationRule", rule.id, changes, user_id=current_user.id)
    SessionLocal.commit()
    flash(f'Automation "{name}" updated.', "success")
    return redirect(url_for("crm_automations.index"))


@crm_automations_bp.route("/<int:rule_id>/pausar", methods=["POST"])
def rule_pause(rule_id: int):
    rule = SessionLocal.get(AutomationRule, rule_id)
    if rule is None:
        abort(404)
    rule.active = False
    audit_service.log_change("AutomationRule", rule.id, "pause",
                              description=f"Rule '{rule.name}' paused", user_id=current_user.id)
    SessionLocal.commit()
    flash(f'Automation "{rule.name}" paused.', "success")
    return redirect(url_for("crm_automations.index"))


@crm_automations_bp.route("/<int:rule_id>/reativar", methods=["POST"])
def rule_resume(rule_id: int):
    rule = SessionLocal.get(AutomationRule, rule_id)
    if rule is None:
        abort(404)
    rule.active = True
    audit_service.log_change("AutomationRule", rule.id, "resume",
                              description=f"Rule '{rule.name}' resumed", user_id=current_user.id)
    SessionLocal.commit()
    flash(f'Automation "{rule.name}" resumed.', "success")
    return redirect(url_for("crm_automations.index"))


@crm_automations_bp.route("/<int:rule_id>/excluir", methods=["POST"])
def rule_delete(rule_id: int):
    rule = SessionLocal.get(AutomationRule, rule_id)
    if rule is None:
        abort(404)
    name = rule.name
    audit_service.log_change("AutomationRule", rule_id, "delete",
                              description=f"Rule '{name}' permanently deleted", user_id=current_user.id)
    SessionLocal.delete(rule)
    SessionLocal.commit()
    flash(f'Automation "{name}" deleted.', "success")
    return redirect(url_for("crm_automations.index"))


@crm_automations_bp.route("/<int:rule_id>/testar", methods=["POST"])
def rule_test(rule_id: int):
    """Modo de teste (pedido explícito do documento) -- simula sem criar
    Task/Notification/AutomationRun nenhuma, só mostra o que teria
    acontecido."""
    rule = SessionLocal.get(AutomationRule, rule_id)
    if rule is None:
        abort(404)
    results = autosvc.evaluate_rule(rule, svc.today(), dry_run=True)
    if results:
        preview = "; ".join(f"{r['case'].title} → \"{r['text']}\"" for r in results[:5])
        more = f" (+{len(results) - 5} more)" if len(results) > 5 else ""
        flash(f"Test mode: would fire for {len(results)} case(s): {preview}{more}", "success")
    else:
        flash("Test mode: no cases would trigger this rule right now.", "success")
    return redirect(url_for("crm_automations.index"))


@crm_automations_bp.route("/<int:rule_id>/executar", methods=["POST"])
def rule_run(rule_id: int):
    """Execução manual de UMA regra (pedido explícito do documento)."""
    rule = SessionLocal.get(AutomationRule, rule_id)
    if rule is None:
        abort(404)
    results = autosvc.evaluate_rule(rule, svc.today(), dry_run=False)
    successes = sum(1 for r in results if r["run"].status.value == "success")
    errors = sum(1 for r in results if r["run"].status.value == "error")
    flash(f"Ran \"{rule.name}\": {successes} succeeded, {errors} failed, out of {len(results)} matching case(s).", "success")
    return redirect(url_for("crm_automations.index"))


@crm_automations_bp.route("/executar-tudo", methods=["POST"])
def run_all():
    """Roda TODAS as regras ativas de uma vez -- mesma função usada por
    scripts/run_automations.py, só chamada manualmente aqui."""
    results_by_rule = autosvc.run_all_active_rules(svc.today(), dry_run=False)
    total = sum(len(v) for v in results_by_rule.values())
    flash(f"Ran all active automations: {total} action(s) executed across {len(results_by_rule)} rule(s).", "success")
    return redirect(url_for("crm_automations.index"))
