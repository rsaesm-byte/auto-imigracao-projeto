"""Gera dados FICTÍCIOS de demonstração no CRM (Fase 1 + Fase 2) para o
usuário testar as telas com conteúdo realista, sem mexer em nenhum dado
real do site.

Marcação para facilitar identificar/apagar depois: todo e-mail criado
aqui (clientes, financeiro, contas de login de demonstração) termina em
"@demo.example" -- nunca um domínio que colidiria com um cliente real.
Para apagar tudo de uma vez, ver a função `wipe_demo_data()` no final
deste arquivo (roda com `python scripts/seed_demo_crm_data.py --wipe`).

Rodar com: python scripts/seed_demo_crm_data.py
(da raiz do projeto, mesmo venv do site).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.security import generate_password_hash

from app import create_app
from app.db import SessionLocal
from app.models import User
from app.crm_models import (Case, CaseStatus, Client, ClientTier,
                             CloseLossReason, Communication, CommDirection,
                             CommStatus, ContactChannel, Currency, Document,
                             DocumentType, FieldOffice, Lead, LeadSource,
                             LeadStage, LeadQuality, PaymentDirection,
                             PaymentLedgerEntry, PaymentMethodLookup,
                             PaymentStatus, PreferredLanguage, Priority,
                             ProcessStatus, ServiceMode, Task, TaskStatus,
                             TaskType)
from app.crm_financial_models import (ClientComplianceLevel, CoachingSession,
                                       ContinuityProgram, EmergencyFundStatus,
                                       FinancialChallenge, FinancialClient,
                                       FinancialClientChallenge,
                                       FinancialClientGoal,
                                       FinancialClientIncomeSource,
                                       FinancialClientMeetingPlatform,
                                       FinancialClientStatus, FinancialGoal,
                                       FinancialProgressStatus, FinancialTask,
                                       FinancialTaskCategory,
                                       HomeworkAdherenceLevel,
                                       HouseholdIncomeRange, MeetingPlatform,
                                       NinetyDayReviewStatus, ProgramType,
                                       SessionType, TaskDifficulty,
                                       TaskResponsibleParty)
from app.crm_models import IncomeSourceType

DEMO_DOMAIN = "@demo.example"
DEMO_PASSWORD = "demo12345"


def _by_name(model, name):
    row = SessionLocal.query(model).filter_by(name=name).first()
    if row is None:
        raise RuntimeError(f"lookup {model.__name__} nao tem '{name}' -- rode a seed normal do app primeiro")
    return row.id


def _dt(days_ago: int, hour: int = 10) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0)


def _d(days_ago: int) -> date:
    return date.today() - timedelta(days=days_ago)


def seed() -> None:
    app = create_app()
    with app.app_context():
        _seed_immigration()
        _seed_financial()
        SessionLocal.commit()
        _print_summary()


def _seed_immigration() -> None:
    referral_id = _by_name(LeadSource, "Referral")
    google_ads_id = _by_name(LeadSource, "Google Ads")
    instagram_id = _by_name(LeadSource, "Instagram")
    too_expensive_id = _by_name(CloseLossReason, "Too Expensive")
    credit_card_id = _by_name(PaymentMethodLookup, "Credit Card")
    zelle_id = _by_name(PaymentMethodLookup, "Zelle")
    whatsapp_channel_id = _by_name(ContactChannel, "WhatsApp")
    email_channel_id = _by_name(ContactChannel, "Email")
    nbc_office_id = _by_name(FieldOffice, "USCIS National Benefits Center")

    staff = SessionLocal.query(User).filter_by(is_staff=True).order_by(User.id).first()
    responsible_id = staff.id if staff else None

    # --- Leads (funil, ainda não viraram cliente) ---------------------
    leads = [
        Lead(name="Vanessa Rodrigues", stage=LeadStage.new, quality=LeadQuality.hot,
             lead_source_id=instagram_id, contact_email=f"vanessa.rodrigues{DEMO_DOMAIN}",
             contact_phone="+1 617 555 0110", deal_value_cents=180000, first_contact_at=_d(2)),
        Lead(name="Thiago Mendes", stage=LeadStage.contacted, quality=LeadQuality.warm,
             lead_source_id=google_ads_id, contact_email=f"thiago.mendes{DEMO_DOMAIN}",
             contact_phone="+1 508 555 0142", deal_value_cents=95000, first_contact_at=_d(5)),
        Lead(name="Camila Barros", stage=LeadStage.proposal_sent, quality=LeadQuality.hot,
             lead_source_id=referral_id, contact_email=f"camila.barros{DEMO_DOMAIN}",
             contact_phone="+1 774 555 0198", deal_value_cents=220000,
             first_contact_at=_d(10), proposal_at=_d(6)),
        Lead(name="Diego Farias", stage=LeadStage.negotiation, quality=LeadQuality.warm,
             lead_source_id=google_ads_id, contact_email=f"diego.farias{DEMO_DOMAIN}",
             contact_phone="+1 401 555 0177", deal_value_cents=150000,
             first_contact_at=_d(14), proposal_at=_d(8)),
        Lead(name="Larissa Nunes", stage=LeadStage.closed_lost, quality=LeadQuality.cold,
             lead_source_id=instagram_id, contact_email=f"larissa.nunes{DEMO_DOMAIN}",
             contact_phone="+1 857 555 0163", deal_value_cents=80000, first_contact_at=_d(30),
             closed_at=_d(20), close_loss_reason_id=too_expensive_id),
    ]
    SessionLocal.add_all(leads)
    SessionLocal.flush()

    # --- Clientes + casos em estágios variados -------------------------
    clients_data = [
        dict(full_name="Maria Silva", email=f"maria.silva{DEMO_DOMAIN}", tier=ClientTier.a,
             country_of_origin="Brasil", preferred_language=PreferredLanguage.pt,
             case_title="I-485 — Ajuste de Status", service_mode=ServiceMode.full_service,
             case_status=CaseStatus.document_collection, process_status=ProcessStatus.documents,
             priority=Priority.high, service_deadline=_d(-45), contract_signed=True, terms_accepted=True),
        dict(full_name="João Santos", email=f"joao.santos{DEMO_DOMAIN}", tier=ClientTier.b,
             country_of_origin="Brasil", preferred_language=PreferredLanguage.pt,
             case_title="N-400 — Naturalização", service_mode=ServiceMode.self_service,
             case_status=CaseStatus.submission, process_status=ProcessStatus.submitted,
             priority=Priority.medium, receipt_number="MSC2190012345", receipt_date=_d(20),
             submission_date=_d(25)),
        dict(full_name="Ana Costa", email=f"ana.costa{DEMO_DOMAIN}", tier=ClientTier.a,
             country_of_origin="Brasil", preferred_language=PreferredLanguage.en,
             case_title="I-130 — Petição Familiar", service_mode=ServiceMode.full_service,
             case_status=CaseStatus.preparation, process_status=ProcessStatus.preparation,
             priority=Priority.urgent, service_deadline=_d(-10), contract_signed=True),
        dict(full_name="Carlos Oliveira", email=f"carlos.oliveira{DEMO_DOMAIN}", tier=ClientTier.c,
             country_of_origin="Brasil", preferred_language=PreferredLanguage.pt,
             case_title="I-751 — Remoção de Condições", service_mode=ServiceMode.full_service,
             case_status=CaseStatus.approved, process_status=ProcessStatus.done,
             priority=Priority.low, approval_date=_d(3), submission_date=_d(200),
             receipt_number="MSC2180099887", contract_signed=True),
        dict(full_name="Patrícia Souza", email=f"patricia.souza{DEMO_DOMAIN}", tier=ClientTier.b,
             country_of_origin="Brasil", preferred_language=PreferredLanguage.es,
             case_title="I-539 — Extensão de Status (B2)", service_mode=ServiceMode.self_service,
             case_status=CaseStatus.follow_up, process_status=ProcessStatus.post_submission,
             priority=Priority.medium, submission_date=_d(40), receipt_number="EAC2177001122"),
        dict(full_name="Roberto Lima", email=f"roberto.lima{DEMO_DOMAIN}", tier=ClientTier.d,
             country_of_origin="Brasil", preferred_language=PreferredLanguage.pt,
             case_title="I-90 — Substituição de Green Card", service_mode=ServiceMode.full_service,
             case_status=CaseStatus.onboarding, process_status=ProcessStatus.intake,
             priority=Priority.medium),
    ]

    clients_by_name: dict[str, Client] = {}
    for data in clients_data:
        client = Client(
            full_name=data["full_name"], email=data["email"], tier=data["tier"],
            country_of_origin=data["country_of_origin"], preferred_language=data["preferred_language"],
            us_phone="+1 617 555 0100", us_phone_has=True)
        SessionLocal.add(client)
        SessionLocal.flush()
        clients_by_name[data["full_name"]] = client

        case = Case(
            client_id=client.id, title=data["case_title"], service_mode=data["service_mode"],
            case_status=data["case_status"], process_status=data["process_status"],
            priority=data["priority"], responsible_id=responsible_id, field_office_id=nbc_office_id,
            service_deadline=data.get("service_deadline"), receipt_number=data.get("receipt_number"),
            receipt_date=data.get("receipt_date"), submission_date=data.get("submission_date"),
            approval_date=data.get("approval_date"), contract_signed=data.get("contract_signed", False),
            terms_accepted=data.get("terms_accepted", False))
        SessionLocal.add(case)
        SessionLocal.flush()
        data["_case"] = case

    maria_case = clients_by_name["Maria Silva"].cases[0]
    ana_case = clients_by_name["Ana Costa"].cases[0]
    carlos_case = clients_by_name["Carlos Oliveira"].cases[0]

    # --- Documentos ------------------------------------------------
    SessionLocal.add_all([
        Document(case_id=maria_case.id, client_id=maria_case.client_id, name="Passaporte",
                 document_type=DocumentType.passport, progress=10, requested_at=_d(50), received_at=_d(48)),
        Document(case_id=maria_case.id, client_id=maria_case.client_id, name="Certidão de Nascimento",
                 document_type=DocumentType.birth_certificate, progress=6, requested_at=_d(50)),
        Document(case_id=maria_case.id, client_id=maria_case.client_id, name="Extrato Bancário",
                 document_type=DocumentType.bank_statement, progress=0, requested_at=_d(3)),
        Document(case_id=carlos_case.id, client_id=carlos_case.client_id, name="Contrato de Serviço",
                 document_type=DocumentType.service_contract, progress=10, requested_at=_d(200), received_at=_d(199)),
    ])

    # --- Pagamentos (ledger) -----------------------------------------
    SessionLocal.add_all([
        PaymentLedgerEntry(client_id=maria_case.client_id, case_id=maria_case.id,
                            description="Honorários Saes — I-485", amount_cents=250000,
                            currency=Currency.usd, direction=PaymentDirection.receivable,
                            status=PaymentStatus.partially_paid, payment_method_id=credit_card_id,
                            payment_date=_d(40)),
        PaymentLedgerEntry(client_id=maria_case.client_id, case_id=maria_case.id,
                            description="Taxa USCIS I-485", amount_cents=144000,
                            currency=Currency.usd, direction=PaymentDirection.receivable,
                            status=PaymentStatus.pending, due_date=_d(-5)),
        PaymentLedgerEntry(client_id=carlos_case.client_id, case_id=carlos_case.id,
                            description="Honorários Saes — I-751", amount_cents=180000,
                            currency=Currency.usd, direction=PaymentDirection.receivable,
                            status=PaymentStatus.paid, payment_method_id=zelle_id, payment_date=_d(195)),
        PaymentLedgerEntry(client_id=ana_case.client_id, case_id=ana_case.id,
                            description="Tradução certificada — certidão de casamento",
                            amount_cents=8000, currency=Currency.usd,
                            direction=PaymentDirection.payable, status=PaymentStatus.paid,
                            payment_date=_d(12)),
    ])

    # --- Comunicações --------------------------------------------------
    SessionLocal.add_all([
        Communication(client_id=maria_case.client_id, case_id=maria_case.id,
                       subject="Follow-up documentos pendentes", occurred_at=_dt(3),
                       direction=CommDirection.outbound, channel_id=whatsapp_channel_id,
                       status=CommStatus.done, next_followup_at=_d(-4),
                       summary="Pedimos o extrato bancário atualizado."),
        Communication(client_id=ana_case.client_id, case_id=ana_case.id,
                       subject="Confirmação de recebimento da petição", occurred_at=_dt(9),
                       direction=CommDirection.inbound, channel_id=email_channel_id,
                       status=CommStatus.done, summary="Cliente confirmou recebimento do rascunho da I-130."),
    ])

    # --- Tarefas internas ------------------------------------------
    SessionLocal.add_all([
        Task(case_id=maria_case.id, title="Revisar documentos recebidos", status=TaskStatus.in_progress,
             priority=Priority.high, task_type=TaskType.documents_review, responsible_id=responsible_id,
             due_date=_d(-2)),
        Task(case_id=ana_case.id, title="Reunião de preparação da petição", status=TaskStatus.not_started,
             priority=Priority.urgent, task_type=TaskType.meeting_client, responsible_id=responsible_id,
             meeting_date=_dt(-3)),
        Task(case_id=None, title="Revisar tradução certificada da certidão", status=TaskStatus.done,
             priority=Priority.medium, task_type=TaskType.translation_review, responsible_id=responsible_id,
             completed_at=_dt(11)),
    ])

    # --- 1 conta de cliente com login, pra testar o painel "Meu Caso" ---
    demo_user = User(email=f"demo.cliente{DEMO_DOMAIN}",
                      password_hash=generate_password_hash(DEMO_PASSWORD))
    SessionLocal.add(demo_user)
    SessionLocal.flush()
    clients_by_name["Maria Silva"].user_id = demo_user.id


def _seed_financial() -> None:
    referral_id = _by_name(LeadSource, "Referral")
    web_search_id = _by_name(LeadSource, "Web Search")
    financial_course_id = _by_name(LeadSource, "Financial Course")

    goal_ids = {name: _by_name(FinancialGoal, name) for name in
                ("Build Emergency Fund", "Pay Off Debt", "Build Wealth", "Save for College")}
    challenge_ids = {name: _by_name(FinancialChallenge, name) for name in
                      ("Overspending", "No Emergency Fund", "Poor Money Management")}
    income_source_ids = {name: _by_name(IncomeSourceType, name) for name in
                          ("Employee (Full-Time)", "Own Business")}
    category_ids = {name: _by_name(FinancialTaskCategory, name) for name in
                     ("Budgeting", "Savings", "Debt Reduction")}

    coach = SessionLocal.query(User).filter_by(is_staff=True).order_by(User.id).first()
    coach_id = coach.id if coach else None

    # --- Fernanda: cliente ativa, no meio do programa -------------------
    fernanda = FinancialClient(
        full_name="Fernanda Almeida", email=f"fernanda.almeida{DEMO_DOMAIN}",
        phone_number="+1 617 555 0201", preferred_language=PreferredLanguage.pt,
        client_status=FinancialClientStatus.active_6_sessions,
        lead_source_id=referral_id, first_contact_at=_d(60), proposal_at=_d(55), closed_at=_d(50),
        program_type=ProgramType.financial_coaching, enrollment_at=_d(50), diagnostic_at=_d(48),
        total_sessions_purchased=6, progress_status=FinancialProgressStatus.on_track,
        homework_adherence=HomeworkAdherenceLevel.high, client_compliance=ClientComplianceLevel.good,
        continuity_program=ContinuityProgram.none, nps_score=9, priority_level=Priority.medium,
        household_income_range=HouseholdIncomeRange.from_5001_10000,
        monthly_household_income_cents=750000, monthly_expenses_cents=680000,
        emergency_fund_status=EmergencyFundStatus.less_1_month, credit_score=650,
        total_assets_cents=1500000, total_liabilities_cents=900000,
        package_value_cents=180000)
    SessionLocal.add(fernanda)
    SessionLocal.flush()
    SessionLocal.add_all([
        FinancialClientMeetingPlatform(financial_client_id=fernanda.id, platform=MeetingPlatform.zoom),
        FinancialClientGoal(financial_client_id=fernanda.id, financial_goal_id=goal_ids["Build Emergency Fund"]),
        FinancialClientGoal(financial_client_id=fernanda.id, financial_goal_id=goal_ids["Pay Off Debt"]),
        FinancialClientChallenge(financial_client_id=fernanda.id,
                                  financial_challenge_id=challenge_ids["Overspending"]),
        FinancialClientIncomeSource(financial_client_id=fernanda.id,
                                     income_source_type_id=income_source_ids["Employee (Full-Time)"]),
    ])
    fernanda_sessions = [
        CoachingSession(financial_client_id=fernanda.id, session_number=1,
                         session_type=SessionType.discovery_consultation, completed=True,
                         coach_id=coach_id, session_date=_dt(48)),
        CoachingSession(financial_client_id=fernanda.id, session_number=2,
                         session_type=SessionType.financial_assessment, completed=True,
                         coach_id=coach_id, session_date=_dt(34)),
        CoachingSession(financial_client_id=fernanda.id, session_number=3,
                         session_type=SessionType.goal_setting, main_topic="Fundo de emergência",
                         completed=True, coach_id=coach_id, session_date=_dt(20)),
        CoachingSession(financial_client_id=fernanda.id, session_number=4,
                         session_type=SessionType.cash_flow_review, completed=False,
                         coach_id=coach_id, session_date=_dt(-6)),
    ]
    SessionLocal.add_all(fernanda_sessions)
    SessionLocal.flush()
    SessionLocal.add_all([
        FinancialTask(financial_client_id=fernanda.id, coaching_session_id=fernanda_sessions[2].id,
                      task_name="Abrir conta poupança separada", status=TaskStatus.done,
                      category_id=category_ids["Savings"], priority=Priority.high,
                      difficulty=TaskDifficulty.easy, responsible_party=TaskResponsibleParty.client,
                      completed_at=_d(18)),
        FinancialTask(financial_client_id=fernanda.id, coaching_session_id=fernanda_sessions[2].id,
                      task_name="Registrar gastos por 2 semanas", status=TaskStatus.in_progress,
                      category_id=category_ids["Budgeting"], priority=Priority.medium,
                      difficulty=TaskDifficulty.medium, responsible_party=TaskResponsibleParty.client,
                      due_date=_d(-3)),
    ])
    SessionLocal.add(PaymentLedgerEntry(
        financial_client_id=fernanda.id, description="Pacote 6 sessões — Fernanda Almeida",
        amount_cents=90000, currency=Currency.usd, direction=PaymentDirection.receivable,
        status=PaymentStatus.paid, payment_date=_d(50)))

    demo_financial_user = User(email=f"demo.coaching{DEMO_DOMAIN}",
                                password_hash=generate_password_hash(DEMO_PASSWORD))
    SessionLocal.add(demo_financial_user)
    SessionLocal.flush()
    fernanda.user_id = demo_financial_user.id

    # --- Ricardo: lead novo, ainda sem programa ------------------------
    SessionLocal.add(FinancialClient(
        full_name="Ricardo Pereira", email=f"ricardo.pereira{DEMO_DOMAIN}",
        phone_number="+1 508 555 0212", client_status=FinancialClientStatus.new_lead,
        lead_source_id=web_search_id, first_contact_at=_d(2)))

    # --- Bruno: proposta enviada ----------------------------------------
    SessionLocal.add(FinancialClient(
        full_name="Bruno Ferreira", email=f"bruno.ferreira{DEMO_DOMAIN}",
        phone_number="+1 774 555 0223", client_status=FinancialClientStatus.proposal_sent,
        lead_source_id=financial_course_id, first_contact_at=_d(12), proposal_at=_d(5),
        program_type=ProgramType.debt_elimination))

    # --- Camila: recém-matriculada --------------------------------------
    camila = FinancialClient(
        full_name="Camila Dias", email=f"camila.dias{DEMO_DOMAIN}",
        phone_number="+1 401 555 0234", client_status=FinancialClientStatus.onboarding,
        lead_source_id=referral_id, first_contact_at=_d(15), proposal_at=_d(10), closed_at=_d(3),
        program_type=ProgramType.budget_planning, enrollment_at=_d(3), total_sessions_purchased=6,
        progress_status=FinancialProgressStatus.not_started, package_value_cents=180000)
    SessionLocal.add(camila)
    SessionLocal.flush()
    SessionLocal.add(CoachingSession(
        financial_client_id=camila.id, session_number=1, session_type=SessionType.discovery_consultation,
        completed=False, coach_id=coach_id, session_date=_dt(-2)))

    # --- Juliana: programa concluído, com continuidade -----------------
    juliana = FinancialClient(
        full_name="Juliana Rocha", email=f"juliana.rocha{DEMO_DOMAIN}",
        phone_number="+1 857 555 0245", client_status=FinancialClientStatus.completed_program,
        lead_source_id=referral_id, first_contact_at=_d(220), proposal_at=_d(215), closed_at=_d(210),
        program_type=ProgramType.financial_coaching, enrollment_at=_d(210), diagnostic_at=_d(208),
        total_sessions_purchased=6, progress_status=FinancialProgressStatus.completed,
        homework_adherence=HomeworkAdherenceLevel.high, client_compliance=ClientComplianceLevel.excellent,
        review_90day_status=NinetyDayReviewStatus.done, continuity_program=ContinuityProgram.maintenance_quarterly,
        nps_score=10, package_value_cents=180000)
    SessionLocal.add(juliana)
    SessionLocal.flush()
    SessionLocal.add(PaymentLedgerEntry(
        financial_client_id=juliana.id, description="Pacote 6 sessões — Juliana Rocha",
        amount_cents=180000, currency=Currency.usd, direction=PaymentDirection.receivable,
        status=PaymentStatus.paid, payment_date=_d(212)))


DEMO_EMAIL_SUFFIX = DEMO_DOMAIN


def wipe_demo_data() -> None:
    """Apaga TUDO criado por seed() -- identificado só pelo domínio de
    e-mail @demo.example, em ordem segura de FK. Seguro rodar mesmo se
    seed() nunca rodou (não acha nada, não faz nada)."""
    app = create_app()
    with app.app_context():
        client_ids = [c.id for c in SessionLocal.query(Client.id)
                      .filter(Client.email.like(f"%{DEMO_EMAIL_SUFFIX}")).all()]
        fc_ids = [c.id for c in SessionLocal.query(FinancialClient.id)
                  .filter(FinancialClient.email.like(f"%{DEMO_EMAIL_SUFFIX}")).all()]
        lead_ids = [l.id for l in SessionLocal.query(Lead.id)
                    .filter(Lead.contact_email.like(f"%{DEMO_EMAIL_SUFFIX}")).all()]
        case_ids = [c.id for c in SessionLocal.query(Case.id)
                    .filter(Case.client_id.in_(client_ids or [0])).all()]
        user_ids = [u.id for u in SessionLocal.query(User.id)
                    .filter(User.email.like(f"%{DEMO_EMAIL_SUFFIX}")).all()]

        SessionLocal.query(PaymentLedgerEntry).filter(
            PaymentLedgerEntry.client_id.in_(client_ids or [0])
            | PaymentLedgerEntry.financial_client_id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(Document).filter(Document.client_id.in_(client_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(Communication).filter(Communication.client_id.in_(client_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(Task).filter(Task.case_id.in_(case_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(FinancialTask).filter(FinancialTask.financial_client_id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(CoachingSession).filter(CoachingSession.financial_client_id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(FinancialClientMeetingPlatform).filter(FinancialClientMeetingPlatform.financial_client_id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(FinancialClientIncomeSource).filter(FinancialClientIncomeSource.financial_client_id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(FinancialClientGoal).filter(FinancialClientGoal.financial_client_id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(FinancialClientChallenge).filter(FinancialClientChallenge.financial_client_id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(Case).filter(Case.id.in_(case_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(Lead).filter(Lead.id.in_(lead_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(FinancialClient).filter(FinancialClient.id.in_(fc_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(Client).filter(Client.id.in_(client_ids or [0])).delete(synchronize_session=False)
        SessionLocal.query(User).filter(User.id.in_(user_ids or [0])).delete(synchronize_session=False)
        SessionLocal.commit()
        print(f"Removidos: {len(client_ids)} clientes, {len(fc_ids)} clientes de coaching, "
              f"{len(lead_ids)} leads, {len(case_ids)} casos, {len(user_ids)} contas de login.")


def _print_summary() -> None:
    print("=" * 70)
    print("Dados de demonstração criados com sucesso.")
    print("=" * 70)
    print("Login de teste (aba Cliente):")
    print(f"  Cliente imigração (Maria Silva):  demo.cliente{DEMO_DOMAIN} / {DEMO_PASSWORD}")
    print(f"  Cliente coaching (Fernanda Almeida): demo.coaching{DEMO_DOMAIN} / {DEMO_PASSWORD}")
    print()
    print("No painel staff: /staff/crm/casos, /staff/crm/leads, /staff/crm/clientes,")
    print("/staff/crm/financeiro/ -- todos já têm conteúdo pra navegar.")
    print()
    print("Para apagar tudo depois: python scripts/seed_demo_crm_data.py --wipe")


if __name__ == "__main__":
    if "--wipe" in sys.argv:
        wipe_demo_data()
    else:
        seed()
