"""Fase 11 (Reports) do SAES_Financial_Planning_Master_Spec, 2026-08-07 --
Monthly Financial Summary, comparação com o período anterior, exportação
CSV/PDF.
"""
from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Reports Teste")
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
# Períodos
# --------------------------------------------------------------------------

def test_period_range_this_month():
    from app.services import financial_reports_service as reports_svc

    start, end = reports_svc.period_range("this_month", today=date(2026, 8, 15))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 15)


def test_period_range_last_month():
    from app.services import financial_reports_service as reports_svc

    start, end = reports_svc.period_range("last_month", today=date(2026, 8, 15))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_period_range_ytd():
    from app.services import financial_reports_service as reports_svc

    start, end = reports_svc.period_range("ytd", today=date(2026, 8, 15))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 8, 15)


def test_period_range_last_3_months():
    from app.services import financial_reports_service as reports_svc

    start, end = reports_svc.period_range("last_3_months", today=date(2026, 8, 15))
    assert start == date(2026, 6, 1)
    assert end == date(2026, 8, 15)


def test_previous_period_range_same_length():
    from app.services import financial_reports_service as reports_svc

    prev_start, prev_end = reports_svc.previous_period_range(date(2026, 8, 1), date(2026, 8, 10))
    assert prev_start == date(2026, 7, 22)
    assert prev_end == date(2026, 7, 31)
    assert (prev_end - prev_start).days == (date(2026, 8, 10) - date(2026, 8, 1)).days


# --------------------------------------------------------------------------
# Monthly Financial Summary
# --------------------------------------------------------------------------

def test_monthly_summary_income_expenses_savings(db, workspace, account):
    from app.financial_planning_models import TransactionType
    from app.services import financial_reports_service as reports_svc
    from app.services import financial_transactions_service as tx_svc

    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.income, name="Paycheck",
        amount_cents=500000, transaction_date=date(2026, 8, 5), account_id=account.id)
    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.expense, name="Rent",
        amount_cents=180000, transaction_date=date(2026, 8, 6), account_id=account.id)

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert summary["income_cents"] == 500000
    assert summary["expenses_cents"] == 180000
    assert summary["savings_cents"] == 320000
    assert summary["savings_rate"] == pytest.approx(320000 / 500000)


def test_monthly_summary_savings_rate_none_without_income(db, workspace, account):
    from app.services import financial_reports_service as reports_svc

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert summary["savings_rate"] is None


def test_monthly_summary_debt_reduction(db, workspace):
    from app.services import debts_service, financial_reports_service as reports_svc

    debt = debts_service.create_debt(workspace, actor=None, debt_name="Visa", current_balance_cents=100000)
    debts_service.record_payment(debt, amount_cents=20000, payment_date=date(2026, 8, 10))
    debts_service.record_payment(debt, amount_cents=10000, payment_date=date(2026, 9, 1))  # fora do período

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert summary["debt_reduction_cents"] == 20000


def test_monthly_summary_goal_contributions(db, workspace, account):
    from app.services import goals_service, financial_reports_service as reports_svc

    goal = goals_service.create_goal(workspace, actor=None, name="Trip", target_amount_cents=500000)
    goals_service.add_contribution(goal, amount_cents=30000, contribution_date=date(2026, 8, 12))
    goals_service.add_contribution(goal, amount_cents=15000, contribution_date=date(2026, 9, 1))  # fora do período

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert summary["goal_contributions_cents"] == 30000


def test_monthly_summary_net_worth_change_none_without_snapshots(db, workspace, account):
    from app.services import financial_reports_service as reports_svc

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert summary["net_worth_change_cents"] is None


def test_monthly_summary_net_worth_change_computed_from_snapshots(db, workspace, account):
    from app.services import net_worth_service, financial_reports_service as reports_svc

    net_worth_service.record_snapshot(account, balance_cents=100000, snapshot_date=date(2026, 7, 31))
    net_worth_service.record_snapshot(account, balance_cents=150000, snapshot_date=date(2026, 8, 31))

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert summary["net_worth_change_cents"] == 50000


def test_monthly_summary_budget_performance_none_for_multi_month_period(db, workspace):
    from app.services import financial_reports_service as reports_svc

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 6, 1), end=date(2026, 8, 31))
    assert summary["budget_performance"] is None


def test_monthly_summary_budget_performance_populated_for_calendar_month_with_period(db, workspace, account):
    from app.financial_planning_models import BudgetCategory, BudgetCategoryGroup, TransactionType
    from app.services import budget_service, financial_reports_service as reports_svc
    from app.services import financial_transactions_service as tx_svc

    cat = BudgetCategory(financial_workspace_id=workspace.id, name="Housing", category_group=BudgetCategoryGroup.needs)
    db.add(cat)
    db.commit()

    period = budget_service.get_or_create_current_period(workspace, today=date(2026, 8, 15))
    budget_service.set_allocation(period, cat, planned_amount_cents=150000)
    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.expense, name="Rent",
        amount_cents=180000, transaction_date=date(2026, 8, 6), account_id=account.id, budget_category_id=cat.id)

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert summary["budget_performance"] is not None
    assert summary["budget_performance"][0]["planned_cents"] == 150000
    assert summary["budget_performance"][0]["actual_cents"] == 180000

    # Período PARCIAL do mesmo mês (ex.: "This Month" visto no dia 15,
    # que sempre termina hoje, nunca no fim do mês) também precisa
    # mostrar Budget Performance -- achado ao vivo no Chrome: a primeira
    # versão só mostrava pra período cobrindo o mês inteiro.
    partial = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 15))
    assert partial["budget_performance"] is not None
    assert partial["budget_performance"][0]["actual_cents"] == 180000


def test_monthly_summary_with_comparison_includes_previous(db, workspace, account):
    from app.financial_planning_models import TransactionType
    from app.services import financial_reports_service as reports_svc
    from app.services import financial_transactions_service as tx_svc

    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.income, name="Paycheck",
        amount_cents=500000, transaction_date=date(2026, 8, 5), account_id=account.id)

    summary = reports_svc.monthly_summary_with_comparison(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert "previous" in summary
    assert summary["previous"]["income_cents"] == 0


# --------------------------------------------------------------------------
# Exportação
# --------------------------------------------------------------------------

def test_to_csv_bytes_contains_key_figures(db, workspace, account):
    from app.financial_planning_models import TransactionType
    from app.services import financial_reports_service as reports_svc
    from app.services import financial_transactions_service as tx_svc

    tx_svc.create_transaction(
        workspace, actor=None, transaction_type=TransactionType.income, name="Paycheck",
        amount_cents=500000, transaction_date=date(2026, 8, 5), account_id=account.id)

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    csv_bytes = reports_svc.to_csv_bytes(summary)
    text = csv_bytes.decode("utf-8")
    assert "$5,000" in text
    assert "Monthly Financial Summary" in text


def test_render_pdf_bytes_produces_a_real_pdf(db, workspace, account):
    from app.services import financial_reports_service as reports_svc

    summary = reports_svc.monthly_summary(workspace, start=date(2026, 8, 1), end=date(2026, 8, 31))
    pdf_bytes = reports_svc.render_pdf_bytes(summary)
    assert pdf_bytes.startswith(b"%PDF-")


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="reportsclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Reports HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_reports_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/relatorios")
    assert resp.status_code == 200
    assert b"Monthly Financial Summary" in resp.data or b"Reports" in resp.data


def test_reports_csv_export_route(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/relatorios/exportar.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"


def test_reports_pdf_export_route(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/relatorios/exportar.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF-")


def test_reports_custom_period_via_route(financial_client_login):
    resp = financial_client_login.get(
        "/meu-plano-financeiro/workspace/relatorios",
        query_string={"period": "custom", "start": "2026-01-01", "end": "2026-01-15"})
    assert resp.status_code == 200


def test_reports_invalid_custom_period_falls_back_to_this_month(financial_client_login):
    resp = financial_client_login.get(
        "/meu-plano-financeiro/workspace/relatorios",
        query_string={"period": "custom", "start": "", "end": ""})
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# Saved views (Fase 12 -- item que ficou esquecido na primeira passada,
# ver docstring de SavedReportView em app/financial_planning_models.py)
# --------------------------------------------------------------------------

def test_create_saved_view_persists_period(db, workspace, staff_user):
    from app.services import financial_reports_service as reports_svc

    view = reports_svc.create_saved_view(workspace, actor=staff_user, name="Q1 review", period="last_3_months")
    assert view.id is not None
    assert view.name == "Q1 review"
    assert view.period == "last_3_months"
    assert view.custom_start is None and view.custom_end is None


def test_create_saved_view_custom_period_stores_dates(db, workspace, staff_user):
    from app.services import financial_reports_service as reports_svc

    view = reports_svc.create_saved_view(
        workspace, actor=staff_user, name="Custom range", period="custom",
        custom_start=date(2026, 1, 1), custom_end=date(2026, 3, 15))
    assert view.custom_start == date(2026, 1, 1)
    assert view.custom_end == date(2026, 3, 15)


def test_create_saved_view_drops_dates_for_non_custom_period(db, workspace, staff_user):
    """Se o form mandar start/end junto com um período fixo (não deveria
    acontecer pela UI, mas a rota não confia nisso), o service ignora --
    só "custom" pode ter datas próprias."""
    from app.services import financial_reports_service as reports_svc

    view = reports_svc.create_saved_view(
        workspace, actor=staff_user, name="Should ignore dates", period="this_month",
        custom_start=date(2026, 1, 1), custom_end=date(2026, 3, 15))
    assert view.custom_start is None and view.custom_end is None


def test_list_saved_views_scoped_to_workspace_most_recent_first(db, workspace, staff_user):
    from app.services import financial_reports_service as reports_svc

    reports_svc.create_saved_view(workspace, actor=staff_user, name="First", period="this_month")
    second = reports_svc.create_saved_view(workspace, actor=staff_user, name="Second", period="last_month")

    views = reports_svc.list_saved_views(workspace)
    assert [v.name for v in views] == ["Second", "First"]
    assert second.created_by_id == staff_user.id


def test_delete_saved_view_removes_it(db, workspace, staff_user):
    from app.services import financial_reports_service as reports_svc

    view = reports_svc.create_saved_view(workspace, actor=staff_user, name="Temp", period="this_month")
    reports_svc.delete_saved_view(view)
    assert reports_svc.list_saved_views(workspace) == []


def test_saved_view_new_route_creates_and_redirects_with_period(financial_client_login):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/relatorios/visualizacoes",
        data={"name": "Q1 review", "period": "last_3_months", "start": "", "end": ""})
    assert resp.status_code == 302
    assert "period=last_3_months" in resp.headers["Location"]

    page = financial_client_login.get("/meu-plano-financeiro/workspace/relatorios")
    assert b"Q1 review" in page.data


def test_saved_view_new_route_requires_name(financial_client_login):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/relatorios/visualizacoes",
        data={"name": "", "period": "this_month", "start": "", "end": ""}, follow_redirects=True)
    assert b"No saved views yet" in resp.data


def test_saved_view_open_route_redirects_with_custom_dates(financial_client_login):
    financial_client_login.post(
        "/meu-plano-financeiro/workspace/relatorios/visualizacoes",
        data={"name": "Custom range", "period": "custom", "start": "2026-01-01", "end": "2026-03-15"})

    from app.db import SessionLocal
    from app.financial_planning_models import SavedReportView
    view_id = SessionLocal.query(SavedReportView).first().id

    resp = financial_client_login.get(f"/meu-plano-financeiro/workspace/relatorios/visualizacoes/{view_id}/abrir")
    assert resp.status_code == 302
    assert "period=custom" in resp.headers["Location"]
    assert "start=2026-01-01" in resp.headers["Location"]
    assert "end=2026-03-15" in resp.headers["Location"]


def test_saved_view_delete_route_removes_it(financial_client_login):
    financial_client_login.post(
        "/meu-plano-financeiro/workspace/relatorios/visualizacoes",
        data={"name": "Temp", "period": "this_month", "start": "", "end": ""})

    from app.db import SessionLocal
    from app.financial_planning_models import SavedReportView
    view_id = SessionLocal.query(SavedReportView).first().id

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/relatorios/visualizacoes/{view_id}/excluir")
    assert resp.status_code == 302

    page = financial_client_login.get("/meu-plano-financeiro/workspace/relatorios")
    assert b"No saved views yet" in page.data


def test_saved_view_delete_route_rejects_other_workspace(financial_client_login, db, staff_user):
    """Isolamento de tenant: uma saved view de OUTRO workspace não pode
    ser aberta/excluída pelo cliente logado, mesmo sabendo o id."""
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc
    from app.services import financial_reports_service as reports_svc

    staff_user = db.query(User).filter_by(email="staff@example.com").first()
    other_fc = FinancialClient(full_name="Outro Cliente")
    db.add(other_fc)
    db.commit()
    other_workspace = fp_svc.enable_access(other_fc, actor=staff_user)
    other_view = reports_svc.create_saved_view(other_workspace, actor=staff_user, name="Not yours", period="this_month")

    resp = financial_client_login.get(f"/meu-plano-financeiro/workspace/relatorios/visualizacoes/{other_view.id}/abrir")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/relatorios")  # sem period=... -- caiu no "not found"
