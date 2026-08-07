"""Blueprint do CRM (staff) -- aba Reports: gráficos de Payments (Payable/
Receivable por tipo), Leads por source, motivos de não-fechamento, lista
de leads sem source pra completar (pedido do usuário 2026-08-06), e --
desde a mesma data, Fase 9 do Prompt Mestre -- relatório de tradutor,
atrasos, renovações e exportação CSV.
"""
from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required

from app.crm_models import PaymentDirection
from app.services import reports_service as rsvc

crm_reports_bp = Blueprint("crm_reports", __name__, url_prefix="/staff/crm/reports")


@crm_reports_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)


@crm_reports_bp.route("/")
def dashboard():
    period = request.args.get("period", "month")
    if period not in rsvc.PERIODS:
        period = "month"
    start, end = rsvc.period_range(period)

    payable = rsvc.payments_by_service(PaymentDirection.payable, start, end)
    receivable = rsvc.payments_by_service(PaymentDirection.receivable, start, end)
    leads_sources = rsvc.leads_by_source(start, end)
    reasons = rsvc.lost_reasons(start, end)
    missing_source = rsvc.leads_missing_source()
    monthly = rsvc.monthly_comparison(6) if period == "last_6_months" else []
    translator_rows = rsvc.translator_report(start, end)
    overdue = rsvc.overdue_report()
    renewals = rsvc.renewals_report(90)

    return render_template(
        "crm_reports.html", periods=rsvc.PERIODS, period=period, start=start, end=end,
        payable=payable, receivable=receivable, leads_sources=leads_sources,
        reasons=reasons, missing_source=missing_source, monthly=monthly,
        payable_total=sum(r["amount_cents"] for r in payable),
        receivable_total=sum(r["amount_cents"] for r in receivable),
        translator_rows=translator_rows, overdue=overdue, renewals=renewals)


_EXPORTABLE_REPORTS = {
    # key -> (builder(start, end) -> list[dict], header row)
    "payable": (lambda s, e: rsvc.payments_by_service(PaymentDirection.payable, s, e),
                ["Service", "Amount (USD)"]),
    "receivable": (lambda s, e: rsvc.payments_by_service(PaymentDirection.receivable, s, e),
                   ["Service", "Amount (USD)"]),
    "leads_sources": (rsvc.leads_by_source, ["Source", "Leads"]),
    "reasons": (rsvc.lost_reasons, ["Reason", "Leads"]),
}


@crm_reports_bp.route("/exportar/<key>.csv")
def export_csv(key: str):
    """Exportação CSV -- pedido do documento mestre (Seção 15). Reusa a
    MESMA função de agregação já usada pelos gráficos da tela (nunca uma
    query paralela), então a exportação sempre bate com o que a tela
    mostra pro mesmo período."""
    entry = _EXPORTABLE_REPORTS.get(key)
    if entry is None:
        abort(404)
    builder, header = entry

    period = request.args.get("period", "month")
    if period not in rsvc.PERIODS:
        period = "month"
    start, end = rsvc.period_range(period)
    rows = builder(start, end)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        value = row.get("amount_cents", row.get("count"))
        if "amount_cents" in row:
            value = f"{value / 100:.2f}"
        writer.writerow([row["label"], value])

    return Response(
        buffer.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={key}_{period}.csv"})
