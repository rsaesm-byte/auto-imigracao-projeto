"""Fase 6 (Recurring) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
`RecurringTransaction` (gera FinancialTransaction de verdade, cadência
respeitada por mês/semana, backfill de ocorrências perdidas) e
`RecurringDebit` (registro de assinatura + "subscription analysis",
nunca gera transação sozinho).
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Recurring Teste")
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
# RecurringTransaction
# --------------------------------------------------------------------------

def test_create_recurring_transaction_requires_name(db, workspace):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    with pytest.raises(recurring_service.RecurringValidationError):
        recurring_service.create_recurring_transaction(
            workspace, actor=None, transaction_kind=RecurringTransactionKind.income, name="",
            amount_cents=100000, frequency=BillFrequency.monthly, start_date=date(2026, 8, 1))


def test_create_recurring_transaction_rejects_non_positive_amount(db, workspace):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    with pytest.raises(recurring_service.RecurringValidationError):
        recurring_service.create_recurring_transaction(
            workspace, actor=None, transaction_kind=RecurringTransactionKind.income, name="Paycheck",
            amount_cents=0, frequency=BillFrequency.monthly, start_date=date(2026, 8, 1))


def test_create_recurring_transaction_initializes_next_occurrence(db, workspace, account):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    r = recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.income, name="Paycheck",
        amount_cents=500000, frequency=BillFrequency.monthly, start_date=date(2026, 8, 15), account_id=account.id)
    assert r.next_occurrence == date(2026, 8, 15)


def test_generate_due_transactions_creates_and_advances_monthly(db, workspace, account):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    r = recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.income, name="Paycheck",
        amount_cents=500000, frequency=BillFrequency.monthly, start_date=date(2026, 8, 15), account_id=account.id)

    created = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 20))
    assert len(created) == 1
    assert created[0].amount_cents == 500000
    assert created[0].transaction_date == date(2026, 8, 15)
    assert r.next_occurrence == date(2026, 9, 15)


def test_generate_due_transactions_is_idempotent_same_day(db, workspace, account):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.expense, name="Subscription",
        amount_cents=1500, frequency=BillFrequency.monthly, start_date=date(2026, 8, 1), account_id=account.id)

    first = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 5))
    second = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 5))
    assert len(first) == 1
    assert len(second) == 0


def test_generate_due_transactions_backfills_missed_occurrences(db, workspace, account):
    """Se o cliente não abre o app por 3 meses, as 3 ocorrências perdidas
    são geradas de uma vez (nunca silenciosamente perdidas)."""
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.expense, name="Gym",
        amount_cents=5000, frequency=BillFrequency.monthly, start_date=date(2026, 6, 1), account_id=account.id)

    created = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 15))
    assert len(created) == 3
    assert sorted(t.transaction_date for t in created) == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]


def test_weekly_frequency_advances_by_seven_days(db, workspace, account):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    r = recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.expense, name="Lunch club",
        amount_cents=2000, frequency=BillFrequency.weekly, start_date=date(2026, 8, 3), account_id=account.id)
    recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 3))
    assert r.next_occurrence == date(2026, 8, 10)


def test_custom_frequency_never_generates_or_advances(db, workspace, account):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    r = recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.expense, name="One-off-ish",
        amount_cents=2000, frequency=BillFrequency.custom, start_date=date(2026, 8, 1), account_id=account.id)
    created = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 15))
    assert created == []
    assert r.next_occurrence is None


def test_end_date_stops_generation(db, workspace, account):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    r = recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.expense, name="Short course",
        amount_cents=2000, frequency=BillFrequency.monthly, start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 15), account_id=account.id)

    created = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 15))
    assert len(created) == 2  # jun 1, jul 1 -- aug 1 já passa do end_date
    assert r.next_occurrence is None


def test_savings_contribution_generates_expense_with_savings_classification(db, workspace, account):
    from app.financial_planning_models import (BillFrequency, RecurringTransactionKind,
                                                 TransactionClassification, TransactionType)
    from app.services import recurring_service

    recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.savings_contribution, name="Auto-save",
        amount_cents=10000, frequency=BillFrequency.monthly, start_date=date(2026, 8, 1), account_id=account.id)

    created = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 1))
    assert created[0].transaction_type == TransactionType.expense
    assert created[0].classification == TransactionClassification.savings


def test_recurring_transaction_without_account_does_not_generate(db, workspace):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import recurring_service

    r = recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.income, name="Freelance",
        amount_cents=50000, frequency=BillFrequency.monthly, start_date=date(2026, 8, 1))
    created = recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 15))
    assert created == []
    assert r.next_occurrence == date(2026, 8, 1)  # não avança sem conta pra lançar


def test_soft_delete_recurring_transaction_keeps_posted_transactions(db, workspace, account):
    from app.financial_planning_models import BillFrequency, RecurringTransactionKind
    from app.services import financial_transactions_service as tx_svc
    from app.services import recurring_service

    r = recurring_service.create_recurring_transaction(
        workspace, actor=None, transaction_kind=RecurringTransactionKind.expense, name="Old plan",
        amount_cents=1000, frequency=BillFrequency.monthly, start_date=date(2026, 8, 1), account_id=account.id)
    recurring_service.generate_due_transactions(workspace, today=date(2026, 8, 1))
    posted_count_before = len(tx_svc.list_transactions(workspace))

    recurring_service.soft_delete_recurring_transaction(r)

    assert r.deleted_at is not None
    assert len(tx_svc.list_transactions(workspace)) == posted_count_before


# --------------------------------------------------------------------------
# RecurringDebit / subscription analysis
# --------------------------------------------------------------------------

def test_create_recurring_debit_requires_merchant(db, workspace):
    from app.services import recurring_service

    with pytest.raises(recurring_service.RecurringValidationError):
        recurring_service.create_recurring_debit(workspace, actor=None, merchant="", amount_cents=1500)


def test_monthly_equivalent_conversion(db, workspace):
    from app.financial_planning_models import BillFrequency
    from app.services import recurring_service

    recurring_service.create_recurring_debit(
        workspace, actor=None, merchant="Weekly coffee club", amount_cents=1000, frequency=BillFrequency.weekly)
    recurring_service.create_recurring_debit(
        workspace, actor=None, merchant="Amazon Prime", amount_cents=13900, frequency=BillFrequency.annual)

    summary = recurring_service.subscription_summary(workspace)
    # 1000 * 52/12 ~= 4333 ; 13900 / 12 ~= 1158
    assert summary["total_active_monthly_cents"] == round(1000 * 52 / 12) + round(13900 / 12)


def test_custom_frequency_excluded_from_monthly_total(db, workspace):
    from app.financial_planning_models import BillFrequency
    from app.services import recurring_service

    recurring_service.create_recurring_debit(
        workspace, actor=None, merchant="Irregular thing", amount_cents=5000, frequency=BillFrequency.custom)
    summary = recurring_service.subscription_summary(workspace)
    assert summary["total_active_monthly_cents"] == 0
    assert summary["excluded_custom_count"] == 1


def test_set_review_status_cancel_records_intent_without_deactivating(db, workspace):
    """Marcar `cancel` é só a intenção do cliente -- continua `active`
    (ainda sendo cobrado de verdade) até ser removido de fato via
    `soft_delete_recurring_debit`; senão `potential_monthly_savings_cents`
    não teria mais nada pra somar assim que algo fosse marcado."""
    from app.financial_planning_models import ReviewStatus
    from app.services import recurring_service

    debit = recurring_service.create_recurring_debit(workspace, actor=None, merchant="Unused app", amount_cents=999)
    recurring_service.set_review_status(debit, ReviewStatus.cancel)

    assert debit.review_status == ReviewStatus.cancel
    assert debit.active is True
    assert debit.cancelled_at is not None


def test_subscription_summary_potential_savings_matches_cancelled_bucket(db, workspace):
    from app.financial_planning_models import ReviewStatus
    from app.services import recurring_service

    keep = recurring_service.create_recurring_debit(workspace, actor=None, merchant="Netflix", amount_cents=1599)
    cancel_me = recurring_service.create_recurring_debit(workspace, actor=None, merchant="Unused gym", amount_cents=4000)
    recurring_service.set_review_status(cancel_me, ReviewStatus.cancel)

    summary = recurring_service.subscription_summary(workspace)
    assert summary["potential_monthly_savings_cents"] == 4000
    assert summary["by_status"]["keep"]["monthly_cents"] == 1599


def test_soft_delete_recurring_debit(db, workspace):
    from app.services import recurring_service

    debit = recurring_service.create_recurring_debit(workspace, actor=None, merchant="Trial thing", amount_cents=500)
    recurring_service.soft_delete_recurring_debit(debit)
    assert debit.deleted_at is not None
    assert debit.active is False


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="recurringclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Recurring HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_recurring_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/recorrentes")
    assert resp.status_code == 200
    assert b"Recurring Transactions" in resp.data


def test_subscriptions_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/assinaturas")
    assert resp.status_code == 200
    assert b"Subscriptions" in resp.data


def test_add_recurring_transaction_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_accounts_service as accounts_svc

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Recurring HTTP").first()
    from app.financial_planning_models import AccountType
    account = accounts_svc.create_account(
        fc.workspace, actor=None, account_name="Checking", account_type=AccountType.checking)

    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/recorrentes/nova",
        data={"transaction_kind": "income", "name": "Paycheck", "amount": "5000.00",
              "frequency": "monthly", "account_id": str(account.id), "start_date": "2026-08-01"},
        follow_redirects=True)
    assert resp.status_code == 200
    assert b"Paycheck" in resp.data


def test_add_subscription_and_update_status_via_route(financial_client_login, db):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/assinaturas/nova",
        data={"merchant": "Spotify", "amount": "10.99", "frequency": "monthly"},
        follow_redirects=True)
    assert resp.status_code == 200
    assert b"Spotify" in resp.data

    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import RecurringDebit
    fc = db.query(FinancialClient).filter_by(full_name="Cliente Recurring HTTP").first()
    debit = db.query(RecurringDebit).filter_by(financial_workspace_id=fc.workspace.id, merchant="Spotify").first()
    debit_id = debit.id

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/assinaturas/{debit_id}/status",
        data={"review_status": "cancel"}, follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db.get(RecurringDebit, debit_id)
    assert refreshed.review_status.value == "cancel"
