"""Admin CRUD + reorder das listas de checkbox da ficha do cliente de
Financial Coaching (Income sources / Financial goals / Main challenges),
2026-08-07 -- pedido do usuário, escopo confirmado via pergunta: só
estes 3 grupos (já eram tabelas no banco); os selects de vocabulário
fechado ficam pra uma rodada seguinte. Exclusão é sempre lógica.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def option(db):
    from app.crm_financial_models import FinancialGoal

    g = FinancialGoal(name="Test Goal Alpha", sort_order=0)
    db.add(g)
    db.commit()
    return g


def test_new_option_appends_at_end_of_sort_order(logged_in_client, db):
    from app.crm_financial_models import FinancialGoal

    db.add(FinancialGoal(name="Existing Goal", sort_order=5))
    db.commit()

    resp = logged_in_client.post(
        "/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_goal/nova",
        data={"name": "New Goal"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"New Goal" in resp.data

    created = db.query(FinancialGoal).filter_by(name="New Goal").first()
    assert created.sort_order == 6


def test_new_option_requires_name(logged_in_client, db):
    from app.crm_financial_models import FinancialGoal

    before = db.query(FinancialGoal).count()
    resp = logged_in_client.post(
        "/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_goal/nova",
        data={"name": ""}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.query(FinancialGoal).count() == before


def test_new_option_rejects_duplicate_name(logged_in_client, db, option):
    resp = logged_in_client.post(
        "/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_goal/nova",
        data={"name": "Test Goal Alpha"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"already exists" in resp.data

    from app.crm_financial_models import FinancialGoal
    assert db.query(FinancialGoal).filter_by(name="Test Goal Alpha").count() == 1


def test_save_renames_option(logged_in_client, db, option):
    option_id = option.id
    resp = logged_in_client.post(
        f"/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_goal/{option_id}/salvar",
        data={"name": "Buy a Condo"}, follow_redirects=True)
    assert resp.status_code == 200

    from app.crm_financial_models import FinancialGoal
    refreshed = db.get(FinancialGoal, option_id)
    assert refreshed.name == "Buy a Condo"


def test_delete_is_soft_and_keeps_client_association(logged_in_client, db, option, staff_user):
    from app.crm_financial_models import FinancialClient, FinancialClientGoal, FinancialGoal

    fc = FinancialClient(full_name="Cliente Opcoes Teste")
    db.add(fc)
    db.commit()
    fc_id = fc.id
    db.add(FinancialClientGoal(financial_client_id=fc_id, financial_goal_id=option.id))
    db.commit()

    option_id = option.id
    resp = logged_in_client.post(
        f"/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_goal/{option_id}/excluir",
        follow_redirects=True)
    assert resp.status_code == 200

    deleted = db.get(FinancialGoal, option_id)
    assert deleted.deleted_at is not None
    # associação do cliente continua intacta -- exclusão nunca é destrutiva
    assert db.get(FinancialClientGoal, {"financial_client_id": fc_id, "financial_goal_id": option_id}) is not None


def test_deleted_option_not_offered_on_profile_edit_screen(logged_in_client, db, option, staff_user):
    from app.crm_financial_models import FinancialClient

    fc = FinancialClient(full_name="Cliente Opcoes Teste 2")
    db.add(fc)
    db.commit()
    fc_id = fc.id

    logged_in_client.post(
        f"/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_goal/{option.id}/excluir")

    resp = logged_in_client.get(f"/staff/crm/financeiro/{fc_id}/perfil")
    assert resp.status_code == 200
    assert b"Test Goal Alpha" not in resp.data


def test_reorder_persists_sort_order(logged_in_client, db):
    from app.crm_financial_models import FinancialGoal

    a = FinancialGoal(name="Goal A", sort_order=0)
    b = FinancialGoal(name="Goal B", sort_order=1)
    db.add_all([a, b])
    db.commit()
    a_id, b_id = a.id, b.id

    resp = logged_in_client.post(
        "/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_goal/reordenar",
        data={"option_id": [str(b_id), str(a_id)]}, follow_redirects=True)
    assert resp.status_code == 200

    assert db.get(FinancialGoal, b_id).sort_order == 0
    assert db.get(FinancialGoal, a_id).sort_order == 1


def test_income_source_and_challenge_kinds_also_work(logged_in_client, db):
    from app.crm_financial_models import FinancialChallenge
    from app.crm_models import IncomeSourceType

    resp = logged_in_client.post(
        "/staff/crm/configuracoes/coaching-financeiro-opcoes/income_source/nova",
        data={"name": "Freelance Work"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.query(IncomeSourceType).filter_by(name="Freelance Work").count() == 1

    resp = logged_in_client.post(
        "/staff/crm/configuracoes/coaching-financeiro-opcoes/financial_challenge/nova",
        data={"name": "Medical Debt"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.query(FinancialChallenge).filter_by(name="Medical Debt").count() == 1


def test_unknown_kind_404s(logged_in_client):
    resp = logged_in_client.post(
        "/staff/crm/configuracoes/coaching-financeiro-opcoes/not_a_real_kind/nova",
        data={"name": "X"})
    assert resp.status_code == 404


def test_options_page_renders(logged_in_client):
    resp = logged_in_client.get("/staff/crm/configuracoes/coaching-financeiro-opcoes")
    assert resp.status_code == 200
    assert b"Financial Coaching profile options" in resp.data
