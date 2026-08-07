"""Fase 1 (Acesso e Workspace) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- habilitar/desabilitar o módulo self-service "Financial
Planning" pra um FinancialClient, e criar/manter o
`FinancialWorkspace` (container 1:1 onde as fases futuras -- contas,
transações, orçamento, boletos, dívidas, metas -- vão pendurar dado).

Nunca apaga workspace nem qualquer dado financeiro ao desabilitar --
`enabled=False` só esconde o módulo da navegação do cliente (ver
app/crm_financial_client.py::_inject_has_financial_plan). Todo
enable/disable é auditado (app/services/audit_service.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.crm_financial_models import FinancialClient, FinancialPlanningStatus, FinancialWorkspace
from app.db import SessionLocal
from app.financial_planning_models import BudgetCategory, BudgetCategoryGroup
from app.services import audit_service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# (nome, grupo) -- ponto de partida razoável pro cliente já lançar
# despesas no primeiro dia sem ter que cadastrar categoria antes; ele
# pode renomear/arquivar/adicionar depois (Fase 4, tela de orçamento).
_DEFAULT_CATEGORIES = [
    ("Housing", BudgetCategoryGroup.needs),
    ("Groceries", BudgetCategoryGroup.needs),
    ("Transportation", BudgetCategoryGroup.needs),
    ("Utilities", BudgetCategoryGroup.needs),
    ("Insurance", BudgetCategoryGroup.needs),
    ("Dining Out", BudgetCategoryGroup.wants),
    ("Entertainment", BudgetCategoryGroup.wants),
    ("Shopping", BudgetCategoryGroup.wants),
    ("Savings", BudgetCategoryGroup.savings),
    ("Emergency Fund", BudgetCategoryGroup.savings),
]


def _seed_default_categories(workspace: FinancialWorkspace) -> None:
    for index, (name, group) in enumerate(_DEFAULT_CATEGORIES):
        SessionLocal.add(BudgetCategory(
            financial_workspace_id=workspace.id, name=name, category_group=group, sort_order=index))


class FinancialPlanningAccessError(Exception):
    """Levantado quando quem chama não tem
    `User.financial_planning_manage_access` -- a rota deve pegar isto e
    responder 403, nunca deixar a checagem implícita no template."""


def enable_access(financial_client: FinancialClient, *, actor) -> FinancialWorkspace:
    """Cria o `FinancialWorkspace` se ainda não existir (nunca recria um
    já existente -- reativar um cliente que foi desabilitado antes
    preserva o workspace e todo o dado nele) e liga o acesso. `actor` é
    o `User` staff que está habilitando -- checagem de permissão é
    responsabilidade de quem chama (ver
    app/crm_financial_staff.py::financial_planning_enable), esta função
    assume que já foi validada."""
    now = _utcnow()

    workspace = financial_client.workspace
    if workspace is None:
        workspace = FinancialWorkspace(
            financial_client_id=financial_client.id,
            status=FinancialPlanningStatus.active,
            created_by_id=actor.id,
        )
        SessionLocal.add(workspace)
        SessionLocal.flush()  # popula workspace.id pras categorias abaixo
        _seed_default_categories(workspace)
    else:
        workspace.status = FinancialPlanningStatus.active

    financial_client.financial_planning_enabled = True
    financial_client.financial_planning_status = FinancialPlanningStatus.active
    if financial_client.financial_planning_started_at is None:
        financial_client.financial_planning_started_at = now
    financial_client.financial_planning_enabled_at = now
    financial_client.financial_planning_enabled_by_id = actor.id
    financial_client.financial_planning_disabled_at = None
    financial_client.financial_planning_disabled_by_id = None

    audit_service.log_change(
        "FinancialClient", financial_client.id, "financial_planning_enabled",
        description=f"Financial Planning access enabled by {actor.email}",
        user_id=actor.id)
    SessionLocal.commit()
    return workspace


def disable_access(financial_client: FinancialClient, *, actor) -> None:
    """Marca o acesso como desabilitado -- NUNCA apaga o workspace nem
    nenhum dado financeiro dele, só esconde o módulo da navegação do
    cliente. `status` do workspace/cliente fica como estava (pausar
    acesso administrativamente é diferente de cancelar o plano -- quem
    quiser cancelar de vez muda `financial_planning_status` na edição
    de perfil, fora desta função)."""
    now = _utcnow()

    financial_client.financial_planning_enabled = False
    financial_client.financial_planning_disabled_at = now
    financial_client.financial_planning_disabled_by_id = actor.id

    audit_service.log_change(
        "FinancialClient", financial_client.id, "financial_planning_disabled",
        description=f"Financial Planning access disabled by {actor.email}",
        user_id=actor.id)
    SessionLocal.commit()
