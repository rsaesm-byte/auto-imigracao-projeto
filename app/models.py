"""Modelos SQLAlchemy: usuário e submissões de formulário.

answers_json guarda exatamente o mesmo formato dos arquivos
output/answers-<slug>-e2e.json de hoje (um dict question_id -> valor) —
mesmo formato que is_visible()/active_questions()/validate_required()
(scripts/run_questionnaire.py) e fill_form_for_submission()
(app/services/pdf_service.py) já esperam.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base, UserMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    is_active_: Mapped[bool] = mapped_column(default=True)
    # Acesso ao painel /staff (marcar casos de Cartas Complementares como
    # pagos). Não existe fluxo de auto-cadastro para isso -- é ligado
    # manualmente no banco para as contas da própria equipe.
    is_staff: Mapped[bool] = mapped_column(default=False)
    # Login alternativo, só usado pela equipe hoje (ver app/auth.py::login,
    # aceita e-mail OU username) -- opcional, null pra clientes comuns.
    username: Mapped[str | None] = mapped_column(unique=True, index=True, default=None)
    # Perfil da aba /staff/perfil (app/staff.py) -- preenchido pelo próprio
    # usuário, nunca pela equipe uns dos outros. photo_path aponta pro
    # arquivo em instance/staff_photos/ (fora do git), servido só pra quem
    # está logado como staff (ver staff.profile_photo).
    photo_path: Mapped[str | None] = mapped_column(default=None)
    job_title: Mapped[str | None] = mapped_column(default=None)
    personal_phone: Mapped[str | None] = mapped_column(default=None)
    work_phone: Mapped[str | None] = mapped_column(default=None)
    work_hours: Mapped[str | None] = mapped_column(default=None)
    # Verificação de e-mail por código de 6 dígitos (ver
    # app/services/email_verification_service.py) -- exigida antes de
    # contratar um pacote (gate global em app/__init__.py::create_app()).
    # Contas já existentes antes desta feature são migradas com
    # email_verified=True (ver _ensure_user_email_verification_columns) para
    # não bloquear ninguém que já usava o sistema; contas de staff nunca
    # passam por este gate independente do valor aqui.
    email_verified: Mapped[bool] = mapped_column(default=False)
    email_verification_code_hash: Mapped[str | None] = mapped_column(default=None)
    email_verification_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    email_verification_attempts: Mapped[int] = mapped_column(default=0)
    # Permissão `financial_planning.manage_access` do
    # SAES_Financial_Planning_Master_Spec (Fase 1, 2026-08-07) -- quem
    # pode habilitar/desabilitar o módulo self-service "Financial
    # Planning" pra um cliente de coaching (ver
    # app/services/financial_planning_service.py). Flag booleana simples
    # (mesmo padrão de `is_staff` acima), não um sistema de papéis/
    # permissões completo -- isso é a Seção 13 do Prompt Mestre do CRM,
    # ainda pendente. Concedida manualmente por linha (nunca checado por
    # e-mail/nome hardcoded em rota nenhuma -- pedido explícito do
    # documento: "Never hard-code Alessandra").
    financial_planning_manage_access: Mapped[bool] = mapped_column(default=False)

    # Painel do CEO (Prompt Mestre 1, Seção 13, 2026-08-08) -- is_ceo é
    # separado das áreas normais de StaffAreaAccess de propósito: gerenciar
    # OUTRAS contas de colaborador (criar/bloquear/conceder área) é mais
    # sensível do que qualquer área de trabalho do dia a dia, então nunca
    # fica embutido em "Internal Management" nem em nenhuma outra área --
    # só concedido linha a linha, nunca checado por e-mail/nome hardcoded
    # em rota nenhuma (mesma regra já usada em
    # financial_planning_manage_access acima). Contas de staff já
    # existentes no dia em que este recurso foi ao ar ganharam is_ceo=True
    # junto com todas as áreas (ver _provision_legacy_staff_areas() em
    # app/__init__.py) -- ninguém perdeu acesso.
    is_ceo: Mapped[bool] = mapped_column(default=False)
    # Marca quem já passou pela concessão automática de "todas as áreas"
    # (contas anteriores ao recurso) -- nunca reavaliado depois. Sem isso,
    # um CEO que bloqueasse TODAS as áreas de alguém (0 linhas em
    # StaffAreaAccess) veria essa pessoa ganhar tudo de volta sozinha no
    # próximo boot, porque "zero áreas" ficaria indistinguível de "conta
    # nova, nunca provisionada".
    areas_provisioned: Mapped[bool] = mapped_column(default=False)

    submissions: Mapped[list["FormSubmission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")

    # UserMixin.is_active é uma property; sobrescrevemos para usar a coluna
    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.is_active_


class StaffAreaAccess(Base):
    """Perfis por ÁREA INTEIRA (Prompt Mestre 1, Seção 13) -- um colaborador
    pode ter 0 ou mais áreas de app/staff_permissions.py::AREAS. Ausência
    de linha = sem acesso àquela área (exceto is_ceo=True em User, que
    sempre passa por tudo, ver app/staff_permissions.py::has_area)."""
    __tablename__ = "staff_area_access"
    __table_args__ = (UniqueConstraint("user_id", "area", name="uq_staff_area_access_user_area"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    area: Mapped[str]
    granted_at: Mapped[datetime] = mapped_column(default=_utcnow)


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    form_slug: Mapped[str] = mapped_column(index=True)
    # Só usado por formulários "por dependente" (hoje só I-539A): aponta pro
    # FormSubmission do I-539 principal ao qual este dependente pertence.
    # Null para toda submissão normal (não-dependente).
    parent_submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("form_submissions.id"), default=None, index=True)
    # Preenchido quando a submissão nasceu de um "Iniciar pacote" em
    # app/packages.py (ver data/packages.json) -- usado só para agrupar
    # visualmente no dashboard; null para submissões avulsas.
    package_slug: Mapped[str | None] = mapped_column(default=None, index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    # Perguntas opcionais explicitamente deixadas em branco. Sem isso, uma
    # pergunta opcional sem resposta nunca entraria em answers_json e o
    # wizard ficaria perguntando ela pra sempre (achado testando o fluxo
    # completo via HTTP: a mesma pergunta nunca saía de "não respondida").
    skipped_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(default="in_progress")  # in_progress | completed
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    filled_pdf_path: Mapped[str | None] = mapped_column(default=None)
    checklist_pdf_path: Mapped[str | None] = mapped_column(default=None)
    documents_pdf_path: Mapped[str | None] = mapped_column(default=None)
    # Só usado pelo pseudo-formulário "i-539-cartas" (sem PDF oficial próprio):
    # zip com o resumo da narrativa + as cartas complementares aplicáveis.
    cartas_zip_path: Mapped[str | None] = mapped_column(default=None)
    # Só usado pelo pseudo-formulário "ds160" (idem, sem PDF/AcroForm
    # oficial -- o DS-160 de verdade só existe online no CEAC): PDF com a
    # marca Saes reunindo todas as respostas, gerado por
    # scripts/generate_ds160_draft.py para a equipe usar ao preencher o
    # formulário oficial.
    ds160_draft_pdf_path: Mapped[str | None] = mapped_column(default=None)
    # Campos do "núcleo de identidade" pré-preenchidos automaticamente a
    # partir de outra submissão do mesmo usuário (ver
    # app/wizard.py::_build_autofill), ainda não confirmados pelo usuário
    # nesta submissão -- {question_id: form_slug de origem}. Um question_id
    # sai daqui assim que o usuário passa por aquela pergunta no wizard
    # (confirmando ou alterando o valor), então não é "todo campo
    # autopreenchido alguma vez", só os que ainda não foram vistos.
    autofilled_json: Mapped[str] = mapped_column(Text, default="{}")
    # Número de recibo do USCIS, digitado manualmente pelo usuário depois que
    # o caso é protocolado -- não vem do questionário (a maioria dos
    # formulários não pergunta isso, já que o recibo só existe depois do
    # protocolo). Usado só para dar um atalho de "verificar status oficial"
    # no dashboard; não fazemos nenhuma consulta automática ao USCIS (ver
    # references/compliance.md e a decisão desta sessão de não automatizar
    # contorno de CAPTCHA do egov.uscis.gov).
    receipt_number: Mapped[str | None] = mapped_column(default=None)
    # Só usado pelo caso "I-539 — Cartas Complementares" (a submissão
    # i-539-cartas em si, nunca nas 4 cartas de terceiro vinculadas a ela --
    # ver app/wizard.py::_cartas_case): true depois que a equipe confirma
    # manualmente (via /staff) que o cliente pagou pelo serviço, fora do
    # site (Zelle/Venmo/wire/cartão -- ver app/payment_methods.py). Sem
    # isso, generate() recusa gerar a carta narrativa ou qualquer carta de
    # terceiro vinculada a este caso.
    paid: Mapped[bool] = mapped_column(default=False)
    paid_at: Mapped[datetime | None] = mapped_column(default=None)
    # Liga esta submissão a um Case do CRM (app/crm_models.py) quando o
    # formulário faz parte de um caso gerenciado (full_service) ou o
    # próprio cliente self_service tem um Case aberto para acompanhamento
    # -- opcional e nullable de propósito: toda submissão que já existia
    # antes do CRM continua funcionando sem nenhum Case associado.
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), default=None, index=True)

    user: Mapped[User] = relationship(back_populates="submissions")

    def get_answers(self) -> dict:
        return json.loads(self.answers_json) if self.answers_json else {}

    def set_answers(self, answers: dict) -> None:
        self.answers_json = json.dumps(answers, ensure_ascii=False)

    def get_skipped(self) -> set[str]:
        return set(json.loads(self.skipped_json)) if self.skipped_json else set()

    def set_skipped(self, skipped: set[str]) -> None:
        self.skipped_json = json.dumps(sorted(skipped), ensure_ascii=False)

    def get_autofilled(self) -> dict:
        return json.loads(self.autofilled_json) if self.autofilled_json else {}

    def set_autofilled(self, autofilled: dict) -> None:
        self.autofilled_json = json.dumps(autofilled, ensure_ascii=False)


class Payment(Base):
    """Gate de pagamento genérico (Zelle/Venmo/cartão/wire + comprovante,
    ver app/payment_gate.py) para qualquer formulário avulso ou pacote
    vendido pela Saes conforme data/service_fees.json -- não cobre as
    Cartas Complementares do I-539, que têm seu próprio gate mais simples
    desde antes (FormSubmission.paid/paid_at, ver app/wizard.py::_cartas_case).
    Uma linha por "caso": ou (user_id, package_slug) para um pacote inteiro,
    ou (user_id, submission_id) para um formulário avulso -- submission_id
    aponta pra raiz da cadeia de parent_submission_id quando o formulário
    tem dependentes (ver app/wizard.py::_payment_case), exceto para I-134,
    que sempre tem seu próprio caso/preço (ver mesma função)."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    package_slug: Mapped[str | None] = mapped_column(default=None, index=True)
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("form_submissions.id"), default=None, index=True)
    amount_cents: Mapped[int]
    method: Mapped[str | None] = mapped_column(default=None)  # zelle | venmo | credit_card | wire
    proof_path: Mapped[str | None] = mapped_column(default=None)
    # Preenchidos pelo cliente na tela de checkout (app/payment_gate.py) --
    # client_phone é o que importa de verdade: quando um staff confirma o
    # pagamento (app/staff.py::confirm_payment), é pra ESSE número que o
    # WhatsApp abre (não o da Saes), pra equipe avisar o cliente direto.
    # client_name/client_email só ficam guardados de referência pra equipe.
    client_name: Mapped[str | None] = mapped_column(default=None)
    client_email: Mapped[str | None] = mapped_column(default=None)
    client_phone: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="pending")  # pending | confirmed
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(default=None)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    # Ciclo de vida depois da aprovação (painel /staff, abas "Aprovados" /
    # "Finalizados" / "Solicitar Review" -- ver app/staff.py). finalized_at
    # é preenchido quando a equipe marca o caso como encerrado de vez
    # (documentos entregues); review_requested é o "X" que tira o caso da
    # aba "Solicitar Review" depois que a equipe já pediu a avaliação pro
    # cliente -- só faz sentido depois de finalizado.
    finalized_at: Mapped[datetime | None] = mapped_column(default=None)
    review_requested: Mapped[bool] = mapped_column(default=False)
    # Mesmo link opcional que FormSubmission.case_id acima -- ver
    # app/crm_models.py::PaymentLedgerEntry.gate_payment_id para a ligação
    # inversa (o ledger financeiro completo do CRM aponta pra cá quando é
    # a mesma transação, em vez de duplicar o registro).
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), default=None, index=True)
    # Paralelo a package_slug/submission_id acima, mas para a compra de um
    # "Pacote Completo" profissional (Saes Standard/Plus) -- esses não têm
    # FormSubmission (o cliente não preenche PDF, a equipe conduz o caso),
    # então o "caso de pagamento" nasce de um Lead em vez de uma submissão
    # (ver app/payment_gate.py::checkout_lead, app/services/pricing.py).
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("crm_leads.id"), default=None, index=True)


class ServiceFee(Base):
    """Preço cobrado pela Saes Professional Services por um formulário
    avulso ou pacote -- fonte da verdade para app/services/pricing.py
    (não confundir com a taxa oficial da USCIS em data/registry.json).
    Semeada uma vez a partir de data/service_fees.json quando a tabela
    está vazia (ver app/__init__.py::_seed_service_fees) e editável pela
    equipe na aba "Preços" do painel /staff -- dali em diante o arquivo
    JSON só serve de valor inicial/histórico, nunca mais é lido em
    produção. Uma linha por (kind, slug):
      - kind="individual", slug=form_slug: preço quando vendido avulso.
      - kind="in_package", slug=form_slug: preço deste formulário quando
        faz parte de um pacote (usado por I-134 hoje, ver
        app/wizard.py::_payment_case).
      - kind="package", slug=package_slug: preço total do pacote.
    price_cents None = "não vendido separadamente nesse contexto"."""
    __tablename__ = "service_fees"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]  # individual | in_package | package
    slug: Mapped[str]
    price_cents: Mapped[int | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)


class PostPaymentOnboarding(Base):
    """Etapa que se abre pro cliente assim que um Payment é confirmado
    (ver app/staff.py::confirm_payment) -- endereço completo nos EUA,
    e-mail do titular/dependentes, e checklist de documentos de apoio
    (RequiredDocument abaixo). Uma linha por Payment (não por
    FormSubmission -- um pacote com várias submissões usa o mesmo
    onboarding, mesma unidade de "caso" já usada em
    app/staff.py::_case_label/_case_submissions)."""
    __tablename__ = "post_payment_onboarding"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), unique=True, index=True)

    # Nome completo/telefone do titular -- pedido do usuário (2026-08-01)
    # pra sincronizar com Client.full_name/us_phone no CRM (ver
    # app/onboarding.py::_sync_onboarding_to_crm).
    applicant_full_name: Mapped[str | None] = mapped_column(default=None)
    applicant_us_phone: Mapped[str | None] = mapped_column(default=None)
    us_address_line1: Mapped[str | None] = mapped_column(default=None)
    us_address_complement: Mapped[str | None] = mapped_column(default=None)
    us_city: Mapped[str | None] = mapped_column(default=None)
    us_state: Mapped[str | None] = mapped_column(default=None)
    us_zip: Mapped[str | None] = mapped_column(default=None)
    applicant_email: Mapped[str | None] = mapped_column(default=None)
    # True assim que o cliente salva o formulário de endereço/e-mails pelo
    # menos uma vez -- não significa que o staff já revisou nada, só que
    # não está mais em branco.
    address_confirmed: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    dependents: Mapped[list["OnboardingDependent"]] = relationship(
        back_populates="onboarding", cascade="all, delete-orphan")
    documents: Mapped[list["RequiredDocument"]] = relationship(
        back_populates="onboarding", cascade="all, delete-orphan")


class OnboardingDependent(Base):
    """E-mail de um dependente do titular (cônjuge, filho etc.) informado
    na etapa de onboarding -- N por PostPaymentOnboarding."""
    __tablename__ = "onboarding_dependents"

    id: Mapped[int] = mapped_column(primary_key=True)
    onboarding_id: Mapped[int] = mapped_column(ForeignKey("post_payment_onboarding.id"), index=True)
    full_name: Mapped[str]
    email: Mapped[str | None] = mapped_column(default=None)
    us_phone: Mapped[str | None] = mapped_column(default=None)

    onboarding: Mapped[PostPaymentOnboarding] = relationship(back_populates="dependents")


class RequiredDocument(Base):
    """Um item do checklist de documentos de apoio -- criado manualmente
    pelo staff por caso (não reusa data/document_rules/<form>.json de
    propósito: cada caso pode precisar de uma lista diferente). O cliente
    faz upload quando tem o documento em mãos e marca como enviado; o
    staff aprova, reprova (com observação) ou pede reenvio."""
    __tablename__ = "required_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    onboarding_id: Mapped[int] = mapped_column(ForeignKey("post_payment_onboarding.id"), index=True)
    label: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending", index=True)  # pending | uploaded | approved | rejected
    # Marcado pelo staff em /staff/crm/casos/<id>/procedimento -- pedido do
    # usuário 2026-08-06: quando marcado, o item passa a aparecer na aba
    # "Translations" do cliente (app/crm_client.py::translations()) e
    # dispara uma notificação pro cliente (ver app/services/
    # notification_service.py, Notification.recipient_user_id).
    needs_translation: Mapped[bool] = mapped_column(default=False)
    file_path: Mapped[str | None] = mapped_column(default=None)
    uploaded_at: Mapped[datetime | None] = mapped_column(default=None)
    staff_notes: Mapped[str | None] = mapped_column(Text, default=None)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    onboarding: Mapped[PostPaymentOnboarding] = relationship(back_populates="documents")


class StaffNavLayout(Base):
    """Per-collaborator customization of the /staff top nav bar -- order of
    tabs + optional dropdown groups bundling several tabs together. User
    request 2026-08-02: an "Edit navigation" mode where tabs can be
    dragged to reorder and dropped onto each other to form a group. One
    row per user; no row means "use the default order" (see
    app/staff_nav.py::DEFAULT_LAYOUT) -- never a stored duplicate of it,
    so a future new tab added to the registry shows up for everyone who
    hasn't customized their nav without a migration."""
    __tablename__ = "staff_nav_layouts"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    layout_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class StaffNavGlobalLayout(Base):
    """Org-wide default nav layout -- a singleton (always id=1), separate
    from the per-user `StaffNavLayout` above. User request 2026-08-02:
    "Save for all collaborators" vs. "Save just for me" when editing the
    nav. Resolution order (app/staff_nav.py::resolve_nav_layout): a
    collaborator's own `StaffNavLayout` row wins if present; otherwise
    this singleton if someone has ever saved one "for everyone"; otherwise
    the hardcoded DEFAULT_LAYOUT. Never duplicated -- same convention as
    StaffNavLayout (absence means "fall through to the next layer")."""
    __tablename__ = "staff_nav_global_layout"

    id: Mapped[int] = mapped_column(primary_key=True)
    layout_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)


class StaffDashboardLayout(Base):
    """Personalização por colaborador da aba Dashboard (Prompt Mestre,
    Fase 3, 2026-08-06: "Reorganizar widgets; Ocultar widgets; ... Salvar
    preferências"). `visible_widgets_json` é uma lista JSON de chaves de
    widget (ver app/services/dashboard_service.py::WIDGETS) NA ORDEM em
    que devem aparecer -- um widget ausente da lista está oculto; não há
    coluna separada de "ocultos" (a própria ausência já é o sinal, mesma
    convenção around de "sem linha = usa o padrão" do StaffNavLayout
    acima). Deliberadamente só pessoal (sem StaffDashboardGlobalLayout) --
    diferente da navegação, o documento não pediu um "salvar pra todo
    mundo" aqui."""
    __tablename__ = "staff_dashboard_layouts"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    visible_widgets_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
