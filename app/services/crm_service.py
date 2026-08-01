"""Regras de negócio do CRM: campos calculados (equivalentes às `formula`/
`rollup` do Notion, mas nunca gravados -- ver app/crm_models.py) e as
"funções-botão" (equivalentes aos botões do Notion: `Confirm Case Status
Check`, `Submit Application`, `Register Approval`, `Finish Review`).

Convenção deste projeto (mesmo padrão de app/staff.py::confirm_payment/
finalize_payment): as funções aqui só alteram o objeto em memória, nunca
chamam `SessionLocal.commit()` sozinhas -- quem chama (a rota) decide
quando persistir.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import groupby

from app.crm_models import (Case, CaseStatus, Client, Document,
                             DocumentTranslation, Lead, LeadStage,
                             PaymentLedgerEntry, ProcessStatus,
                             ServiceCatalog, ServiceMode, TranslationStatus)
from app.db import SessionLocal
from app.models import User

DEFAULT_STATUS_CHECK_INTERVAL_DAYS = 14


def _today() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------
# Helpers puros compartilhados pelos blueprints staff do CRM
# (app/crm_staff_pipeline.py, app/crm_staff_ops.py) -- vivem aqui, e não
# duplicados em cada blueprint, porque não têm nada de específico de rota;
# ao contrário de `_require_staff` (esse sim fica duplicado de propósito em
# cada blueprint, como defesa em profundidade -- cada um se protege sozinho).
# --------------------------------------------------------------------------

def today() -> date:
    return _today()


def parse_dollars_to_cents(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return round(float(raw.replace(",", ".")) * 100)
    except ValueError:
        return None


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def staff_users() -> list[User]:
    return SessionLocal.query(User).filter_by(is_staff=True).order_by(User.email).all()


def parse_enum(enum_cls, raw, default=None):
    """`enum_cls(raw)` sem estourar `ValueError` -- todo enum do CRM vindo de
    `request.form`/`request.args` deve passar por aqui em vez de ser
    construído direto: um valor inesperado (select desatualizado numa aba
    velha, POST manual) vira `default` (ou `None`) em vez de um 500 cru."""
    if not raw:
        return default
    try:
        return enum_cls(raw)
    except ValueError:
        return default


def parse_int(raw: str | None) -> int | None:
    """`int(raw)` sem estourar `ValueError` -- mesma ideia de `parse_enum`,
    para ids vindos de form/querystring (client_id, case_id, etc.)."""
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _add_years(d: date, years: int) -> date:
    """d + N anos, tratando 29/fev em ano não-bissexto (cai pra 28/fev) --
    sem depender de python-dateutil, que não é dependência deste projeto."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


# --------------------------------------------------------------------------
# Campos calculados -- nunca gravados como coluna (ver docstring do módulo)
# --------------------------------------------------------------------------

def days_to_deadline(case: Case, *, today: date | None = None) -> int | None:
    if case.service_deadline is None:
        return None
    return (case.service_deadline - (today or _today())).days


def days_to_close(lead: Lead) -> int | None:
    if lead.first_contact_at is None or lead.closed_at is None:
        return None
    return (lead.closed_at - lead.first_contact_at).days


def processing_time_days(case: Case) -> int | None:
    """Dias entre o protocolo e a decisão -- só a aprovação é rastreada
    como data hoje (ver app/crm_models.py::Case, sem `decision_date`
    separado para indeferimento); None enquanto qualquer uma faltar."""
    if case.submission_date is None or case.approval_date is None:
        return None
    return (case.approval_date - case.submission_date).days


def citizenship_window(resident_since: date, years: int) -> dict[str, date]:
    """N-400 pode ser protocolado até 90 dias antes de completar `years`
    como residente permanente. `years` é 3 (cônjuge de cidadão americano)
    ou 5 (regra geral) -- a chamada decide qual regra aplicar, não é
    inferido aqui."""
    eligible_on = _add_years(resident_since, years)
    return {"eligible_on": eligible_on, "can_file_on": eligible_on - timedelta(days=90)}


def roc_window(gc_expiration: date) -> dict[str, date]:
    """Janela de 90 dias para peticionar a remoção de condições (I-751),
    terminando no vencimento do Green Card condicional."""
    return {"window_start": gc_expiration - timedelta(days=90), "window_end": gc_expiration}


def arrived_on_schedule(received_date: date | None, expected_delivery_date: date | None) -> bool | None:
    if received_date is None or expected_delivery_date is None:
        return None
    return received_date <= expected_delivery_date


def month_key(d: date) -> str:
    """Chave "YYYY-MM" p/ agrupar relatórios (equivalente ao `Month-Year`
    formula do Notion) -- calculada aqui, nunca guardada em coluna."""
    return f"{d.year:04d}-{d.month:02d}"


def group_payments_by_month(payments: list[PaymentLedgerEntry]) -> dict[str, list[PaymentLedgerEntry]]:
    """Agrupa por mês de `payment_date` (pagamentos sem data ainda, ex.
    `pending`, ficam de fora -- não têm mês de fato)."""
    dated = [p for p in payments if p.payment_date is not None]
    dated.sort(key=lambda p: p.payment_date)
    return {key: list(group) for key, group in groupby(dated, key=lambda p: month_key(p.payment_date))}


def service_installment_amount_cents(service: ServiceCatalog, installments: int) -> int | None:
    """Valor de cada parcela -- sempre calculado a partir de base_price_cents
    e do nº de parcelas (ver ServicePaymentPlan em crm_models.py), nunca
    guardado como texto canônico separado (era assim no Notion: "1x $2000"
    duplicava o próprio preço em outro formato)."""
    if service.base_price_cents is None or installments <= 0:
        return None
    return round(service.base_price_cents / installments)


def case_pending_documents(case: Case) -> list[Document]:
    """Documentos ainda não recebidos deste caso -- é o que alimenta tanto
    o painel "Meu Caso" do cliente quanto a lista de pendências do staff."""
    return [d for d in case.documents if d.received_at is None]


# --------------------------------------------------------------------------
# "Funções-botão" -- equivalentes aos botões do Notion (Confirm Case Status
# Check / Submit Application / Register Approval / Finish Review)
# --------------------------------------------------------------------------

def confirm_case_status_check(case: Case, *, today: date | None = None,
                               interval_days: int = DEFAULT_STATUS_CHECK_INTERVAL_DAYS) -> None:
    now = today or _today()
    case.last_checked_at = now
    case.next_check_at = now + timedelta(days=interval_days)


def submit_application(case: Case, *, submission_date: date | None = None) -> None:
    case.submission_date = submission_date or _today()
    case.process_status = ProcessStatus.submitted
    case.case_status = CaseStatus.submission


def register_approval(case: Case, *, approval_date: date | None = None) -> None:
    case.approval_date = approval_date or _today()
    case.case_status = CaseStatus.approved
    case.process_status = ProcessStatus.done


def finish_review(translation: DocumentTranslation) -> None:
    translation.status = TranslationStatus.ready


# --------------------------------------------------------------------------
# Conversão de Lead -> Client + Case (o "fechamento" do funil)
# --------------------------------------------------------------------------

def convert_lead_to_client_and_case(
    lead: Lead, *, service_mode: ServiceMode, case_title: str,
    user_id: int | None = None,
) -> tuple[Client, Case]:
    """Fecha o lead (`closed_at`/`stage`) e cria o Client + Case
    resultantes -- `user_id` é preenchido quando o cliente já tem (ou
    acabou de criar) uma conta de login no site; fica None para um
    cliente full_service ainda sem conta própria."""
    client = Client(
        user_id=user_id, full_name=lead.name, email=lead.contact_email,
        us_phone=lead.contact_phone, us_phone_has=bool(lead.contact_phone),
    )
    SessionLocal.add(client)
    SessionLocal.flush()  # precisa do client.id antes de criar o Case abaixo

    case = Case(
        client_id=client.id, lead_id=lead.id, title=case_title,
        service_mode=service_mode,
    )
    SessionLocal.add(case)

    lead.stage = LeadStage.closed_won
    lead.closed_at = lead.closed_at or _today()
    lead.converted_client_id = client.id

    return client, case
