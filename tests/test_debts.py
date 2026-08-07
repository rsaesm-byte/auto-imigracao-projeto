"""Fase 8 (Debt Management) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- registro de dívida, pagamentos, ordenação snowball/
avalanche/custom, e o simulador de quitação (amortização simples).
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Debts Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


@pytest.fixture()
def account(db, workspace, staff_user):
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc

    return accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)


# --------------------------------------------------------------------------
# Debts
# --------------------------------------------------------------------------

def test_create_debt_requires_name(db, workspace):
    from app.services import debts_service

    with pytest.raises(debts_service.DebtValidationError):
        debts_service.create_debt(workspace, actor=None, debt_name="", current_balance_cents=100000)


def test_create_debt_rejects_negative_balance(db, workspace):
    from app.services import debts_service

    with pytest.raises(debts_service.DebtValidationError):
        debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=-100)


def test_create_debt_rejects_invalid_due_day(db, workspace):
    from app.services import debts_service

    with pytest.raises(debts_service.DebtValidationError):
        debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000, due_day=32)


def test_soft_delete_debt(db, workspace):
    from app.services import debts_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    debts_service.soft_delete_debt(debt)
    assert debt.deleted_at is not None


# --------------------------------------------------------------------------
# Payments
# --------------------------------------------------------------------------

def test_record_payment_reduces_balance(db, workspace, account):
    from app.services import debts_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    debts_service.record_payment(
        debt, amount_cents=20000, payment_date=date(2026, 8, 1), paid_from_account_id=account.id)
    assert debt.current_balance_cents == 80000


def test_record_payment_marks_paid_off_at_zero(db, workspace):
    from app.financial_planning_models import DebtStatus
    from app.services import debts_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=50000)
    debts_service.record_payment(debt, amount_cents=50000, payment_date=date(2026, 8, 1))
    assert debt.current_balance_cents == 0
    assert debt.status == DebtStatus.paid_off


def test_record_payment_uses_principal_when_given(db, workspace):
    from app.services import debts_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    debts_service.record_payment(
        debt, amount_cents=25000, principal_amount_cents=20000, interest_amount_cents=5000,
        payment_date=date(2026, 8, 1))
    assert debt.current_balance_cents == 80000  # só o principal abate o saldo


def test_record_payment_rejects_non_positive_amount(db, workspace):
    from app.services import debts_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    with pytest.raises(debts_service.DebtValidationError):
        debts_service.record_payment(debt, amount_cents=0, payment_date=date(2026, 8, 1))


def test_record_payment_rejects_account_from_another_workspace(db, workspace, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import AccountType
    from app.services import financial_accounts_service as accounts_svc
    from app.services import financial_planning_service as fp_svc
    from app.services import debts_service

    other_fc = FinancialClient(full_name="Outro Cliente Debts")
    db.add(other_fc)
    db.commit()
    other_ws = fp_svc.enable_access(other_fc, actor=staff_user)
    other_account = accounts_svc.create_account(
        other_ws, actor=staff_user, account_name="Other Checking", account_type=AccountType.checking)

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    with pytest.raises(debts_service.DebtValidationError):
        debts_service.record_payment(
            debt, amount_cents=1000, payment_date=date(2026, 8, 1), paid_from_account_id=other_account.id)


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------

def test_debt_progress_none_without_original_balance(db, workspace):
    from app.services import debts_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    progress = debts_service.debt_progress(debt)
    assert progress["paid_amount_cents"] is None
    assert progress["progress"] is None


def test_debt_progress_computes_paid_amount_and_ratio(db, workspace):
    from app.services import debts_service

    debt = debts_service.create_debt(
        workspace, actor=None, debt_name="Visa", current_balance_cents=75000, original_balance_cents=100000)
    progress = debts_service.debt_progress(debt)
    assert progress["paid_amount_cents"] == 25000
    assert progress["progress"] == 0.25


# --------------------------------------------------------------------------
# Payoff projection
# --------------------------------------------------------------------------

def test_payoff_projection_none_without_payment(db, workspace):
    from app.services import debts_service

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    assert debts_service.payoff_projection(debt) is None


def test_payoff_projection_none_when_payment_doesnt_cover_interest(db, workspace):
    from app.services import debts_service

    # $10,000 a 24% ao ano -> ~$200/mês só de juros; pagando $50/mês nunca quita
    debt = debts_service.create_debt(
        workspace, actor=None, debt_name="Visa", current_balance_cents=1000000, apr_bps=2400,
        minimum_payment_cents=5000)
    assert debts_service.payoff_projection(debt) is None


def test_payoff_projection_zero_months_when_already_paid(db, workspace):
    from app.services import debts_service

    debt = debts_service.create_debt(
        workspace, actor=None, debt_name="Visa", current_balance_cents=0, minimum_payment_cents=10000)
    proj = debts_service.payoff_projection(debt, today=date(2026, 8, 1))
    assert proj == {"months_to_payoff": 0, "total_interest_cents": 0, "payoff_date": date(2026, 8, 1)}


def test_payoff_projection_zero_apr_is_simple_division(db, workspace):
    """Sem juros, $1000 pagando $100/mês quita em exatamente 10 meses,
    sem nenhum centavo de juros -- confirma a matemática básica antes de
    testar o caso com APR."""
    from app.services import debts_service

    debt = debts_service.create_debt(
        workspace, actor=None, debt_name="0% APR loan", current_balance_cents=100000,
        minimum_payment_cents=10000)
    proj = debts_service.payoff_projection(debt, today=date(2026, 1, 1))
    assert proj["months_to_payoff"] == 10
    assert proj["total_interest_cents"] == 0
    assert proj["payoff_date"] == date(2026, 11, 1)


def test_payoff_projection_with_apr_accrues_interest(db, workspace):
    """$1,200 a 12% ao ano (1% ao mês) pagando $110/mês -- confere que
    o total pago > saldo original (juros de verdade sendo cobrados) e
    que o número de meses é maior do que a divisão simples (1200/110 ~
    11 meses sem juros; com juros deve levar mais tempo)."""
    from app.services import debts_service

    debt = debts_service.create_debt(
        workspace, actor=None, debt_name="Personal loan", current_balance_cents=120000, apr_bps=1200,
        minimum_payment_cents=11000)
    proj = debts_service.payoff_projection(debt, today=date(2026, 1, 1))
    assert proj is not None
    assert proj["total_interest_cents"] > 0
    assert proj["months_to_payoff"] > 11  # mais devagar que sem juros


# --------------------------------------------------------------------------
# Ordering (snowball/avalanche/custom)
# --------------------------------------------------------------------------

def test_ordered_debts_snowball_by_balance_ascending(db, workspace):
    from app.financial_planning_models import PayoffStrategy
    from app.services import debts_service

    debts_service.create_debt(workspace, actor=None, debt_name="Big", current_balance_cents=500000)
    debts_service.create_debt(workspace, actor=None, debt_name="Small", current_balance_cents=10000)
    debts_service.create_debt(workspace, actor=None, debt_name="Medium", current_balance_cents=100000)

    ordered = debts_service.ordered_debts(workspace, strategy=PayoffStrategy.snowball)
    assert [d.debt_name for d in ordered] == ["Small", "Medium", "Big"]


def test_ordered_debts_avalanche_by_apr_descending(db, workspace):
    from app.financial_planning_models import PayoffStrategy
    from app.services import debts_service

    debts_service.create_debt(workspace, actor=None, debt_name="Low APR", current_balance_cents=100000, apr_bps=500)
    debts_service.create_debt(workspace, actor=None, debt_name="High APR", current_balance_cents=100000, apr_bps=2500)
    debts_service.create_debt(workspace, actor=None, debt_name="Mid APR", current_balance_cents=100000, apr_bps=1500)

    ordered = debts_service.ordered_debts(workspace, strategy=PayoffStrategy.avalanche)
    assert [d.debt_name for d in ordered] == ["High APR", "Mid APR", "Low APR"]


def test_ordered_debts_custom_by_priority(db, workspace):
    from app.financial_planning_models import PayoffStrategy
    from app.services import debts_service

    debts_service.create_debt(workspace, actor=None, debt_name="Third", current_balance_cents=100000, custom_priority=3)
    debts_service.create_debt(workspace, actor=None, debt_name="First", current_balance_cents=100000, custom_priority=1)
    debts_service.create_debt(workspace, actor=None, debt_name="Second", current_balance_cents=100000, custom_priority=2)

    ordered = debts_service.ordered_debts(workspace, strategy=PayoffStrategy.custom)
    assert [d.debt_name for d in ordered] == ["First", "Second", "Third"]


def test_ordered_debts_excludes_paid_off(db, workspace):
    from app.financial_planning_models import PayoffStrategy
    from app.services import debts_service

    active = debts_service.create_debt(workspace, actor=None, debt_name="Active", current_balance_cents=100000)
    paid = debts_service.create_debt(workspace, actor=None, debt_name="Paid", current_balance_cents=50000)
    debts_service.record_payment(paid, amount_cents=50000, payment_date=date(2026, 8, 1))

    ordered = debts_service.ordered_debts(workspace, strategy=PayoffStrategy.snowball)
    assert [d.debt_name for d in ordered] == ["Active"]


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="debtsclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Debts HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_debts_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/dividas")
    assert resp.status_code == 200
    assert b"Debts" in resp.data


def test_debt_plan_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/dividas/plano")
    assert resp.status_code == 200
    assert b"Debt Payoff Plan" in resp.data


def test_add_debt_via_route(financial_client_login, db):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/dividas/nova",
        data={"debt_name": "Chase Visa", "current_balance": "2500.00", "apr": "19.99"},
        follow_redirects=True)
    assert resp.status_code == 200
    assert b"Chase Visa" in resp.data

    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import Debt
    fc = db.query(FinancialClient).filter_by(full_name="Cliente Debts HTTP").first()
    debt = db.query(Debt).filter_by(financial_workspace_id=fc.workspace.id, debt_name="Chase Visa").first()
    assert debt is not None
    assert debt.apr_bps == 1999


def test_pay_debt_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.services import debts_service

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Debts HTTP").first()
    debt = debts_service.create_debt(fc.workspace, actor=None, debt_name="Store Card", current_balance_cents=30000)
    debt_id = debt.id

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/dividas/{debt_id}/pagamento",
        data={"amount": "100.00"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Payment recorded" in resp.data

    from app.financial_planning_models import Debt
    refreshed = db.get(Debt, debt_id)
    assert refreshed.current_balance_cents == 20000
