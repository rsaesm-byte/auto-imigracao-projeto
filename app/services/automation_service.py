"""Motor de automação de ciclo de vida (Prompt Mestre, Seção 7), 2026-08-06.
Ver docstring de `AutomationRule` em app/crm_models.py pro porquê do
escopo reduzido (2 ações, sem templates de e-mail/campanha/segmento).

Este módulo NUNCA agenda nada sozinho -- quem decide QUANDO rodar é
quem chama `run_all_active_rules()`: o botão "Run now" da tela admin
(execução manual, pedido explícito do documento) ou
`scripts/run_automations.py` (pensado pra ser agendado externamente, ver
docstring do próprio script pro porquê de não usar um scheduler
embutido)."""
from __future__ import annotations

from datetime import date, timedelta

from app.crm_models import (AutomationActionType, AutomationRule, AutomationRun,
                             AutomationRunStatus, Case, CaseService, CaseStatus,
                             ServiceRole, Task)
from app.db import SessionLocal

_ACTIVE_STATUSES = [
    s for s in CaseStatus
    if s not in (CaseStatus.approved, CaseStatus.denied, CaseStatus.gave_up, CaseStatus.lost)
]


def matching_cases(rule: AutomationRule) -> list[Case]:
    """Casos ativos (não fechados) que esta regra deveria considerar --
    "interromper quando o cliente já contratou o próximo serviço" (pedido
    do documento) é tratado aqui como "não considerar caso fechado",
    interpretação simples e segura sem precisar de um modelo de
    "próximo serviço" que não existe ainda."""
    query = SessionLocal.query(Case).filter(Case.case_status.in_(_ACTIVE_STATUSES))
    if rule.service_catalog_id is not None:
        case_ids = {
            cs.case_id for cs in SessionLocal.query(CaseService).filter_by(
                service_id=rule.service_catalog_id, role=ServiceRole.current).all()
        }
        if not case_ids:
            return []
        query = query.filter(Case.id.in_(case_ids))
    return query.all()


def trigger_date_for(case: Case, rule: AutomationRule) -> date | None:
    base = getattr(case, rule.trigger_field.value, None)
    if base is None:
        return None
    return base + timedelta(days=rule.offset_days)


def already_ran(rule_id: int, case_id: int) -> bool:
    return (
        SessionLocal.query(AutomationRun)
        .filter_by(rule_id=rule_id, case_id=case_id, status=AutomationRunStatus.success)
        .first() is not None
    )


def _render_text(rule: AutomationRule, case: Case) -> str:
    return rule.action_text.replace("{case}", case.title)


def _execute_action(rule: AutomationRule, case: Case) -> str:
    """Executa de verdade -- levanta exceção em caso de falha (capturada
    por quem chama, vira um AutomationRun de status=error)."""
    text = _render_text(rule, case)
    if rule.action_type == AutomationActionType.create_task:
        from app.services import crm_service as svc
        task = Task(
            title=text, case_id=case.id, responsible_id=case.responsible_id,
            due_date=svc.today(),
        )
        SessionLocal.add(task)
        SessionLocal.flush()
        return f"Task #{task.id} created: {text}"
    elif rule.action_type == AutomationActionType.notify_responsible:
        from app.services.notification_service import notify
        # URL montada à mão (não url_for) de propósito -- este código
        # também roda fora de request context, via scripts/
        # run_automations.py (agendado externamente, sem servidor web
        # ativo nesse momento).
        notify(
            "automation", title=text, body=f"Case: {case.title}",
            url=f"/staff/crm/clientes/{case.client_id}",
            recipient_user_id=case.responsible_id,
        )
        return f"Notification sent: {text}"
    raise ValueError(f"Unknown action_type: {rule.action_type}")


def evaluate_rule(rule: AutomationRule, today: date, dry_run: bool = False) -> list[dict]:
    """Pra cada caso elegível, decide se o gatilho já venceu (trigger_date
    <= hoje) e ainda não disparou -- em `dry_run=True` (Modo de teste,
    pedido do documento) simula e retorna o que TERIA acontecido sem
    tocar no banco (nenhuma Task/Notification/AutomationRun criada)."""
    results = []
    for case in matching_cases(rule):
        trigger = trigger_date_for(case, rule)
        if trigger is None or trigger > today:
            continue
        if already_ran(rule.id, case.id):
            continue

        if dry_run:
            results.append({
                "case": case, "would_fire": True,
                "text": _render_text(rule, case), "trigger_date": trigger,
            })
            continue

        try:
            result_text = _execute_action(rule, case)
            run = AutomationRun(
                rule_id=rule.id, case_id=case.id, status=AutomationRunStatus.success,
                result_text=result_text)
        except Exception as exc:  # noqa: BLE001 -- automação não pode derrubar o processo por 1 caso ruim
            SessionLocal.rollback()
            run = AutomationRun(
                rule_id=rule.id, case_id=case.id, status=AutomationRunStatus.error,
                error_text=str(exc))
        SessionLocal.add(run)
        SessionLocal.commit()
        results.append({"case": case, "run": run})
    return results


def run_all_active_rules(today: date | None = None, dry_run: bool = False) -> dict[int, list[dict]]:
    """Roda TODAS as regras ativas -- usado tanto pelo botão "Run now"
    quanto por scripts/run_automations.py. Retorna {rule_id: [resultados]}."""
    from app.services import crm_service as svc
    today = today or svc.today()
    rules = SessionLocal.query(AutomationRule).filter_by(active=True).all()
    return {rule.id: evaluate_rule(rule, today, dry_run=dry_run) for rule in rules}
