"""Importa o CRM legado do Notion (export tratado) para o banco real.

Escopo (pedido do usuário 2026-08-03): Clientes (já deduplicados),
Pagamentos, Casos (Dashboard) e Casos finalizados (Submitted). Reaproveita
o mesmo padrão de sessão/engine de scripts/seed_demo_crm_data.py.

Fonte: data/notion_migration/saes_notion_export_CLEAN.json
(ver data/notion_migration/MIGRACAO_README.md para o schema do export).

Idempotência: cada linha importada guarda o `notion_page_id` de origem numa
coluna nova (nullable + índice único), adicionada automaticamente no commit.
Rodar 2x faz UPSERT, nunca duplica.

Uso:
    python scripts/import_notion_crm.py                 # DRY-RUN (não grava nada)
    python scripts/import_notion_crm.py --commit        # grava (faz backup antes)
    python scripts/import_notion_crm.py --limit 50      # testar com subconjunto

DRY-RUN não precisa de Flask nem de CRM_CREDENTIALS_KEY. O --commit precisa da
chave (.env) para criptografar credenciais, exatamente como o resto do app.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.orm import scoped_session, sessionmaker  # noqa: E402

from app.db import Base  # noqa: E402  (metadata compartilhada)
import app.models  # noqa: E402,F401  (registra tabela users e demais FKs)
import app.crm_financial_models  # noqa: E402,F401  (registra crm_financial_clients)

# Caminho do banco: por padrão o instance/app.db do projeto, mas
# sobrescrevível por IMPORT_DB_PATH -- necessário porque o SQLite não
# consegue fazer lock in-place em alguns mounts (roda numa cópia local e
# depois copia o arquivo de volta).
_DB_PATH = os.environ.get("IMPORT_DB_PATH") or str(ROOT / "instance" / "app.db")
engine = create_engine(f"sqlite:///{_DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _fk_on(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
from app.crm_models import (  # noqa: E402
    Case, CaseStatus, CaseStepLog, Client, ClientCredential, ClientDependent,
    ClientIntake, ClientTier, CredentialService, Currency, FieldOffice,
    LeadSource, MaritalStatus, PaymentDirection, PaymentLedgerEntry,
    PaymentMethodLookup, PaymentStatus, PreferredLanguage, Priority,
    ProcessStatus, ServiceMode, BestContactPeriod, MonthlyIncomeRange,
)

DEFAULT_JSON = ROOT / "data" / "notion_migration" / "saes_notion_export_CLEAN.json"

# ---------------------------------------------------------------------------
# Mapas de enum (valor do Notion -> enum do schema real)
# ---------------------------------------------------------------------------
CASE_STATUS = {
    "Lead Capture & Qualification": CaseStatus.lead_capture,
    "Conversion & Onboarding": CaseStatus.onboarding,
    "Document Collection & Review": CaseStatus.document_collection,
    "Process Development & Preparation": CaseStatus.preparation,
    "Submission": CaseStatus.submission,
    "Follow-up": CaseStatus.follow_up,
    "Approved": CaseStatus.approved,
    "Denied": CaseStatus.denied,
    "Gave Up": CaseStatus.gave_up,
    "Lost Leads": CaseStatus.lost,
}
PROCESS_STATUS = {
    "Intake": ProcessStatus.intake,
    "Documents": ProcessStatus.documents,
    "Preparation": ProcessStatus.preparation,
    "Form Preparation": ProcessStatus.preparation,
    "Review": ProcessStatus.review,
    "Final Review & Package Assembly": ProcessStatus.review,
    "Ready to Submit": ProcessStatus.ready_to_submit,
    "Ready for Submission": ProcessStatus.ready_to_submit,
    "Submitted": ProcessStatus.submitted,
    "Post Submission  Monitoring": ProcessStatus.post_submission,
    "Post Submission Monitoring": ProcessStatus.post_submission,
    "RFE Handling": ProcessStatus.rfe_handling,
    "Decision & Closing": ProcessStatus.decision,
    "Done": ProcessStatus.done,
    "Internal Print Request": ProcessStatus.preparation,
    "In progress": ProcessStatus.preparation,
}
PRIORITY = {"Low": Priority.low, "Medium": Priority.medium,
            "High": Priority.high, "Urgent": Priority.urgent}
PAY_STATUS = {
    "Pending": PaymentStatus.pending, "Invoice Sent": PaymentStatus.invoice_sent,
    "Partially Paid": PaymentStatus.partially_paid, "In Dispute": PaymentStatus.in_dispute,
    "Paid": PaymentStatus.paid, "Refunded": PaymentStatus.refunded,
    "Written Off": PaymentStatus.written_off,
}
PAY_DIRECTION = {"Receivables": PaymentDirection.receivable,
                 "Payables": PaymentDirection.payable}
CURRENCY = {"USD": Currency.usd, "BRL": Currency.brl, "Other": Currency.other}
PREF_LANG = {"Portuguese": PreferredLanguage.pt, "PT": PreferredLanguage.pt,
             "English": PreferredLanguage.en, "ENG": PreferredLanguage.en,
             "Spanish": PreferredLanguage.es, "SPA": PreferredLanguage.es}
MARITAL = {"Single": MaritalStatus.single, "Married": MaritalStatus.married,
           "Divorced": MaritalStatus.divorced, "Widowed": MaritalStatus.widowed}
TIER = {f"Tier {x}": getattr(ClientTier, x.lower()) for x in "ABCDE"}
TIER.update({x: getattr(ClientTier, x.lower()) for x in "ABCDE"})
INCOME_RANGE = {
    "Menos do que 5 mil mensais": MonthlyIncomeRange.under_5k,
    "Entre 5 mil e 10 mil mensais": MonthlyIncomeRange.from_5k_10k,
    "Entre 10 mil e 15mil mensais": MonthlyIncomeRange.from_10k_15k,
    "Mais do que 15 mil mensais": MonthlyIncomeRange.over_15k,
}

# Serviço/tipo do Notion -> formulário USCIS (para relatório; a criação de
# crm_case_tracked_forms fica como passo posterior, fora do escopo pedido).
FORM_BY_KEYWORD = [
    ("removal of conditions", "I-751"), ("roc", "I-751"),
    ("citizenship", "N-400"), ("naturaliz", "N-400"),
    ("aos", "I-485"), ("adjust", "I-485"),
    ("consular", "I-130"), ("i-130", "I-130"), ("petição familiar", "I-130"),
    ("k1", "I-129F"), ("k-1", "I-129F"), ("fiancé", "I-129F"), ("fiance", "I-129F"),
    ("i-765", "I-765"), ("work authorization", "I-765"), ("ead", "I-765"),
    ("travel document", "I-131"), ("advance parole", "I-131"),
    ("cos", "I-539"), ("change of status", "I-539"), ("eos", "I-539"),
    ("extension", "I-539"), ("i-539", "I-539"),
]


class Stats:
    def __init__(self):
        self.counts = {}
        self.warnings = []
        self.forms_derived = {}
        self.forms_a_cadastrar = set()

    def inc(self, k, n=1):
        self.counts[k] = self.counts.get(k, 0) + n

    def warn(self, msg):
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def g(rec, key, default=None):
    v = rec.get(key, default)
    if isinstance(v, str) and v.strip() == "":
        return default
    return v


def parse_date(v):
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("start")
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            return None


def to_cents(v):
    if v is None:
        return None
    try:
        return round(float(v) * 100)
    except (TypeError, ValueError):
        return None


def enum_map(mapping, value, stats, label):
    if value is None:
        return None
    hit = mapping.get(value)
    if hit is None:
        stats.warn(f"{label}: valor sem mapeamento -> {value!r} (deixado nulo)")
    return hit


def best_contact_period(value, stats):
    if not value:
        return None
    low = value.lower()
    if "manhã" in low or "manha" in low or "am" in low.split():
        return BestContactPeriod.manha
    if "tarde" in low:
        return BestContactPeriod.tarde
    if "noite" in low or "após" in low or "pm" in low:
        return BestContactPeriod.noite
    return None


def derive_form(*texts):
    blob = " ".join(t for t in texts if t).lower()
    for kw, form in FORM_BY_KEYWORD:
        if kw in blob:
            return form
    return None


# ---------------------------------------------------------------------------
# Lookups (cache por nome; resolve-or-none, nunca cria)
# ---------------------------------------------------------------------------
class Lookups:
    def __init__(self, sess):
        self.sess = sess
        self._cache = {}

    def _all(self, model):
        if model not in self._cache:
            self._cache[model] = {r.name.strip().lower(): r.id
                                  for r in self.sess.query(model).all()}
        return self._cache[model]

    def payment_method(self, name):
        if not name:
            return None
        return self._all(PaymentMethodLookup).get(name.strip().lower())

    def lead_source(self, name):
        if not name:
            return None
        return self._all(LeadSource).get(name.strip().lower())

    def field_office(self, notion_value):
        if not notion_value:
            return None
        low = notion_value.lower()
        table = self._all(FieldOffice)
        if "texas" in low or "scops" in low or "irving" in low:
            return table.get("scops texas facility")
        if "national benefits" in low or "lee" in low or "missouri" in low or "mo " in low:
            return table.get("uscis national benefits center")
        return None


# ---------------------------------------------------------------------------
# Idempotência: coluna notion_page_id
# ---------------------------------------------------------------------------
TARGET_TABLES = ["crm_clients", "crm_cases", "crm_payments_ledger"]


def has_notion_col(conn, table):
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == "notion_page_id" for r in rows)


def ensure_notion_columns(conn):
    for t in TARGET_TABLES:
        if not has_notion_col(conn, t):
            conn.execute(text(f"ALTER TABLE {t} ADD COLUMN notion_page_id VARCHAR"))
            conn.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{t}_notion_page_id "
                f"ON {t}(notion_page_id)"))


def existing_by_notion(conn, table):
    if not has_notion_col(conn, table):
        return {}
    rows = conn.execute(text(
        f"SELECT notion_page_id, id FROM {table} WHERE notion_page_id IS NOT NULL")).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Importação
# ---------------------------------------------------------------------------
def uuid_from(value):
    """Extrai o UUID (32 hex, com ou sem hífens) de uma URL do Notion ou
    devolve o próprio valor se já for um id."""
    if not value:
        return None
    import re
    m = re.search(r"([0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12})",
                  str(value))
    if not m:
        return None
    raw = m.group(1).replace("-", "")
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def build_alias_map(data):
    """removido -> mantido, a partir do client_deduplication_log, para religar
    casos/pagamentos que apontam para um cliente duplicado que foi descartado."""
    alias = {}
    for e in data.get("client_deduplication_log", []):
        removed = uuid_from(e.get("removed_url_from_export"))
        kept = uuid_from(e.get("kept_url"))
        if removed and kept:
            alias[removed] = kept
    return alias


def run(data, commit, limit, stats):
    sess = SessionLocal
    conn = sess.connection()
    lk = Lookups(sess)

    if commit:
        ensure_notion_columns(conn)

    existing_clients = existing_by_notion(conn, "crm_clients")
    existing_cases = existing_by_notion(conn, "crm_cases")
    existing_pay = existing_by_notion(conn, "crm_payments_ledger")

    client_id_by_uuid = dict(existing_clients)   # notion_uuid -> db id
    case_id_by_uuid = dict(existing_cases)
    alias = build_alias_map(data)                 # removido -> mantido
    _synth = [0]

    def synth_id():
        _synth[0] -= 1
        return _synth[0]

    def resolve_client(u):
        u = uuid_from(u)
        if u is None:
            return None
        return client_id_by_uuid.get(u) or client_id_by_uuid.get(alias.get(u))

    def set_notion(table, db_id, notion_uuid):
        # notion_page_id é coluna adicionada por ALTER (não mapeada no ORM),
        # então grava via SQL cru após o flush que gerou o id.
        conn.execute(text(f"UPDATE {table} SET notion_page_id=:u WHERE id=:i"),
                     {"u": notion_uuid, "i": db_id})

    # ---- CLIENTES ----
    clients = data["clients_all_deduped"]
    if limit:
        clients = clients[:limit]
    for rec in clients:
        uuid = rec["notion_page_id"]
        name = g(rec, "Client Name") or "(sem nome)"
        fields = dict(
            full_name=name,
            email=g(rec, "Email"),
            us_phone=g(rec, "US Phone"), us_phone_has=bool(g(rec, "US Phone?", False)),
            home_phone=g(rec, "Home Country Phone"), home_phone_has=bool(g(rec, "Home Country Phone?", False)),
            us_address=g(rec, "US Address"), home_address=g(rec, "Home Country Address"),
            city_country=g(rec, "City/Country"), country_of_origin=g(rec, "Country of Origin"),
            preferred_language=enum_map(PREF_LANG, g(rec, "Preferred Language"), stats, "Client.preferred_language"),
            best_contact_time=g(rec, "Best Contact Time"),
            dob=parse_date(g(rec, "Date of Birth")),
            marital_status=enum_map(MARITAL, g(rec, "Marital Status"), stats, "Client.marital_status"),
            marriage_date=parse_date(g(rec, "Marriage Date")),
            has_dependents=bool(g(rec, "Has Dependents?", False)),
            n_dependents=g(rec, "Number of Dependents"),
            passport_expiration=parse_date(g(rec, "Passport Expiration")),
            current_status_visa=g(rec, "Current Status/Visa"),
            status_expiration=parse_date(g(rec, "Current Status Expiration")),
            resident_since=parse_date(g(rec, "Resident Since (LPR)")),
            gc_expiration=parse_date(g(rec, "GC Expiration Date")),
            tier=enum_map(TIER, g(rec, "Status"), stats, "Client.tier"),
            five_letters=g(rec, "5 Letters"), key_word=g(rec, "Key Word"),
        )
        if uuid in client_id_by_uuid and commit:
            obj = sess.get(Client, client_id_by_uuid[uuid])
            for k, v in fields.items():
                setattr(obj, k, v)
            stats.inc("clients_updated")
        else:
            obj = Client(**fields)
            if commit:
                sess.add(obj)
                sess.flush()
                set_notion("crm_clients", obj.id, uuid)
                client_id_by_uuid[uuid] = obj.id
            else:
                client_id_by_uuid[uuid] = synth_id()
            stats.inc("clients_inserted")

        # intake (1:1)
        intake_fields = dict(
            best_contact_period=best_contact_period(g(rec, "Qual o melhor horário para contato?"), stats),
            money_problem=g(rec, "Me conte seu maior problema com o dinheiro hoje:"),
            monthly_income_range=enum_map(INCOME_RANGE, g(rec, "Faixa de Renda Mensal Familiar"), stats, "Intake.income_range"),
            desired_solutions=g(rec, "Quais soluções você deseja encontrar com os nossos serviços?"),
            how_found_us_id=lk.lead_source(g(rec, "How Did You Hear About Us?")),
            referral_name=g(rec, "Referral Name"),
            previous_service=g(rec, "Por favor selecione o serviço que você já fez conosco:"),
        )
        if any(v is not None for v in intake_fields.values()):
            stats.inc("intakes")
            if commit and uuid in client_id_by_uuid:
                cid = client_id_by_uuid[uuid]
                existing_intake = sess.get(ClientIntake, cid)
                if existing_intake:
                    for k, v in intake_fields.items():
                        setattr(existing_intake, k, v)
                else:
                    sess.add(ClientIntake(client_id=cid, **intake_fields))

        # credenciais (criptografadas)
        cred_specs = [
            (CredentialService.uscis, g(rec, "USCIS Account Email"),
             g(rec, "USCIS Account Password"), g(rec, "USCIS Back Up Code")),
            (CredentialService.embassy, g(rec, "Email (Embassy)"),
             g(rec, "Password(Embassy)"), None),
        ]
        for service, cemail, cpass, cbackup in cred_specs:
            if not any([cemail, cpass, cbackup]):
                continue
            stats.inc("credentials")
            if commit and uuid in client_id_by_uuid:
                from app.services.crypto import encrypt
                cid = client_id_by_uuid[uuid]
                row = (sess.query(ClientCredential)
                       .filter_by(client_id=cid, service=service).first())
                enc = dict(email_encrypted=encrypt(cemail),
                           password_encrypted=encrypt(cpass),
                           backup_code_encrypted=encrypt(cbackup))
                if row:
                    for k, v in enc.items():
                        setattr(row, k, v)
                else:
                    sess.add(ClientCredential(client_id=cid, service=service, **enc))

        # dependentes
        dep_email = g(rec, "Dependent's Email")
        dep_phone = g(rec, "Dependent's Phone Number (USA)")
        if dep_email or dep_phone:
            stats.inc("dependents")
            if commit and uuid in client_id_by_uuid:
                cid = client_id_by_uuid[uuid]
                if not sess.query(ClientDependent).filter_by(client_id=cid).first():
                    sess.add(ClientDependent(client_id=cid, full_name="(dependente)",
                                             email=dep_email, us_phone=dep_phone))

    # ---- CASOS (dashboard + submitted, dedup por uuid) ----
    seen = set()
    cases = []
    for src, finalized in [("cases_dashboard", False), ("cases_submitted_finalized", True)]:
        for rec in data[src]:
            u = rec["notion_page_id"]
            if u in seen:
                continue
            seen.add(u)
            cases.append((rec, finalized))
    if limit:
        cases = cases[:limit]

    for rec, finalized in cases:
        uuid = rec["notion_page_id"]
        client_rel = rec.get("🧑‍💼 Client") or []
        client_uuid = client_rel[0] if client_rel else None
        client_db_id = resolve_client(client_uuid)
        if client_db_id is None:
            # Cliente do caso não está no export de clientes (ou foi removido
            # na dedup sem alias). O título do caso é o nome da pessoa -> cria
            # um cliente-stub para não perder o caso. notion_page_id estável
            # derivado do caso, para idempotência em reexecuções.
            stub_uuid = f"case-stub:{uuid}"
            stub_id = client_id_by_uuid.get(stub_uuid)
            if stub_id is None:
                stub_name = (g(rec, "Case Title") or "(cliente sem nome)").strip()
                stats.inc("clients_stub_criados")
                if commit:
                    stub = Client(full_name=stub_name)
                    sess.add(stub)
                    sess.flush()
                    set_notion("crm_clients", stub.id, stub_uuid)
                    stub_id = stub.id
                else:
                    stub_id = synth_id()
                client_id_by_uuid[stub_uuid] = stub_id
            client_db_id = stub_id

        # ponte USCIS (só relatório)
        form = derive_form(g(rec, "Case Title"), " ".join(rec.get("Current Step") or []))
        if form:
            stats.forms_derived[form] = stats.forms_derived.get(form, 0) + 1
        else:
            stats.forms_a_cadastrar.add(g(rec, "Case Title") or "(sem título)")

        fields = dict(
            client_id=client_db_id,
            title=g(rec, "Case Title") or "(sem título)",
            service_mode=ServiceMode.saes_standard,   # default; sem info de pacote no caso
            case_status=enum_map(CASE_STATUS, g(rec, "Case Status"), stats, "Case.case_status") or CaseStatus.lead_capture,
            process_status=enum_map(PROCESS_STATUS, g(rec, "Process Status"), stats, "Case.process_status") or ProcessStatus.intake,
            priority=enum_map(PRIORITY, g(rec, "Priority"), stats, "Case.priority") or Priority.medium,
            ready_for_next_step=(g(rec, "Go to Next Step") == "Yes"),
            field_office_id=lk.field_office(g(rec, "Field Office")),
            receipt_number=g(rec, "Receipt Number"),
            receipt_date=parse_date(g(rec, "Receipt Date")),
            submission_date=parse_date(g(rec, "Submission Date")),
            approval_date=parse_date(g(rec, "Approval Date")),
            service_deadline=parse_date(g(rec, "Service Deadline")),
            status_expire_on=parse_date(g(rec, "Status Expire On")),
            monitoring_started_at=parse_date(g(rec, "Case Monitoring  Started on")),
            next_check_at=parse_date(g(rec, "Next Case Status check")),
            last_checked_at=parse_date(g(rec, "Last Checked on")),
            rfe_received=bool(g(rec, "Received an RFE/NOID", False)),
            contract_signed=bool(g(rec, "Contract Signed", False)),
            terms_accepted=bool(g(rec, "Terms Accepted", False)),
            google_drive_url=g(rec, "Google Drive"),
            notes=g(rec, "Notes"),
        )
        stats.inc("cases_finalized" if finalized else "cases_active")
        if uuid in case_id_by_uuid and commit:
            obj = sess.get(Case, case_id_by_uuid[uuid])
            for k, v in fields.items():
                setattr(obj, k, v)
            stats.inc("cases_updated")
        else:
            obj = Case(**fields)
            if commit:
                sess.add(obj)
                sess.flush()
                set_notion("crm_cases", obj.id, uuid)
                case_id_by_uuid[uuid] = obj.id
            else:
                case_id_by_uuid[uuid] = synth_id()
            stats.inc("cases_inserted")

        # Current Step -> step log (append-only)
        for step in (rec.get("Current Step") or []):
            stats.inc("step_logs")
            if commit and uuid in case_id_by_uuid:
                cid = case_id_by_uuid[uuid]
                if not (sess.query(CaseStepLog)
                        .filter_by(case_id=cid, step_name=step).first()):
                    sess.add(CaseStepLog(case_id=cid, step_name=step))

    # ---- PAGAMENTOS ----
    payments = data["payments_all"]
    if limit:
        payments = payments[:limit]
    total_cents = 0
    for rec in payments:
        uuid = rec["notion_page_id"]
        cli = rec.get("Client") or []
        cas = rec.get("Cases") or []
        amount = to_cents(g(rec, "Amount Paid")) or 0
        total_cents += amount
        notes = " | ".join(x for x in [g(rec, "Confirmation Note"),
                                       g(rec, "Paymente Notes (Receivables)"),
                                       g(rec, "Paymente Notes (Payables)")] if x)
        fields = dict(
            client_id=resolve_client(cli[0]) if cli else None,
            case_id=case_id_by_uuid.get(uuid_from(cas[0])) if cas else None,
            description=g(rec, "Description") or "(sem descrição)",
            amount_cents=amount,
            currency=enum_map(CURRENCY, g(rec, "Currency"), stats, "Payment.currency") or Currency.usd,
            direction=enum_map(PAY_DIRECTION, g(rec, "Type of Payment"), stats, "Payment.direction") or PaymentDirection.receivable,
            status=enum_map(PAY_STATUS, g(rec, "Status"), stats, "Payment.status") or PaymentStatus.pending,
            payment_method_id=lk.payment_method(g(rec, "Payment Method")),
            invoice_date=parse_date(g(rec, "Invoice Date")),
            due_date=parse_date(g(rec, "Due Date")),
            payment_date=parse_date(g(rec, "Payment Date ")),
            notes=notes or None,
        )
        if fields["client_id"] is None and fields["case_id"] is None:
            stats.inc("payments_orfaos")
        stats.inc("payments")
        if uuid in existing_pay and commit:
            obj = sess.get(PaymentLedgerEntry, existing_pay[uuid])
            for k, v in fields.items():
                setattr(obj, k, v)
        else:
            obj = PaymentLedgerEntry(**fields)
            if commit:
                sess.add(obj)
                sess.flush()
                set_notion("crm_payments_ledger", obj.id, uuid)
    stats.counts["soma_pagamentos_usd"] = round(total_cents / 100, 2)

    if commit:
        sess.commit()
    else:
        sess.rollback()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="grava no banco (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None, help="importar só N de cada tipo (teste)")
    ap.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = ap.parse_args()

    data = json.loads(args.json.read_text(encoding="utf-8"))
    stats = Stats()

    if args.commit:
        bak = engine.url.database + f".bak-pre-notion-import-{datetime.now():%Y%m%d%H%M%S}"
        shutil.copy2(engine.url.database, bak)
        print(f"Backup do banco criado: {bak}")

    run(data, commit=args.commit, limit=args.limit, stats=stats)

    mode = "COMMIT" if args.commit else "DRY-RUN (nada foi gravado)"
    print("=" * 70)
    print(f"Importação Notion -> CRM  [{mode}]")
    print("=" * 70)
    for k in sorted(stats.counts):
        print(f"  {k}: {stats.counts[k]}")
    print(f"\n  formas USCIS derivadas dos casos: {dict(sorted(stats.forms_derived.items()))}")
    print(f"  casos sem forma no catálogo (amostra): {list(sorted(stats.forms_a_cadastrar))[:8]}")
    print(f"\n  avisos ({len(stats.warnings)}):")
    seen = {}
    for w in stats.warnings:
        key = w.split(":")[0] + ":" + w.split("->")[-1][:40] if "->" in w else w[:60]
        seen[key] = seen.get(key, 0) + 1
    for key, n in sorted(seen.items(), key=lambda x: -x[1])[:20]:
        print(f"    [{n}x] {key}")


if __name__ == "__main__":
    main()
