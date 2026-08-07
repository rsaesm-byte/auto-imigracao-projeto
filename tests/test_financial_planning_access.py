"""Fase 1 (Acesso e Workspace) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- habilitar/desabilitar o módulo self-service "Financial
Planning" nunca apaga workspace/dado, é sempre auditado, e exige a
permissão `financial_planning_manage_access` (não só `is_staff`).
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def financial_client(db):
    from app.crm_financial_models import FinancialClient
    fc = FinancialClient(full_name="Cliente de Coaching Teste")
    db.add(fc)
    db.commit()
    return fc


# --------------------------------------------------------------------------
# Unitário: app/services/financial_planning_service.py isolado
# --------------------------------------------------------------------------

def test_enable_access_creates_workspace_and_sets_fields(db, staff_user, financial_client):
    from app.crm_financial_models import FinancialPlanningStatus
    from app.services import financial_planning_service as fp_svc

    workspace = fp_svc.enable_access(financial_client, actor=staff_user)

    assert workspace.id is not None
    assert workspace.financial_client_id == financial_client.id
    assert financial_client.financial_planning_enabled is True
    assert financial_client.financial_planning_status == FinancialPlanningStatus.active
    assert financial_client.financial_planning_enabled_by_id == staff_user.id
    assert financial_client.financial_planning_started_at is not None


def test_enable_access_reuses_existing_workspace(db, staff_user, financial_client):
    """Reativar um cliente desabilitado antes não pode criar um segundo
    workspace -- preserva o mesmo container e todo dado nele."""
    from app.services import financial_planning_service as fp_svc

    w1 = fp_svc.enable_access(financial_client, actor=staff_user)
    fp_svc.disable_access(financial_client, actor=staff_user)
    w2 = fp_svc.enable_access(financial_client, actor=staff_user)

    assert w1.id == w2.id


def test_disable_access_never_deletes_workspace(db, staff_user, financial_client):
    from app.crm_financial_models import FinancialWorkspace
    from app.services import financial_planning_service as fp_svc

    workspace = fp_svc.enable_access(financial_client, actor=staff_user)
    workspace_id = workspace.id

    fp_svc.disable_access(financial_client, actor=staff_user)

    assert financial_client.financial_planning_enabled is False
    assert financial_client.financial_planning_disabled_by_id == staff_user.id
    still_there = db.get(FinancialWorkspace, workspace_id)
    assert still_there is not None, "desabilitar não pode apagar o workspace"


def test_enable_and_disable_are_audited(db, staff_user, financial_client):
    from app.services import audit_service
    from app.services import financial_planning_service as fp_svc

    fp_svc.enable_access(financial_client, actor=staff_user)
    fp_svc.disable_access(financial_client, actor=staff_user)

    actions = [h.action for h in audit_service.get_history("FinancialClient", financial_client.id)]
    assert "financial_planning_enabled" in actions
    assert "financial_planning_disabled" in actions


# --------------------------------------------------------------------------
# Integração: rotas reais, checagem de permissão
# --------------------------------------------------------------------------

def test_enable_route_requires_manage_access_permission(logged_in_client, financial_client):
    """`is_staff` sozinho (já concedido a `staff_user` pela fixture) não
    basta -- precisa também de `financial_planning_manage_access`."""
    resp = logged_in_client.post(
        f"/staff/crm/financeiro/{financial_client.id}/financial-planning/habilitar",
        follow_redirects=True)
    assert resp.status_code == 403


def test_disable_route_requires_manage_access_permission(logged_in_client, financial_client):
    resp = logged_in_client.post(
        f"/staff/crm/financeiro/{financial_client.id}/financial-planning/desabilitar",
        follow_redirects=True)
    assert resp.status_code == 403


def _grant_manage_access(db):
    """`logged_in_client` já rodou `session_transaction()` na própria
    resolução de fixture (antes do corpo do teste começar), o que
    desanexa `staff_user` da sessão -- mexer nesse objeto aqui geraria o
    mesmo `DetachedInstanceError` de tests/test_concurrency.py. Busca um
    User fresco pela sessão atual em vez de reusar a referência velha."""
    from app.models import User
    user = db.query(User).filter_by(email="staff@example.com").first()
    user.financial_planning_manage_access = True
    db.commit()


def test_enable_route_works_with_permission(logged_in_client, financial_client, db):
    from app.crm_financial_models import FinancialClient, FinancialWorkspace

    _grant_manage_access(db)
    financial_client_id = financial_client.id

    resp = logged_in_client.post(
        f"/staff/crm/financeiro/{financial_client_id}/financial-planning/habilitar",
        follow_redirects=True)
    assert resp.status_code == 200

    reloaded = db.get(FinancialClient, financial_client_id)
    assert reloaded.financial_planning_enabled is True
    assert db.query(FinancialWorkspace).filter_by(financial_client_id=financial_client_id).first() is not None


def test_disable_route_works_with_permission_and_keeps_data(logged_in_client, financial_client, db):
    from app.crm_financial_models import FinancialClient, FinancialWorkspace
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    admin = db.query(User).filter_by(email="staff@example.com").first()
    admin.financial_planning_manage_access = True
    fp_svc.enable_access(financial_client, actor=admin)
    db.commit()
    financial_client_id = financial_client.id

    resp = logged_in_client.post(
        f"/staff/crm/financeiro/{financial_client_id}/financial-planning/desabilitar",
        follow_redirects=True)
    assert resp.status_code == 200

    reloaded = db.get(FinancialClient, financial_client_id)
    assert reloaded.financial_planning_enabled is False
    assert db.query(FinancialWorkspace).filter_by(financial_client_id=financial_client_id).first() is not None, (
        "desabilitar pela rota não pode apagar o workspace nem o dado nele")
