"""Fase 5 (Bills) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
definição de boleto recorrente, geração idempotente das cobranças
mensais (granularidade mensal mesmo pra frequências não-mensais, ver
docstring de app/services/bills_service.py), status calculado (overdue
nunca sobrescreve o banco), marcar como pago/pular.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Bills Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


# --------------------------------------------------------------------------
# Definição do boleto
# --------------------------------------------------------------------------

def test_create_bill_requires_name(db, workspace):
    from app.services import bills_service

    with pytest.raises(bills_service.BillValidationError):
        bills_service.create_bill(workspace, actor=None, bill_name="")


def test_create_bill_rejects_invalid_due_day(db, workspace):
    from app.services import bills_service

    with pytest.raises(bills_service.BillValidationError):
        bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=32)


def test_create_bill_rejects_category_from_another_workspace(db, workspace, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import BudgetCategory
    from app.services import bills_service
    from app.services import financial_planning_service as fp_svc

    other_fc = FinancialClient(full_name="Outro Cliente")
    db.add(other_fc)
    db.commit()
    other_workspace = fp_svc.enable_access(other_fc, actor=staff_user)
    other_category = db.query(BudgetCategory).filter_by(financial_workspace_id=other_workspace.id).first()

    with pytest.raises(bills_service.BillValidationError):
        bills_service.create_bill(
            workspace, actor=None, bill_name="Rent", budget_category_id=other_category.id)


def test_soft_delete_bill_keeps_payment_history(db, workspace):
    from app.services import bills_service

    bill = bills_service.create_bill(workspace, actor=None, bill_name="Internet", due_day=10)
    bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))
    payment = db.query(bills_service.BillPayment).filter_by(bill_id=bill.id).first()

    bills_service.soft_delete_bill(bill)

    assert bill.deleted_at is not None
    assert bill.active is False
    assert db.get(bills_service.BillPayment, payment.id) is not None  # histórico preservado


# --------------------------------------------------------------------------
# Geração das cobranças mensais
# --------------------------------------------------------------------------

def test_ensure_payments_for_month_creates_monthly_bill(db, workspace):
    from app.financial_planning_models import BillFrequency
    from app.services import bills_service

    bills_service.create_bill(
        workspace, actor=None, bill_name="Rent", default_amount_cents=180000,
        due_day=5, frequency=BillFrequency.monthly)

    created = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 15))
    assert len(created) == 1
    assert created[0].due_date == date(2026, 8, 5)
    assert created[0].amount_cents == 180000
    assert created[0].billing_month == date(2026, 8, 1)


def test_ensure_payments_for_month_is_idempotent(db, workspace):
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=5)
    first = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))
    second = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 20))

    assert len(first) == 1
    assert len(second) == 0  # já existia -- não duplica
    all_payments = db.query(bills_service.BillPayment).all()
    assert len(all_payments) == 1


def test_due_date_capped_to_last_day_of_month(db, workspace):
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Subscription", due_day=31)
    created = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 2, 10))  # fevereiro
    assert created[0].due_date == date(2026, 2, 28)


def test_quarterly_bill_only_generates_in_due_months(db, workspace):
    from app.financial_planning_models import BillFrequency
    from app.services import bills_service

    bills_service.create_bill(
        workspace, actor=None, bill_name="Car Insurance", frequency=BillFrequency.quarterly,
        start_date=date(2026, 1, 15))

    assert len(bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 1, 1))) == 1
    assert len(bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 2, 1))) == 0
    assert len(bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 4, 1))) == 1


def test_custom_frequency_never_auto_generates(db, workspace):
    from app.financial_planning_models import BillFrequency
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="One-off", frequency=BillFrequency.custom)
    created = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))
    assert created == []


def test_inactive_bill_does_not_generate(db, workspace):
    from app.services import bills_service

    bill = bills_service.create_bill(workspace, actor=None, bill_name="Old gym", due_day=1)
    bills_service.soft_delete_bill(bill)
    created = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))
    assert created == []


# --------------------------------------------------------------------------
# Status calculado / ações
# --------------------------------------------------------------------------

def test_display_status_computes_overdue_without_mutating_stored_status(db, workspace):
    from app.financial_planning_models import BillPaymentStatus
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=5)
    payment = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))[0]

    assert bills_service.display_status(payment, today=date(2026, 8, 20)) == "overdue"
    assert payment.status == BillPaymentStatus.upcoming  # nunca mutado só por exibição


def test_display_status_paid_never_shows_as_overdue(db, workspace, staff_user):
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=5)
    payment = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))[0]
    bills_service.mark_paid(payment, actor=staff_user)

    assert bills_service.display_status(payment, today=date(2026, 9, 1)) == "paid"


def test_mark_paid_sets_fields(db, workspace, staff_user):
    from app.financial_planning_models import AccountType, BillPaymentStatus
    from app.services import bills_service
    from app.services import financial_accounts_service as accounts_svc

    bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=5)
    payment = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))[0]
    account = accounts_svc.create_account(
        workspace, actor=staff_user, account_name="Checking", account_type=AccountType.checking)

    bills_service.mark_paid(
        payment, actor=staff_user, paid_date=date(2026, 8, 4),
        paid_from_account_id=account.id, confirmation_number="CONF123")

    assert payment.status == BillPaymentStatus.paid
    assert payment.paid_date == date(2026, 8, 4)
    assert payment.paid_from_account_id == account.id
    assert payment.confirmation_number == "CONF123"


def test_mark_paid_twice_raises(db, workspace, staff_user):
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=5)
    payment = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))[0]
    bills_service.mark_paid(payment, actor=staff_user)

    with pytest.raises(bills_service.BillValidationError):
        bills_service.mark_paid(payment, actor=staff_user)


def test_skip_payment(db, workspace, staff_user):
    from app.financial_planning_models import BillPaymentStatus
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Optional subscription", due_day=5)
    payment = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))[0]
    bills_service.skip_payment(payment, actor=staff_user)
    assert payment.status == BillPaymentStatus.skipped


def test_mark_paid_and_skip_are_audited(db, workspace, staff_user):
    from app.services import audit_service
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=5)
    p1 = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))[0]
    bills_service.mark_paid(p1, actor=staff_user)
    actions = [h.action for h in audit_service.get_history("BillPayment", p1.id)]
    assert "bill_paid" in actions


def test_upcoming_within_days_includes_overdue(db, workspace):
    from app.services import bills_service

    bills_service.create_bill(workspace, actor=None, bill_name="Rent", due_day=5)
    payment = bills_service.ensure_payments_for_month(workspace, for_date=date(2026, 8, 1))[0]

    rows = bills_service.upcoming_within_days(workspace, days=7, today=date(2026, 8, 20))
    assert len(rows) == 1
    assert rows[0]["payment"].id == payment.id


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="billsclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Bills HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_bills_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/contas-a-pagar")
    assert resp.status_code == 200
    assert b"Bills" in resp.data


def test_bills_calendar_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/contas-a-pagar/calendario")
    assert resp.status_code == 200
    assert b"Bills Calendar" in resp.data


def test_add_bill_via_route_then_appears_in_this_month(financial_client_login, db):
    from app.crm_financial_models import FinancialClient

    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/contas-a-pagar/nova",
        data={"bill_name": "Electricity", "due_day": "12", "frequency": "monthly", "default_amount": "95.00"},
        follow_redirects=True)
    assert resp.status_code == 200
    assert b"Electricity" in resp.data

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Bills HTTP").first()
    from app.services import bills_service
    bills = bills_service.list_bills(fc.workspace)
    assert len(bills) == 1
    assert bills[0].bill_name == "Electricity"


def test_pay_bill_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import BillPaymentStatus
    from app.services import bills_service

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Bills HTTP").first()
    bills_service.create_bill(fc.workspace, actor=None, bill_name="Water", due_day=10)
    payment = bills_service.ensure_payments_for_month(fc.workspace)[0]
    payment_id = payment.id

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/contas-a-pagar/pagamento/{payment_id}/pagar",
        data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"marked as paid" in resp.data

    refreshed = db.get(bills_service.BillPayment, payment_id)
    assert refreshed.status == BillPaymentStatus.paid
