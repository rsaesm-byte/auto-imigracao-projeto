"""Fase 2 do SAES_Financial_Planning_Master_Spec -- portal self-service
do CLIENTE pro módulo "Financial Planning": contas e transações (renda/
despesa/transferência). Sibling de app/crm_financial_client.py (aquele é
só leitura do funil de coaching; este é o workspace de verdade que o
CLIENTE alimenta com o próprio dado -- contas/orçamento/dívidas/metas
das fases seguintes vão morar aqui também).

Toda rota exige (1) login, (2) FinancialClient vinculado ao usuário
logado, (3) `financial_planning_enabled=True` -- staff pode desabilitar
sem apagar nada (Fase 1, app/services/financial_planning_service.py), e
o cliente perde acesso na hora, sem 500/404 cru: cai numa mensagem
amigável (mesmo padrão de app/crm_financial_client.py::meu_plano quando
`fc is None`).
"""
from __future__ import annotations

import io
from datetime import date

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.crm_financial_models import FinancialClient
from app.db import SessionLocal
from app.financial_planning_models import (Account, AccountType, Bill, BillFrequency, BillPayment,
                                            BudgetCategory, BudgetCategoryGroup, BudgetPeriod,
                                            BudgetRuleType, CsvImportBatch, CsvImportRowStatus,
                                            CsvImportStatus, Debt, DebtStatus, DebtType,
                                            FinancialAttachment, FinancialGoal, GoalPriority,
                                            GoalStatus, MotivationItem, MotivationItemType,
                                            PaymentMethodType, PayoffStrategy, RecurringDebit,
                                            RecurringTransaction, RecurringTransactionKind,
                                            ReviewStatus, SavedReportView, SinkingFund, SnapshotSource,
                                            TransactionClassification, TransactionType)
from app.services import bills_service as bills_svc
from app.services import budget_service as budget_svc
from app.services import crm_service as svc
from app.services import csv_import_service as csv_import_svc
from app.services import debts_service as debts_svc
from app.services import financial_accounts_service as accounts_svc
from app.services import financial_dashboard_service as dash_svc
from app.services import financial_insights_service as insights_svc
from app.services import financial_reports_service as fin_reports_svc
from app.services import financial_transactions_service as tx_svc
from app.services import goals_service as goals_svc
from app.services import motivation_service as motivation_svc
from app.services import net_worth_service as networth_svc
from app.services import recurring_service as recurring_svc
from app.services.bills_service import BillValidationError
from app.services.budget_service import BudgetValidationError
from app.services.csv_import_service import CsvImportValidationError
from app.services.debts_service import DebtValidationError
from app.services.goals_service import GoalValidationError
from app.services.motivation_service import MotivationValidationError
from app.services import reports_service
from app.services.financial_transactions_service import TransactionValidationError
from app.services.recurring_service import RecurringValidationError

financial_workspace_bp = Blueprint(
    "financial_workspace", __name__, url_prefix="/meu-plano-financeiro/workspace")


def _financial_client_for_current_user() -> FinancialClient | None:
    if not current_user.is_authenticated:
        return None
    return SessionLocal.query(FinancialClient).filter_by(user_id=current_user.id).first()


@financial_workspace_bp.before_request
@login_required
def _require_access():
    fc = _financial_client_for_current_user()
    if fc is None or not fc.financial_planning_enabled or fc.workspace is None:
        flash("Financial Planning is not available for your account yet.", "error")
        return redirect(url_for("wizard.dashboard"))


@financial_workspace_bp.route("/resumo")
def dashboard():
    """Fase 3 (Dashboard) -- Visão Geral: KPIs e gráficos calculados só
    com o que já existe (Fase 1/2, contas e transações). KPIs/gráficos
    do documento que dependem de módulos ainda não construídos (Bills,
    Debts, Financial Goals, Budget allocations) não aparecem aqui --
    nunca mostrar zero/placeholder fingindo ser dado real."""
    fc = _financial_client_for_current_user()
    workspace = fc.workspace

    period = request.args.get("period", "month")
    if period not in reports_service.PERIODS:
        period = "month"
    start, end = reports_service.period_range(period)

    income_cents = dash_svc.monthly_income_cents(workspace, start=start, end=end)
    expenses_cents = dash_svc.monthly_expenses_cents(workspace, start=start, end=end)

    return render_template(
        "financial_dashboard.html", workspace=workspace, periods=reports_service.PERIODS,
        period=period, start=start, end=end, income_cents=income_cents, expenses_cents=expenses_cents,
        net_cash_flow_cents=income_cents - expenses_cents,
        savings_rate=dash_svc.savings_rate(workspace, start=start, end=end),
        total_cash_cents=dash_svc.total_cash_cents(workspace),
        net_worth_cents=dash_svc.net_worth_cents(workspace),
        spending_by_category=dash_svc.spending_by_category(workspace, start=start, end=end),
        needs_wants_savings=dash_svc.needs_wants_savings_breakdown(workspace, start=start, end=end),
        account_distribution=dash_svc.account_distribution(workspace),
        cash_flow_by_month=dash_svc.cash_flow_by_month(workspace, months=6))


@financial_workspace_bp.route("/")
def index():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    accounts = accounts_svc.list_accounts(workspace)
    transactions = tx_svc.list_transactions(workspace, limit=25)
    categories = (
        SessionLocal.query(BudgetCategory)
        .filter_by(financial_workspace_id=workspace.id, active=True)
        .order_by(BudgetCategory.sort_order, BudgetCategory.name).all()
    )
    total_balance_cents = sum(a.current_balance_cents for a in accounts if a.include_in_net_worth)
    return render_template(
        "financial_workspace.html", workspace=workspace, accounts=accounts,
        transactions=transactions, categories=categories, total_balance_cents=total_balance_cents,
        account_types=list(AccountType), transaction_types=list(TransactionType),
        payment_methods=list(PaymentMethodType), classifications=list(TransactionClassification),
        category_groups=list(BudgetCategoryGroup), today=date.today().isoformat())


@financial_workspace_bp.route("/contas/nova", methods=["POST"])
def account_new():
    fc = _financial_client_for_current_user()
    account_name = request.form.get("account_name", "").strip()
    account_type = svc.parse_enum(AccountType, request.form.get("account_type"))
    if not account_name or account_type is None:
        flash("Account name and type are required.", "error")
        return redirect(url_for("financial_workspace.index"))

    accounts_svc.create_account(
        fc.workspace, actor=current_user, account_name=account_name, account_type=account_type,
        institution_name=request.form.get("institution_name", "").strip() or None,
        nickname=request.form.get("nickname", "").strip() or None,
        last_four_digits=request.form.get("last_four_digits", "").strip()[:4] or None,
        current_balance_cents=svc.parse_dollars_to_cents(request.form.get("current_balance")) or 0,
        include_in_cash_flow=request.form.get("include_in_cash_flow") == "on",
        include_in_net_worth=request.form.get("include_in_net_worth") == "on",
        notes=request.form.get("notes", "").strip() or None,
    )
    flash("Account added.", "success")
    return redirect(url_for("financial_workspace.index"))


@financial_workspace_bp.route("/contas/<int:account_id>/salvar", methods=["POST"])
def account_save(account_id: int):
    fc = _financial_client_for_current_user()
    account = SessionLocal.get(Account, account_id)
    if account is None or account.financial_workspace_id != fc.workspace.id:
        flash("Account not found.", "error")
        return redirect(url_for("financial_workspace.index"))

    account_name = request.form.get("account_name", "").strip()
    if not account_name:
        flash("Account name is required.", "error")
        return redirect(url_for("financial_workspace.index"))

    accounts_svc.update_account(
        account, account_name=account_name,
        institution_name=request.form.get("institution_name", "").strip() or None,
        nickname=request.form.get("nickname", "").strip() or None,
        current_balance_cents=svc.parse_dollars_to_cents(request.form.get("current_balance")) or 0,
        include_in_cash_flow=request.form.get("include_in_cash_flow") == "on",
        include_in_net_worth=request.form.get("include_in_net_worth") == "on",
        notes=request.form.get("notes", "").strip() or None,
    )
    flash("Account updated.", "success")
    return redirect(url_for("financial_workspace.index"))


@financial_workspace_bp.route("/contas/<int:account_id>/excluir", methods=["POST"])
def account_delete(account_id: int):
    fc = _financial_client_for_current_user()
    account = SessionLocal.get(Account, account_id)
    if account is None or account.financial_workspace_id != fc.workspace.id:
        flash("Account not found.", "error")
        return redirect(url_for("financial_workspace.index"))
    accounts_svc.soft_delete_account(account)
    flash("Account removed.", "success")
    return redirect(url_for("financial_workspace.index"))


@financial_workspace_bp.route("/transacoes/nova", methods=["POST"])
def transaction_new():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace

    transaction_type = svc.parse_enum(TransactionType, request.form.get("transaction_type"))
    name = request.form.get("name", "").strip()
    amount_cents = svc.parse_dollars_to_cents(request.form.get("amount"))
    transaction_date = svc.parse_date(request.form.get("transaction_date"))
    if transaction_type is None or not name or not amount_cents or transaction_date is None:
        flash("Type, name, amount and date are required.", "error")
        return redirect(url_for("financial_workspace.index"))

    try:
        tx_svc.create_transaction(
            workspace, actor=current_user, transaction_type=transaction_type, name=name,
            amount_cents=amount_cents, transaction_date=transaction_date,
            account_id=svc.parse_int(request.form.get("account_id")),
            transfer_from_account_id=svc.parse_int(request.form.get("transfer_from_account_id")),
            transfer_to_account_id=svc.parse_int(request.form.get("transfer_to_account_id")),
            budget_category_id=svc.parse_int(request.form.get("budget_category_id")),
            merchant_or_source=request.form.get("merchant_or_source", "").strip() or None,
            payment_method=svc.parse_enum(PaymentMethodType, request.form.get("payment_method")),
            classification=svc.parse_enum(TransactionClassification, request.form.get("classification")),
            notes=request.form.get("notes", "").strip() or None,
        )
    except TransactionValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.index"))

    flash("Transaction added.", "success")
    return redirect(url_for("financial_workspace.index"))


@financial_workspace_bp.route("/transacoes/<int:transaction_id>/excluir", methods=["POST"])
def transaction_delete(transaction_id: int):
    from app.financial_planning_models import FinancialTransaction

    fc = _financial_client_for_current_user()
    transaction = SessionLocal.get(FinancialTransaction, transaction_id)
    if transaction is None or transaction.financial_workspace_id != fc.workspace.id:
        flash("Transaction not found.", "error")
        return redirect(url_for("financial_workspace.index"))
    tx_svc.soft_delete_transaction(transaction)
    flash("Transaction removed.", "success")
    return redirect(url_for("financial_workspace.index"))


@financial_workspace_bp.route("/categorias/nova", methods=["POST"])
def category_new():
    fc = _financial_client_for_current_user()
    name = request.form.get("name", "").strip()
    category_group = svc.parse_enum(BudgetCategoryGroup, request.form.get("category_group"))
    if not name or category_group is None:
        flash("Category name and group are required.", "error")
        return redirect(url_for("financial_workspace.index"))

    SessionLocal.add(BudgetCategory(
        financial_workspace_id=fc.workspace.id, name=name, category_group=category_group))
    SessionLocal.commit()
    flash("Category added.", "success")
    return redirect(url_for("financial_workspace.index"))


# --------------------------------------------------------------------------
# Fase 4 (Orçamento)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/orcamento")
def budget():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    period = budget_svc.get_or_create_current_period(workspace)

    rule = budget_svc.get_budget_rule(workspace)
    income_cents = dash_svc.monthly_income_cents(workspace, start=period.period_start, end=period.period_end)
    targets_cents = budget_svc.rule_targets_cents(rule, income_cents)
    needs_wants_savings = dash_svc.needs_wants_savings_breakdown(
        workspace, start=period.period_start, end=period.period_end)

    categories = (
        SessionLocal.query(BudgetCategory)
        .filter_by(financial_workspace_id=workspace.id, active=True)
        .order_by(BudgetCategory.sort_order, BudgetCategory.name).all()
    )
    allocated_category_ids = {
        a.budget_category_id for a in
        SessionLocal.query(budget_svc.BudgetAllocation).filter_by(budget_period_id=period.id).all()
    }
    unallocated_categories = [c for c in categories if c.id not in allocated_category_ids]

    return render_template(
        "financial_budget.html", workspace=workspace, period=period, rule=rule,
        rule_types=list(BudgetRuleType), income_cents=income_cents, targets_cents=targets_cents,
        needs_wants_savings=needs_wants_savings,
        budget_rows=budget_svc.budget_vs_actual(workspace, period),
        unallocated_categories=unallocated_categories)


@financial_workspace_bp.route("/orcamento/regra", methods=["POST"])
def budget_rule_save():
    fc = _financial_client_for_current_user()
    rule_type = svc.parse_enum(BudgetRuleType, request.form.get("rule_type"))
    if rule_type is None:
        flash("Choose a budget method.", "error")
        return redirect(url_for("financial_workspace.budget"))

    try:
        budget_svc.set_budget_rule(
            fc.workspace, rule_type=rule_type,
            needs_percent=svc.parse_int(request.form.get("needs_percent")),
            wants_percent=svc.parse_int(request.form.get("wants_percent")),
            savings_percent=svc.parse_int(request.form.get("savings_percent")))
    except BudgetValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.budget"))

    flash("Budget method updated.", "success")
    return redirect(url_for("financial_workspace.budget"))


@financial_workspace_bp.route("/orcamento/alocacao", methods=["POST"])
def budget_allocation_save():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    period = budget_svc.get_or_create_current_period(workspace)

    category = SessionLocal.get(BudgetCategory, svc.parse_int(request.form.get("budget_category_id")))
    planned_amount_cents = svc.parse_dollars_to_cents(request.form.get("planned_amount"))
    if category is None or category.financial_workspace_id != workspace.id or not planned_amount_cents:
        flash("Choose a category and a planned amount.", "error")
        return redirect(url_for("financial_workspace.budget"))

    try:
        budget_svc.set_allocation(
            period, category, planned_amount_cents=planned_amount_cents,
            rollover_enabled=request.form.get("rollover_enabled") == "on")
    except BudgetValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.budget"))

    flash("Budget allocation saved.", "success")
    return redirect(url_for("financial_workspace.budget"))


@financial_workspace_bp.route("/orcamento/fechar", methods=["POST"])
def budget_period_close():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    period = budget_svc.get_or_create_current_period(workspace)
    try:
        budget_svc.close_period(workspace, period, actor=current_user)
    except BudgetValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.budget"))
    flash("Month closed. A protected snapshot was saved.", "success")
    return redirect(url_for("financial_workspace.budget"))


@financial_workspace_bp.route("/orcamento/reabrir", methods=["POST"])
def budget_period_reopen():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    period = budget_svc.get_or_create_current_period(workspace)
    try:
        budget_svc.reopen_period(period, actor=current_user)
    except BudgetValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.budget"))
    flash("Month reopened.", "success")
    return redirect(url_for("financial_workspace.budget"))


# --------------------------------------------------------------------------
# Fase 5 (Bills)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/contas-a-pagar")
def bills():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    bills_svc.ensure_payments_for_month(workspace)

    categories = (
        SessionLocal.query(BudgetCategory)
        .filter_by(financial_workspace_id=workspace.id, active=True)
        .order_by(BudgetCategory.sort_order, BudgetCategory.name).all()
    )
    return render_template(
        "financial_bills.html", workspace=workspace,
        bill_list=bills_svc.list_bills(workspace), payments=bills_svc.list_payments_for_month(workspace),
        upcoming=bills_svc.upcoming_within_days(workspace), categories=categories,
        accounts=accounts_svc.list_accounts(workspace), frequencies=list(BillFrequency),
        display_status=bills_svc.display_status, today=date.today())


@financial_workspace_bp.route("/contas-a-pagar/calendario")
def bills_calendar():
    from app.services.calendar_view import build_calendar_grid

    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    today = date.today()
    year = svc.parse_int(request.args.get("year")) or today.year
    month = svc.parse_int(request.args.get("month")) or today.month
    bills_svc.ensure_payments_for_month(workspace, for_date=date(year, month, 1))

    rows = bills_svc.payments_for_calendar(workspace, year=year, month=month)
    calendar_grid = build_calendar_grid(rows, lambda row: row["payment"].due_date, year, month)

    def title_fn(row):
        from app.services.formatting import format_usd
        return f"{row['bill'].bill_name} {format_usd(row['payment'].amount_cents)}"

    def url_fn(row):
        return url_for("financial_workspace.bills")

    def color_fn(row):
        st = bills_svc.display_status(row["payment"])
        if st == "paid":
            return "#16a34a"
        if st == "overdue":
            return "#dc2626"
        if st in ("skipped", "cancelled"):
            return "#9ca3af"
        return "#eb6834"

    return render_template(
        "financial_bills_calendar.html", workspace=workspace, calendar_grid=calendar_grid,
        title_fn=title_fn, url_fn=url_fn, color_fn=color_fn)


@financial_workspace_bp.route("/contas-a-pagar/nova", methods=["POST"])
def bill_new():
    fc = _financial_client_for_current_user()
    bill_name = request.form.get("bill_name", "").strip()
    try:
        bills_svc.create_bill(
            fc.workspace, actor=current_user, bill_name=bill_name,
            budget_category_id=svc.parse_int(request.form.get("budget_category_id")),
            default_amount_cents=svc.parse_dollars_to_cents(request.form.get("default_amount")),
            due_day=svc.parse_int(request.form.get("due_day")),
            frequency=svc.parse_enum(BillFrequency, request.form.get("frequency"), BillFrequency.monthly),
            default_payment_account_id=svc.parse_int(request.form.get("default_payment_account_id")),
            autopay=request.form.get("autopay") == "on",
            start_date=svc.parse_date(request.form.get("start_date")),
            end_date=svc.parse_date(request.form.get("end_date")),
            notes=request.form.get("notes", "").strip() or None,
        )
    except BillValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.bills"))

    flash("Bill added.", "success")
    return redirect(url_for("financial_workspace.bills"))


@financial_workspace_bp.route("/contas-a-pagar/<int:bill_id>/excluir", methods=["POST"])
def bill_delete(bill_id: int):
    fc = _financial_client_for_current_user()
    bill = SessionLocal.get(Bill, bill_id)
    if bill is None or bill.financial_workspace_id != fc.workspace.id:
        flash("Bill not found.", "error")
        return redirect(url_for("financial_workspace.bills"))
    bills_svc.soft_delete_bill(bill)
    flash("Bill removed. Its payment history is kept.", "success")
    return redirect(url_for("financial_workspace.bills"))


@financial_workspace_bp.route("/contas-a-pagar/pagamento/<int:payment_id>/pagar", methods=["POST"])
def bill_payment_pay(payment_id: int):
    fc = _financial_client_for_current_user()
    payment = SessionLocal.get(BillPayment, payment_id)
    bill = SessionLocal.get(Bill, payment.bill_id) if payment else None
    if payment is None or bill is None or bill.financial_workspace_id != fc.workspace.id:
        flash("Bill payment not found.", "error")
        return redirect(url_for("financial_workspace.bills"))

    try:
        bills_svc.mark_paid(
            payment, actor=current_user, paid_date=svc.parse_date(request.form.get("paid_date")),
            paid_from_account_id=svc.parse_int(request.form.get("paid_from_account_id")),
            confirmation_number=request.form.get("confirmation_number", "").strip() or None,
        )
    except BillValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.bills"))

    flash("Bill marked as paid.", "success")
    return redirect(url_for("financial_workspace.bills"))


@financial_workspace_bp.route("/contas-a-pagar/pagamento/<int:payment_id>/pular", methods=["POST"])
def bill_payment_skip(payment_id: int):
    fc = _financial_client_for_current_user()
    payment = SessionLocal.get(BillPayment, payment_id)
    bill = SessionLocal.get(Bill, payment.bill_id) if payment else None
    if payment is None or bill is None or bill.financial_workspace_id != fc.workspace.id:
        flash("Bill payment not found.", "error")
        return redirect(url_for("financial_workspace.bills"))

    try:
        bills_svc.skip_payment(payment, actor=current_user)
    except BillValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.bills"))

    flash("Bill payment skipped for this month.", "success")
    return redirect(url_for("financial_workspace.bills"))


# --------------------------------------------------------------------------
# Fase 6 (Recurring)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/recorrentes")
def recurring():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    generated = recurring_svc.generate_due_transactions(workspace)
    if generated:
        flash(f"{len(generated)} recurring transaction(s) were posted automatically.", "success")

    return render_template(
        "financial_recurring.html", workspace=workspace,
        recurring_list=recurring_svc.list_recurring_transactions(workspace),
        accounts=accounts_svc.list_accounts(workspace), kinds=list(RecurringTransactionKind),
        frequencies=list(BillFrequency), today=date.today())


@financial_workspace_bp.route("/recorrentes/nova", methods=["POST"])
def recurring_new():
    fc = _financial_client_for_current_user()
    try:
        recurring_svc.create_recurring_transaction(
            fc.workspace, actor=current_user,
            transaction_kind=svc.parse_enum(RecurringTransactionKind, request.form.get("transaction_kind")),
            name=request.form.get("name", "").strip(),
            amount_cents=svc.parse_dollars_to_cents(request.form.get("amount")),
            frequency=svc.parse_enum(BillFrequency, request.form.get("frequency"), BillFrequency.monthly),
            start_date=svc.parse_date(request.form.get("start_date")) or date.today(),
            end_date=svc.parse_date(request.form.get("end_date")),
            account_id=svc.parse_int(request.form.get("account_id")),
            notes=request.form.get("notes", "").strip() or None,
        )
    except RecurringValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.recurring"))

    flash("Recurring schedule added.", "success")
    return redirect(url_for("financial_workspace.recurring"))


@financial_workspace_bp.route("/recorrentes/<int:recurring_id>/excluir", methods=["POST"])
def recurring_delete(recurring_id: int):
    fc = _financial_client_for_current_user()
    recurring = SessionLocal.get(RecurringTransaction, recurring_id)
    if recurring is None or recurring.financial_workspace_id != fc.workspace.id:
        flash("Recurring schedule not found.", "error")
        return redirect(url_for("financial_workspace.recurring"))
    recurring_svc.soft_delete_recurring_transaction(recurring)
    flash("Recurring schedule removed. Already-posted transactions are kept.", "success")
    return redirect(url_for("financial_workspace.recurring"))


@financial_workspace_bp.route("/assinaturas")
def subscriptions():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    categories = (
        SessionLocal.query(BudgetCategory)
        .filter_by(financial_workspace_id=workspace.id, active=True)
        .order_by(BudgetCategory.sort_order, BudgetCategory.name).all()
    )
    return render_template(
        "financial_subscriptions.html", workspace=workspace,
        debit_list=recurring_svc.list_recurring_debits(workspace, include_inactive=True),
        summary=recurring_svc.subscription_summary(workspace),
        accounts=accounts_svc.list_accounts(workspace), categories=categories,
        frequencies=list(BillFrequency), review_statuses=list(ReviewStatus))


@financial_workspace_bp.route("/assinaturas/nova", methods=["POST"])
def subscription_new():
    fc = _financial_client_for_current_user()
    try:
        recurring_svc.create_recurring_debit(
            fc.workspace, actor=current_user, merchant=request.form.get("merchant", "").strip(),
            description=request.form.get("description", "").strip() or None,
            amount_cents=svc.parse_dollars_to_cents(request.form.get("amount")),
            frequency=svc.parse_enum(BillFrequency, request.form.get("frequency"), BillFrequency.monthly),
            next_charge_date=svc.parse_date(request.form.get("next_charge_date")),
            budget_category_id=svc.parse_int(request.form.get("budget_category_id")),
            account_id=svc.parse_int(request.form.get("account_id")),
            autopay=request.form.get("autopay") == "on",
            notes=request.form.get("notes", "").strip() or None,
        )
    except RecurringValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.subscriptions"))

    flash("Subscription added.", "success")
    return redirect(url_for("financial_workspace.subscriptions"))


@financial_workspace_bp.route("/assinaturas/<int:debit_id>/status", methods=["POST"])
def subscription_status(debit_id: int):
    fc = _financial_client_for_current_user()
    debit = SessionLocal.get(RecurringDebit, debit_id)
    if debit is None or debit.financial_workspace_id != fc.workspace.id:
        flash("Subscription not found.", "error")
        return redirect(url_for("financial_workspace.subscriptions"))

    review_status = svc.parse_enum(ReviewStatus, request.form.get("review_status"))
    if review_status is None:
        flash("Choose a review status.", "error")
        return redirect(url_for("financial_workspace.subscriptions"))

    recurring_svc.set_review_status(debit, review_status)
    flash("Subscription updated.", "success")
    return redirect(url_for("financial_workspace.subscriptions"))


@financial_workspace_bp.route("/assinaturas/<int:debit_id>/excluir", methods=["POST"])
def subscription_delete(debit_id: int):
    fc = _financial_client_for_current_user()
    debit = SessionLocal.get(RecurringDebit, debit_id)
    if debit is None or debit.financial_workspace_id != fc.workspace.id:
        flash("Subscription not found.", "error")
        return redirect(url_for("financial_workspace.subscriptions"))
    recurring_svc.soft_delete_recurring_debit(debit)
    flash("Subscription removed.", "success")
    return redirect(url_for("financial_workspace.subscriptions"))


# --------------------------------------------------------------------------
# Fase 7 (Goals & Savings)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/metas")
def goals():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    goal_list = goals_svc.list_goals(workspace, include_inactive=True)
    progress_by_goal = {g.id: goals_svc.goal_progress(g) for g in goal_list}
    return render_template(
        "financial_goals.html", workspace=workspace, goal_list=goal_list,
        progress_by_goal=progress_by_goal, accounts=accounts_svc.list_accounts(workspace),
        priorities=list(GoalPriority), statuses=list(GoalStatus), today=date.today())


@financial_workspace_bp.route("/metas/nova", methods=["POST"])
def goal_new():
    fc = _financial_client_for_current_user()
    try:
        goals_svc.create_goal(
            fc.workspace, actor=current_user, name=request.form.get("name", "").strip(),
            target_amount_cents=svc.parse_dollars_to_cents(request.form.get("target_amount")),
            goal_type=request.form.get("goal_type", "").strip() or None,
            target_date=svc.parse_date(request.form.get("target_date")),
            monthly_contribution_cents=svc.parse_dollars_to_cents(request.form.get("monthly_contribution")),
            priority=svc.parse_enum(GoalPriority, request.form.get("priority"), GoalPriority.medium),
            account_id=svc.parse_int(request.form.get("account_id")),
            notes=request.form.get("notes", "").strip() or None,
        )
    except GoalValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.goals"))

    flash("Goal added.", "success")
    return redirect(url_for("financial_workspace.goals"))


@financial_workspace_bp.route("/metas/<int:goal_id>/aporte", methods=["POST"])
def goal_contribution_new(goal_id: int):
    fc = _financial_client_for_current_user()
    goal = SessionLocal.get(FinancialGoal, goal_id)
    if goal is None or goal.financial_workspace_id != fc.workspace.id:
        flash("Goal not found.", "error")
        return redirect(url_for("financial_workspace.goals"))

    try:
        goals_svc.add_contribution(
            goal, amount_cents=svc.parse_dollars_to_cents(request.form.get("amount")),
            contribution_date=svc.parse_date(request.form.get("contribution_date")) or date.today(),
            from_account_id=svc.parse_int(request.form.get("from_account_id")),
            notes=request.form.get("notes", "").strip() or None,
        )
    except GoalValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.goals"))

    flash("Contribution added.", "success")
    return redirect(url_for("financial_workspace.goals"))


@financial_workspace_bp.route("/metas/<int:goal_id>/status", methods=["POST"])
def goal_status_update(goal_id: int):
    fc = _financial_client_for_current_user()
    goal = SessionLocal.get(FinancialGoal, goal_id)
    if goal is None or goal.financial_workspace_id != fc.workspace.id:
        flash("Goal not found.", "error")
        return redirect(url_for("financial_workspace.goals"))

    status = svc.parse_enum(GoalStatus, request.form.get("status"))
    if status is None:
        flash("Choose a status.", "error")
        return redirect(url_for("financial_workspace.goals"))
    goals_svc.set_goal_status(goal, status)
    flash("Goal updated.", "success")
    return redirect(url_for("financial_workspace.goals"))


@financial_workspace_bp.route("/metas/<int:goal_id>/excluir", methods=["POST"])
def goal_delete(goal_id: int):
    fc = _financial_client_for_current_user()
    goal = SessionLocal.get(FinancialGoal, goal_id)
    if goal is None or goal.financial_workspace_id != fc.workspace.id:
        flash("Goal not found.", "error")
        return redirect(url_for("financial_workspace.goals"))
    goals_svc.soft_delete_goal(goal)
    flash("Goal removed.", "success")
    return redirect(url_for("financial_workspace.goals"))


@financial_workspace_bp.route("/fundos")
def sinking_funds():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    return render_template(
        "financial_sinking_funds.html", workspace=workspace,
        fund_list=goals_svc.list_sinking_funds(workspace),
        accounts=accounts_svc.list_accounts(workspace))


@financial_workspace_bp.route("/fundos/novo", methods=["POST"])
def sinking_fund_new():
    fc = _financial_client_for_current_user()
    try:
        goals_svc.create_sinking_fund(
            fc.workspace, actor=current_user, name=request.form.get("name", "").strip(),
            target_amount_cents=svc.parse_dollars_to_cents(request.form.get("target_amount")),
            current_amount_cents=svc.parse_dollars_to_cents(request.form.get("current_amount")) or 0,
            target_date=svc.parse_date(request.form.get("target_date")),
            monthly_contribution_cents=svc.parse_dollars_to_cents(request.form.get("monthly_contribution")),
            account_id=svc.parse_int(request.form.get("account_id")),
        )
    except GoalValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.sinking_funds"))

    flash("Sinking fund added.", "success")
    return redirect(url_for("financial_workspace.sinking_funds"))


@financial_workspace_bp.route("/fundos/<int:fund_id>/saldo", methods=["POST"])
def sinking_fund_balance_update(fund_id: int):
    fc = _financial_client_for_current_user()
    fund = SessionLocal.get(SinkingFund, fund_id)
    if fund is None or fund.financial_workspace_id != fc.workspace.id:
        flash("Sinking fund not found.", "error")
        return redirect(url_for("financial_workspace.sinking_funds"))

    try:
        goals_svc.update_sinking_fund_balance(
            fund, current_amount_cents=svc.parse_dollars_to_cents(request.form.get("current_amount")))
    except GoalValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.sinking_funds"))

    flash("Balance updated.", "success")
    return redirect(url_for("financial_workspace.sinking_funds"))


@financial_workspace_bp.route("/fundos/<int:fund_id>/excluir", methods=["POST"])
def sinking_fund_delete(fund_id: int):
    fc = _financial_client_for_current_user()
    fund = SessionLocal.get(SinkingFund, fund_id)
    if fund is None or fund.financial_workspace_id != fc.workspace.id:
        flash("Sinking fund not found.", "error")
        return redirect(url_for("financial_workspace.sinking_funds"))
    goals_svc.soft_delete_sinking_fund(fund)
    flash("Sinking fund removed.", "success")
    return redirect(url_for("financial_workspace.sinking_funds"))


@financial_workspace_bp.route("/fundo-emergencia")
def emergency_fund():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    return render_template(
        "financial_emergency_fund.html", workspace=workspace,
        summary=goals_svc.emergency_fund_summary(workspace),
        accounts=accounts_svc.list_accounts(workspace))


@financial_workspace_bp.route("/fundo-emergencia/salvar", methods=["POST"])
def emergency_fund_save():
    fc = _financial_client_for_current_user()
    try:
        goals_svc.set_emergency_fund_settings(
            fc.workspace, target_months=svc.parse_int(request.form.get("target_months")),
            account_id=svc.parse_int(request.form.get("account_id")))
    except GoalValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.emergency_fund"))

    flash("Emergency fund settings saved.", "success")
    return redirect(url_for("financial_workspace.emergency_fund"))


# --------------------------------------------------------------------------
# Fase 8 (Debt Management)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/dividas")
def debts():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    debt_list = debts_svc.list_debts(workspace, include_inactive=True)
    return render_template(
        "financial_debts.html", workspace=workspace, debt_list=debt_list,
        progress_by_debt={d.id: debts_svc.debt_progress(d) for d in debt_list},
        summary=debts_svc.workspace_debt_summary(workspace),
        accounts=accounts_svc.list_accounts(workspace), debt_types=list(DebtType), today=date.today())


@financial_workspace_bp.route("/dividas/nova", methods=["POST"])
def debt_new():
    fc = _financial_client_for_current_user()
    try:
        debts_svc.create_debt(
            fc.workspace, actor=current_user, debt_name=request.form.get("debt_name", "").strip(),
            current_balance_cents=svc.parse_dollars_to_cents(request.form.get("current_balance")),
            lender_name=request.form.get("lender_name", "").strip() or None,
            debt_type=svc.parse_enum(DebtType, request.form.get("debt_type"), DebtType.other),
            original_balance_cents=svc.parse_dollars_to_cents(request.form.get("original_balance")),
            apr_bps=round(float(request.form["apr"]) * 100) if request.form.get("apr") else None,
            minimum_payment_cents=svc.parse_dollars_to_cents(request.form.get("minimum_payment")),
            extra_monthly_payment_cents=svc.parse_dollars_to_cents(request.form.get("extra_payment")),
            due_day=svc.parse_int(request.form.get("due_day")),
            target_payoff_date=svc.parse_date(request.form.get("target_payoff_date")),
            notes=request.form.get("notes", "").strip() or None,
        )
    except DebtValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.debts"))
    except ValueError:
        flash("APR must be a number.", "error")
        return redirect(url_for("financial_workspace.debts"))

    flash("Debt added.", "success")
    return redirect(url_for("financial_workspace.debts"))


@financial_workspace_bp.route("/dividas/<int:debt_id>/pagamento", methods=["POST"])
def debt_payment_new(debt_id: int):
    fc = _financial_client_for_current_user()
    debt = SessionLocal.get(Debt, debt_id)
    if debt is None or debt.financial_workspace_id != fc.workspace.id:
        flash("Debt not found.", "error")
        return redirect(url_for("financial_workspace.debts"))

    try:
        debts_svc.record_payment(
            debt, amount_cents=svc.parse_dollars_to_cents(request.form.get("amount")),
            payment_date=svc.parse_date(request.form.get("payment_date")) or date.today(),
            paid_from_account_id=svc.parse_int(request.form.get("paid_from_account_id")),
        )
    except DebtValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.debts"))

    flash("Payment recorded.", "success")
    return redirect(url_for("financial_workspace.debts"))


@financial_workspace_bp.route("/dividas/<int:debt_id>/excluir", methods=["POST"])
def debt_delete(debt_id: int):
    fc = _financial_client_for_current_user()
    debt = SessionLocal.get(Debt, debt_id)
    if debt is None or debt.financial_workspace_id != fc.workspace.id:
        flash("Debt not found.", "error")
        return redirect(url_for("financial_workspace.debts"))
    debts_svc.soft_delete_debt(debt)
    flash("Debt removed. Payment history is kept.", "success")
    return redirect(url_for("financial_workspace.debts"))


@financial_workspace_bp.route("/dividas/plano")
def debt_plan():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    strategy = svc.parse_enum(PayoffStrategy, request.args.get("strategy"), PayoffStrategy.snowball)
    ordered = debts_svc.ordered_debts(workspace, strategy=strategy)
    projections = {d.id: debts_svc.payoff_projection(d) for d in ordered}

    # Gráfico de Gantt (pedido do usuário 2026-08-08) -- só entram dívidas
    # com uma projeção real de quitação (months_to_payoff > 0); a janela
    # do gráfico vai de hoje até a quitação mais distante entre elas, e a
    # barra de cada dívida mostra o quanto falta dela nessa janela --
    # matemática de data fica aqui (Python), o template só desenha % já
    # prontos (ver app/templates/_charts.html::gantt_chart).
    today = date.today()
    payoff_rows = [
        (d, projections[d.id]) for d in ordered
        if projections[d.id] is not None and projections[d.id]["months_to_payoff"] > 0
    ]
    gantt_rows = []
    if payoff_rows:
        horizon_days = max((proj["payoff_date"] - today).days for _d, proj in payoff_rows)
        horizon_days = horizon_days or 1
        for d, proj in payoff_rows:
            days_out = (proj["payoff_date"] - today).days
            gantt_rows.append({
                "label": d.debt_name,
                "start_pct": 0,
                "width_pct": round(days_out / horizon_days * 100, 1),
                "tooltip": f"{d.debt_name} — payoff {proj['payoff_date'].strftime('%m/%d/%Y')} ({proj['months_to_payoff']} mo)",
            })

    return render_template(
        "financial_debt_plan.html", workspace=workspace, strategy=strategy,
        strategies=list(PayoffStrategy), ordered_debts=ordered, projections=projections,
        gantt_rows=gantt_rows)


# --------------------------------------------------------------------------
# Fase 9 (Net Worth)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/patrimonio")
def net_worth():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    accounts = accounts_svc.list_accounts(workspace)
    debt_list = [d for d in debts_svc.list_debts(workspace, include_inactive=False)
                 if d.status in (DebtStatus.active, DebtStatus.delinquent)]
    return render_template(
        "financial_net_worth.html", workspace=workspace,
        summary=networth_svc.current_net_worth(workspace),
        history=networth_svc.net_worth_history(workspace),
        accounts=[a for a in accounts if a.include_in_net_worth],
        debt_list=debt_list,
        snapshots_by_account={a.id: networth_svc.list_snapshots(a, limit=6) for a in accounts},
        today=date.today())


@financial_workspace_bp.route("/patrimonio/snapshot", methods=["POST"])
def net_worth_snapshot_new():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    account = SessionLocal.get(Account, svc.parse_int(request.form.get("account_id")))
    if account is None or account.financial_workspace_id != workspace.id:
        flash("Account not found.", "error")
        return redirect(url_for("financial_workspace.net_worth"))

    balance_cents = svc.parse_dollars_to_cents(request.form.get("balance"))
    if balance_cents is None:
        flash("Enter a balance.", "error")
        return redirect(url_for("financial_workspace.net_worth"))

    networth_svc.record_snapshot(
        account, balance_cents=balance_cents,
        snapshot_date=svc.parse_date(request.form.get("snapshot_date")) or date.today(),
        source=SnapshotSource.manual)
    flash("Balance snapshot recorded.", "success")
    return redirect(url_for("financial_workspace.net_worth"))


# --------------------------------------------------------------------------
# Fase 10 (Motivation Board)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/inspiracao")
def motivation():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    favorites_only = request.args.get("favoritos") == "1"
    return render_template(
        "financial_motivation.html", workspace=workspace,
        items=motivation_svc.list_items(workspace, favorites_only=favorites_only),
        favorites_only=favorites_only, item_types=list(MotivationItemType))


@financial_workspace_bp.route("/inspiracao/novo", methods=["POST"])
def motivation_new():
    fc = _financial_client_for_current_user()
    try:
        item = motivation_svc.create_item(
            fc.workspace, actor=current_user, title=request.form.get("title", "").strip(),
            item_type=svc.parse_enum(MotivationItemType, request.form.get("item_type"), None),
            categories=request.form.get("categories", "").strip() or None,
            source_url=request.form.get("source_url", "").strip() or None,
            location=request.form.get("location", "").strip() or None,
        )
    except MotivationValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.motivation"))

    image = request.files.get("image")
    if image is not None and image.filename:
        try:
            motivation_svc.set_image(
                item, actor=current_user, filename=image.filename,
                mime_type=image.mimetype, content=image.read())
        except MotivationValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("financial_workspace.motivation"))

    flash("Added to your Motivation Board.", "success")
    return redirect(url_for("financial_workspace.motivation"))


def _motivation_item_or_404(workspace, item_id: int) -> MotivationItem:
    item = SessionLocal.get(MotivationItem, item_id)
    if item is None or item.financial_workspace_id != workspace.id:
        abort(404)
    return item


@financial_workspace_bp.route("/inspiracao/<int:item_id>/imagem", methods=["POST"])
def motivation_image(item_id: int):
    fc = _financial_client_for_current_user()
    item = _motivation_item_or_404(fc.workspace, item_id)

    image = request.files.get("image")
    if image is None or not image.filename:
        flash("Choose an image first.", "error")
        return redirect(url_for("financial_workspace.motivation"))

    try:
        motivation_svc.set_image(
            item, actor=current_user, filename=image.filename,
            mime_type=image.mimetype, content=image.read())
    except MotivationValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.motivation"))

    flash("Image updated.", "success")
    return redirect(url_for("financial_workspace.motivation"))


@financial_workspace_bp.route("/inspiracao/<int:item_id>/editar", methods=["POST"])
def motivation_edit(item_id: int):
    fc = _financial_client_for_current_user()
    item = _motivation_item_or_404(fc.workspace, item_id)
    try:
        motivation_svc.update_item(
            item, title=request.form.get("title", "").strip(),
            item_type=svc.parse_enum(MotivationItemType, request.form.get("item_type"), None),
            categories=request.form.get("categories", "").strip() or None,
            source_url=request.form.get("source_url", "").strip() or None,
            location=request.form.get("location", "").strip() or None,
        )
    except MotivationValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.motivation"))

    flash("Updated.", "success")
    return redirect(url_for("financial_workspace.motivation"))


@financial_workspace_bp.route("/inspiracao/reordenar", methods=["POST"])
def motivation_reorder():
    fc = _financial_client_for_current_user()
    ordered_ids = [svc.parse_int(raw) for raw in request.form.getlist("item_id")]
    motivation_svc.reorder_items(fc.workspace, [i for i in ordered_ids if i is not None])
    return redirect(url_for("financial_workspace.motivation"))


@financial_workspace_bp.route("/inspiracao/<int:item_id>/favorito", methods=["POST"])
def motivation_favorite(item_id: int):
    fc = _financial_client_for_current_user()
    item = _motivation_item_or_404(fc.workspace, item_id)
    motivation_svc.toggle_favorite(item)
    return redirect(url_for("financial_workspace.motivation"))


@financial_workspace_bp.route("/inspiracao/<int:item_id>/fixar", methods=["POST"])
def motivation_pin(item_id: int):
    fc = _financial_client_for_current_user()
    item = _motivation_item_or_404(fc.workspace, item_id)
    motivation_svc.toggle_pinned(item)
    return redirect(url_for("financial_workspace.motivation"))


@financial_workspace_bp.route("/inspiracao/<int:item_id>/excluir", methods=["POST"])
def motivation_delete(item_id: int):
    fc = _financial_client_for_current_user()
    item = _motivation_item_or_404(fc.workspace, item_id)
    motivation_svc.delete_item(item)
    flash("Removed from your Motivation Board.", "success")
    return redirect(url_for("financial_workspace.motivation"))


@financial_workspace_bp.route("/inspiracao/imagem/<int:attachment_id>")
def motivation_image_file(attachment_id: int):
    """Serve o bytes da imagem -- storage privado (`instance/document_storage/`
    por trás do `StorageBackend`, nunca uma URL pública permanente, pedido
    explícito do documento em "Attachments"). Checa que o anexo pertence
    ao workspace do cliente logado antes de servir qualquer coisa."""
    fc = _financial_client_for_current_user()
    attachment = SessionLocal.get(FinancialAttachment, attachment_id)
    if (attachment is None or attachment.financial_workspace_id != fc.workspace.id
            or attachment.deleted_at is not None):
        abort(404)

    from app.services.storage import get_storage_backend
    content = get_storage_backend().ler(attachment.storage_key)
    return send_file(io.BytesIO(content), mimetype=attachment.mime_type, download_name=attachment.original_filename)


# --------------------------------------------------------------------------
# Fase 11 (Reports)
# --------------------------------------------------------------------------

def _report_range_from_request() -> tuple[str, date, date]:
    """(period_key, start, end) -- "custom" lê `start`/`end` da query
    string (validados, senão cai pro mês corrente); qualquer outro valor
    (ou nenhum) usa `financial_reports_service.period_range`."""
    period = request.args.get("period", "this_month")
    if period == "custom":
        start = svc.parse_date(request.args.get("start"))
        end = svc.parse_date(request.args.get("end"))
        if start and end and start <= end:
            return period, start, end
        period = "this_month"
    start, end = fin_reports_svc.period_range(period)
    return period, start, end


@financial_workspace_bp.route("/relatorios")
def reports():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    period, start, end = _report_range_from_request()
    return render_template(
        "financial_reports.html", workspace=workspace, period=period, start=start, end=end,
        periods=fin_reports_svc.PERIODS,
        summary=fin_reports_svc.monthly_summary_with_comparison(workspace, start=start, end=end),
        saved_views=fin_reports_svc.list_saved_views(workspace))


@financial_workspace_bp.route("/relatorios/exportar.csv")
def reports_export_csv():
    fc = _financial_client_for_current_user()
    _period, start, end = _report_range_from_request()
    summary = fin_reports_svc.monthly_summary(fc.workspace, start=start, end=end)
    csv_bytes = fin_reports_svc.to_csv_bytes(summary)
    filename = f"monthly-summary-{start.isoformat()}-to-{end.isoformat()}.csv"
    return Response(csv_bytes, mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


@financial_workspace_bp.route("/relatorios/exportar.pdf")
def reports_export_pdf():
    fc = _financial_client_for_current_user()
    _period, start, end = _report_range_from_request()
    summary = fin_reports_svc.monthly_summary(fc.workspace, start=start, end=end)
    pdf_bytes = fin_reports_svc.render_pdf_bytes(summary)
    filename = f"monthly-summary-{start.isoformat()}-to-{end.isoformat()}.pdf"
    return Response(pdf_bytes, mimetype="application/pdf",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


@financial_workspace_bp.route("/relatorios/visualizacoes", methods=["POST"])
def reports_saved_view_new():
    """Salva o período atualmente selecionado em /relatorios (name vem do
    form; period/start/end vêm de hidden fields que espelham a query
    string da própria tela, não de request.args -- este é um POST)."""
    fc = _financial_client_for_current_user()
    name = request.form.get("name", "").strip()
    period = request.form.get("period", "this_month")
    if period not in fin_reports_svc.PERIODS and period != "custom":
        period = "this_month"
    if not name:
        flash("Give the saved view a name.", "error")
        return redirect(url_for("financial_workspace.reports", period=period))

    custom_start = svc.parse_date(request.form.get("start")) if period == "custom" else None
    custom_end = svc.parse_date(request.form.get("end")) if period == "custom" else None
    fin_reports_svc.create_saved_view(
        fc.workspace, actor=current_user, name=name, period=period,
        custom_start=custom_start, custom_end=custom_end)
    flash("View saved.", "success")
    return redirect(url_for("financial_workspace.reports", period=period,
                             start=custom_start, end=custom_end))


@financial_workspace_bp.route("/relatorios/visualizacoes/<int:view_id>/abrir")
def reports_saved_view_open(view_id: int):
    fc = _financial_client_for_current_user()
    view = SessionLocal.get(SavedReportView, view_id)
    if view is None or view.financial_workspace_id != fc.workspace.id:
        flash("Saved view not found.", "error")
        return redirect(url_for("financial_workspace.reports"))
    return redirect(url_for("financial_workspace.reports", period=view.period,
                             start=view.custom_start, end=view.custom_end))


@financial_workspace_bp.route("/relatorios/visualizacoes/<int:view_id>/excluir", methods=["POST"])
def reports_saved_view_delete(view_id: int):
    fc = _financial_client_for_current_user()
    view = SessionLocal.get(SavedReportView, view_id)
    if view is None or view.financial_workspace_id != fc.workspace.id:
        flash("Saved view not found.", "error")
        return redirect(url_for("financial_workspace.reports"))
    fin_reports_svc.delete_saved_view(view)
    flash("Saved view removed.", "success")
    return redirect(url_for("financial_workspace.reports"))


# --------------------------------------------------------------------------
# Fase 12 (Advanced Tools -- Insights, Forecasts, Calculators)
# --------------------------------------------------------------------------

@financial_workspace_bp.route("/ferramentas")
def tools():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace

    debt_calc_result = None
    if request.args.get("calc") == "debt":
        try:
            debt_calc_result = insights_svc.debt_payoff_calculator(
                balance_cents=svc.parse_dollars_to_cents(request.args.get("balance")) or 0,
                apr_bps=round(float(request.args["apr"]) * 100) if request.args.get("apr") else None,
                monthly_payment_cents=svc.parse_dollars_to_cents(request.args.get("payment")) or 0,
            )
        except (ValueError, KeyError):
            flash("Enter a valid balance, APR, and payment.", "error")

    goal_calc_result = None
    if request.args.get("calc") == "goal":
        try:
            goal_calc_result = insights_svc.goal_savings_calculator(
                target_amount_cents=svc.parse_dollars_to_cents(request.args.get("target")) or 0,
                current_amount_cents=svc.parse_dollars_to_cents(request.args.get("current")) or 0,
                monthly_contribution_cents=svc.parse_dollars_to_cents(request.args.get("contribution")) or 0,
            )
        except (ValueError, KeyError):
            flash("Enter valid amounts.", "error")

    return render_template(
        "financial_tools.html", workspace=workspace,
        insights=insights_svc.all_insights(workspace),
        forecast=insights_svc.cash_flow_forecast(workspace),
        debt_calc_result=debt_calc_result, goal_calc_result=goal_calc_result,
        debt_calc_form=request.args if request.args.get("calc") == "debt" else {},
        goal_calc_form=request.args if request.args.get("calc") == "goal" else {})


# --------------------------------------------------------------------------
# Fase 12 (Advanced Tools -- CSV Import)
# --------------------------------------------------------------------------

def _csv_batch_or_404(workspace, batch_id: int) -> CsvImportBatch:
    batch = SessionLocal.get(CsvImportBatch, batch_id)
    if batch is None or batch.financial_workspace_id != workspace.id:
        abort(404)
    return batch


@financial_workspace_bp.route("/importar-csv")
def csv_import_start():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    return render_template(
        "financial_csv_import.html", workspace=workspace,
        accounts=accounts_svc.list_accounts(workspace), batches=csv_import_svc.list_batches(workspace))


@financial_workspace_bp.route("/importar-csv/novo", methods=["POST"])
def csv_import_new():
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    account = SessionLocal.get(Account, svc.parse_int(request.form.get("account_id")))
    file_storage = request.files.get("file")

    if account is None or account.financial_workspace_id != workspace.id:
        flash("Choose a valid account.", "error")
        return redirect(url_for("financial_workspace.csv_import_start"))
    if file_storage is None or not file_storage.filename:
        flash("Choose a CSV file first.", "error")
        return redirect(url_for("financial_workspace.csv_import_start"))

    try:
        batch = csv_import_svc.create_batch(
            workspace, actor=current_user, account=account,
            filename=file_storage.filename, content=file_storage.read())
    except CsvImportValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.csv_import_start"))

    return redirect(url_for("financial_workspace.csv_import_map", batch_id=batch.id))


@financial_workspace_bp.route("/importar-csv/<int:batch_id>/mapear", methods=["GET", "POST"])
def csv_import_map(batch_id: int):
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    batch = _csv_batch_or_404(workspace, batch_id)

    if request.method == "POST":
        try:
            csv_import_svc.set_column_mapping(
                workspace, batch, date_col=request.form.get("date_col", ""),
                description_col=request.form.get("description_col", ""),
                amount_col=request.form.get("amount_col") or None,
                debit_col=request.form.get("debit_col") or None,
                credit_col=request.form.get("credit_col") or None,
            )
        except CsvImportValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("financial_workspace.csv_import_map", batch_id=batch.id))
        return redirect(url_for("financial_workspace.csv_import_review", batch_id=batch.id))

    return render_template("financial_csv_import_map.html", workspace=workspace, batch=batch)


@financial_workspace_bp.route("/importar-csv/<int:batch_id>/revisar")
def csv_import_review(batch_id: int):
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    batch = _csv_batch_or_404(workspace, batch_id)
    return render_template(
        "financial_csv_import_review.html", workspace=workspace, batch=batch,
        rows=csv_import_svc.list_rows(batch), accounts=accounts_svc.list_accounts(workspace),
        categories=SessionLocal.query(BudgetCategory).filter_by(financial_workspace_id=workspace.id, active=True).all(),
        transaction_types=list(TransactionType))


@financial_workspace_bp.route("/importar-csv/<int:batch_id>/confirmar", methods=["POST"])
def csv_import_confirm(batch_id: int):
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    batch = _csv_batch_or_404(workspace, batch_id)

    selections: dict[int, dict] = {}
    for row in csv_import_svc.list_rows(batch):
        prefix = f"row_{row.id}_"
        selections[row.id] = {
            "import": request.form.get(f"{prefix}import") == "1",
            "type": svc.parse_enum(TransactionType, request.form.get(f"{prefix}type"), None),
            "category_id": svc.parse_int(request.form.get(f"{prefix}category_id")),
            "transfer_counterpart_account_id": svc.parse_int(request.form.get(f"{prefix}transfer_account_id")),
        }

    try:
        csv_import_svc.confirm_import(workspace, batch, actor=current_user, selections=selections)
    except CsvImportValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("financial_workspace.csv_import_review", batch_id=batch.id))

    return redirect(url_for("financial_workspace.csv_import_report", batch_id=batch.id))


@financial_workspace_bp.route("/importar-csv/<int:batch_id>/relatorio")
def csv_import_report(batch_id: int):
    fc = _financial_client_for_current_user()
    workspace = fc.workspace
    batch = _csv_batch_or_404(workspace, batch_id)
    rows = csv_import_svc.list_rows(batch)
    return render_template(
        "financial_csv_import_report.html", workspace=workspace, batch=batch,
        error_rows=[r for r in rows if r.status == CsvImportRowStatus.error],
        duplicate_rows=[r for r in rows if r.status == CsvImportRowStatus.duplicate],
        skipped_rows=[r for r in rows if r.status == CsvImportRowStatus.skipped])
