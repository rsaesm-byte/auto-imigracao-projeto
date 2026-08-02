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

from app.crm_models import (Case, CaseContract, CaseStatus, CaseTrackedForm,
                             Client, ContractStatus, ContractTier, Currency,
                             Document, DocumentStatus, DocumentTranslation,
                             Lead, LeadStage, PaymentDirection,
                             PaymentLedgerEntry, PaymentStatus, ProcessStatus,
                             ServiceCatalog, ServiceMode, ServiceRole,
                             TranslationSpeedTier, Translator)
from app.db import SessionLocal
from app.models import User

DEFAULT_STATUS_CHECK_INTERVAL_DAYS = 14

# Preço por página cobrado do CLIENTE por tier de velocidade -- pedido do
# usuário 2026-08-02 (valores exatos: "$32 e fica pronto em 1 a [2] dias
# úteis ou $30 fica pronto em 3 a 4 dias úteis"). Vive aqui (lógica de
# negócio), não em app/crm_models.py, porque é preço/regra de produto, não
# vocabulário fechado -- pode mudar sem precisar de uma migração.
TRANSLATION_SPEED_PRICING: dict[TranslationSpeedTier, dict] = {
    TranslationSpeedTier.rush: {"price_per_page_cents": 3200, "turnaround_label": "1-2 business days"},
    TranslationSpeedTier.standard: {"price_per_page_cents": 3000, "turnaround_label": "3-4 business days"},
}

# "Próxima Checagem" para um formulário rastreado individualmente (Case
# Tracking, ver app/crm_models.py::CaseTrackedForm) -- sempre 7 dias a
# partir do momento em que o botão "Register check" é clicado, pedido
# explícito do usuário (2026-08-02), diferente do intervalo de 14 dias já
# usado por confirm_case_status_check() acima para o Case como um todo.
TRACKED_FORM_CHECK_INTERVAL_DAYS = 7


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def tracked_form_processing_time_days(tracked: CaseTrackedForm) -> int | None:
    """Dias entre o dia do recibo e o dia da aprovação, para um formulário
    individual rastreado em Case Tracking -- irmã de processing_time_days()
    acima (que usa submission_date/approval_date do Case como um todo);
    aqui é receipt_date/approval_date do próprio CaseTrackedForm, pedido
    explícito do usuário (2026-08-02: "formula que calcula o dia do
    recibo e o dia da aprovação")."""
    if tracked.receipt_date is None or tracked.approval_date is None:
        return None
    return (tracked.approval_date - tracked.receipt_date).days


def translation_client_price_per_page_cents(speed_tier: TranslationSpeedTier | None) -> int | None:
    if speed_tier is None:
        return None
    return TRANSLATION_SPEED_PRICING[speed_tier]["price_per_page_cents"]


def translation_client_total_cents(translation: DocumentTranslation) -> int | None:
    """O que o CLIENTE paga por esta tradução -- página × preço do tier de
    velocidade escolhido (nunca gravado como coluna, ver docstring de
    DocumentTranslation em app/crm_models.py)."""
    price = translation_client_price_per_page_cents(translation.speed_tier)
    if price is None or translation.page_count is None:
        return None
    return translation.page_count * price


def translation_payout_translator_currency_cents(translation: DocumentTranslation) -> int | None:
    """O que a Saes PAGA ao tradutor, na moeda dele -- página × preço por
    página combinado com esse tradutor (independente do que o cliente
    paga acima)."""
    if translation.page_count is None or translation.price_per_page_translator_currency_cents is None:
        return None
    return translation.page_count * translation.price_per_page_translator_currency_cents


def translation_payout_usd_cents(translation: DocumentTranslation) -> int | None:
    """Mesmo cálculo acima, mas convertido pro valor em dólar que o
    tradutor combinou (campo próprio, não uma taxa de câmbio calculada --
    o tradutor informa seu próprio preço por página em USD)."""
    if translation.page_count is None or translation.price_per_page_usd_cents is None:
        return None
    return translation.page_count * translation.price_per_page_usd_cents


def translations_this_month(translations: list[DocumentTranslation], *, today: date | None = None) -> list:
    today = today or _today()
    return [t for t in translations if t.requested_at and (t.requested_at.year, t.requested_at.month) == (today.year, today.month)]


def translations_last_30_days(translations: list[DocumentTranslation], *, today: date | None = None) -> list:
    today = today or _today()
    cutoff = today - timedelta(days=30)
    return [t for t in translations if t.requested_at and cutoff <= t.requested_at <= today]


def translations_previous_month(translations: list[DocumentTranslation], *, today: date | None = None) -> list:
    today = today or _today()
    last_of_prev_month = today.replace(day=1) - timedelta(days=1)
    return [t for t in translations
            if t.requested_at and (t.requested_at.year, t.requested_at.month) == (last_of_prev_month.year, last_of_prev_month.month)]


def group_translations_by_year_month(translations: list[DocumentTranslation]) -> dict[int, dict[int, list]]:
    """"Todas as traduções separadas (por mês e depois por ano)" -- pedido
    do usuário 2026-08-02. Traduções sem `requested_at` (nunca lançadas
    com data) ficam de fora, mesma convenção de group_payments_by_month()
    acima."""
    dated = [t for t in translations if t.requested_at is not None]
    dated.sort(key=lambda t: t.requested_at, reverse=True)
    grouped: dict[int, dict[int, list]] = {}
    for t in dated:
        grouped.setdefault(t.requested_at.year, {}).setdefault(t.requested_at.month, []).append(t)
    return grouped


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


def contract_price_cents(contract: CaseContract) -> int | None:
    """Preço cotado neste contrato -- resolvido a partir do serviço +
    tier no momento da leitura (nunca gravado, mesma convenção do resto
    do módulo), pra sempre refletir o preço ATUAL do sistema mesmo se o
    staff reajustar o preço depois de o contrato já existir (mas antes de
    ser assinado -- depois de assinado o valor real cobrado deve ser
    conferido no PaymentLedgerEntry vinculado, ver
    create_payment_request_for_contract abaixo, que registra o valor no
    momento da assinatura)."""
    if contract.service is None or contract.tier is None:
        return None
    return {
        ContractTier.standard: contract.service.base_price_cents,
        ContractTier.plus_online: contract.service.plus_price_cents,
        ContractTier.plus_paper: contract.service.plus_price_paper_cents,
    }.get(contract.tier)


def case_pending_documents(case: Case) -> list[Document]:
    """Documentos ainda não recebidos deste caso -- é o que alimenta tanto
    o painel "Meu Caso" do cliente quanto a lista de pendências do staff."""
    return [d for d in case.documents if d.received_at is None]


def apply_service_procedure_checklist(case: Case) -> None:
    """Popula automaticamente o checklist de documentos (`RequiredDocument`,
    app/models.py -- o mesmo que o cliente vê e usa para upload em
    /pendencias, ver app/onboarding.py) a partir do template de
    procedimento do serviço "Pacote Completo" atribuído ao caso (ver
    app/services/service_procedures.py) -- só os itens da Fase 1
    (documentos, não os passos internos). Pedido do usuário (2026-08-01):
    "gerar automaticamente a partir de um template por serviço".

    Só faz algo quando (a) o caso tem um `CaseService` atual ligado a um
    `ServiceCatalog` com `slug` preenchido, (b) o `Payment` (app/models.py)
    deste caso já está confirmado, e (c) o onboarding daquele pagamento
    ainda não tem nenhum `RequiredDocument` -- essa última checagem é a
    guarda de idempotência: nunca duplica nem sobrescreve um checklist que
    a equipe já editou manualmente. Chamada em dois pontos: depois de
    confirmar o pagamento (app/staff.py::confirm_payment) e depois de
    atribuir/trocar o serviço do caso (app/crm_staff_ops.py::
    case_service_update) -- cobre a ordem em que o staff decidir fazer as
    duas coisas. Segue a convenção do módulo (não commita sozinha)."""
    from app.models import Payment, PostPaymentOnboarding, RequiredDocument
    from app.services.service_procedures import phase1_documents

    current_service = next(
        (cs.service for cs in case.services if cs.role == ServiceRole.current and cs.service.slug),
        None)
    if current_service is None:
        return
    payment = SessionLocal.query(Payment).filter_by(case_id=case.id, status="confirmed").first()
    if payment is None:
        return
    onboarding = SessionLocal.query(PostPaymentOnboarding).filter_by(payment_id=payment.id).first()
    if onboarding is None or onboarding.documents:
        return
    for label in phase1_documents(current_service.slug):
        SessionLocal.add(RequiredDocument(onboarding_id=onboarding.id, label=label))


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


def register_tracked_form_check(tracked: CaseTrackedForm, *, now: datetime | None = None) -> None:
    """"Register check" button on a Case Tracking form card -- stamps the
    exact moment (date + time, so the UI can show it as month/day/year +
    AM/PM per the user's request) and schedules the next check exactly
    `TRACKED_FORM_CHECK_INTERVAL_DAYS` (7) days out."""
    ts = now or datetime.now(timezone.utc)
    tracked.last_checked_at = ts
    tracked.next_check_at = ts.date() + timedelta(days=TRACKED_FORM_CHECK_INTERVAL_DAYS)


def finish_review(translation: DocumentTranslation) -> None:
    """"Finish review" button (crm_documents.html) -- translation states
    now live on `Document.status` (unified vocabulary, see DocumentStatus
    in app/crm_models.py) instead of the old translation-only
    TranslationStatus, so this just marks the parent document completed."""
    translation.document.status = DocumentStatus.completed


def register_translator_payment(
    translator: Translator, *, amount_cents: int, currency, paid_at: date,
    document_translation_id: int | None = None, notes: str | None = None,
) -> "TranslatorPayment":
    from app.crm_models import TranslatorPayment
    payment = TranslatorPayment(
        translator_id=translator.id, document_translation_id=document_translation_id,
        amount_cents=amount_cents, currency=currency, paid_at=paid_at, notes=notes)
    SessionLocal.add(payment)
    return payment


def open_contract_for_review(contract: CaseContract) -> None:
    """Chamado sempre que o cliente ABRE a tela de assinatura -- só
    transiciona not_started -> in_review, nunca regride signed/rejected
    de volta (idempotente: abrir de novo um contrato já assinado não
    muda nada). Pedido do usuário 2026-08-02: "em análise (quando o
    cliente abriu mas não assinou)"."""
    if contract.status == ContractStatus.not_started:
        contract.status = ContractStatus.in_review
        contract.opened_at = _now()


def sign_contract(
    contract: CaseContract, *, signature_image_path: str, payment_method_id: int | None, signer_ip: str | None,
) -> None:
    """"Confirmar assinatura" -- pedido do usuário 2026-08-02. Também
    liga o flag legado correspondente em Case (contract_signed/
    terms_accepted, já existiam sem nenhuma tela que os usasse até
    agora)."""
    contract.status = ContractStatus.signed
    contract.signed_at = _now()
    contract.signature_image_path = signature_image_path
    contract.selected_payment_method_id = payment_method_id
    contract.signer_ip = signer_ip
    if contract.document_type.value == "service_contract":
        contract.case.contract_signed = True
    else:
        contract.case.terms_accepted = True


def reject_contract(contract: CaseContract, *, reason: str | None = None) -> None:
    contract.status = ContractStatus.rejected
    contract.rejected_at = _now()
    contract.rejected_reason = reason


def create_payment_request_for_contract(contract: CaseContract) -> PaymentLedgerEntry | None:
    """Depois que o cliente assina um contrato de serviço (não T&C),
    cria automaticamente a solicitação de pagamento correspondente --
    pedido do usuário 2026-08-02: "o sistema deverá enviar a solicitação
    de pagamento pra ele de acordo com o pacote e serviço escolhido".

    Vira um `PaymentLedgerEntry` (o ledger que a equipe já usa na aba
    "Payments (CRM)"), status `invoice_sent` (não `pending` -- o valor já
    foi formalmente comunicado ao cliente no momento da assinatura, não é
    só uma cobrança em aberto sem contexto) -- pagamento em si continua
    manual (Zelle/Venmo/wire, como os contratos reais descrevem), o staff
    confirma quando o cliente pagar. Nunca cria uma segunda solicitação
    pro mesmo contrato (idempotente via `payment_ledger_entry_id`)."""
    if contract.document_type.value != "service_contract" or contract.payment_ledger_entry_id is not None:
        return None
    price_cents = contract_price_cents(contract)
    if price_cents is None:
        return None

    method_label = f" via {contract.payment_method.name}" if contract.payment_method else ""
    entry = PaymentLedgerEntry(
        case_id=contract.case_id, client_id=contract.case.client_id,
        description=f"{contract.service.name} ({contract.tier.value.replace('_', ' ').title()}){method_label}",
        amount_cents=price_cents, currency=Currency.usd, direction=PaymentDirection.receivable,
        status=PaymentStatus.invoice_sent, payment_method_id=contract.selected_payment_method_id,
        invoice_date=_today(),
    )
    SessionLocal.add(entry)
    SessionLocal.flush()  # precisa do entry.id antes de linkar de volta no contrato
    contract.payment_ledger_entry_id = entry.id
    return entry


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


def get_or_create_case_for_payment(payment, *, case_title: str) -> Case:
    """Garante que todo pagamento confirmado tenha um Client+Case do CRM
    vinculado -- sem isso, o link "Meu Caso" do cliente (app/crm_client.py)
    nunca tem nada pra mostrar pra maioria dos clientes reais, já que hoje
    só a conversão de Lead (acima) e a atribuição manual de serviço
    (app/crm_staff_ops.py::case_service_update) criavam um Case; um
    cliente que só paga um formulário/pacote avulso nunca passava por
    nenhum dos dois. Pedido do usuário, 2026-08-02 ("criar Client+Case pra
    todo pagamento confirmado"). Reaproveita o Client existente por
    user_id (único, ver Client.user_id) quando já houver um -- quem chama
    (app/staff.py::confirm_payment) só invoca isto quando payment.case_id
    ainda é None, então o Case em si é sempre novo."""
    client = SessionLocal.query(Client).filter_by(user_id=payment.user_id).first()
    if client is None:
        user = SessionLocal.get(User, payment.user_id)
        client = Client(
            user_id=payment.user_id,
            full_name=payment.client_name or (user.email if user else "—"),
            email=payment.client_email or (user.email if user else None),
            us_phone=payment.client_phone, us_phone_has=bool(payment.client_phone),
        )
        SessionLocal.add(client)
        SessionLocal.flush()  # precisa do client.id antes de criar o Case abaixo

    case = Case(client_id=client.id, title=case_title, service_mode=ServiceMode.self_service)
    SessionLocal.add(case)
    SessionLocal.flush()  # quem chama precisa do case.id pra gravar em payment.case_id
    return case
