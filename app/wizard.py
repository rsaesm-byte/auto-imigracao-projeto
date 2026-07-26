"""Blueprint do wizard: dashboard, responder perguntas, revisão, geração e
download dos PDFs.

Reaproveita is_visible()/active_questions() de scripts/run_questionnaire.py
(o motor de show_if) e missing_required_fields()/fill_form_for_submission()/
generate_checklist_for_submission() de app/services/pdf_service.py.

Diferente do wizard de CLI, aqui não guardamos um ponteiro `pos` — cada
requisição recalcula "a primeira pergunta ativa ainda sem resposta" a partir
do dict de respostas salvo. Isso já dá o comportamento de retomar de onde
parou de graça, e evita o bug que existia no CLI (reperguntar uma resposta
obrigatória já dada e rejeitar o Enter em branco) porque aqui uma pergunta
já respondida nunca é mostrada de novo durante o fluxo linear — editar uma
resposta antiga é uma ação deliberada à parte (tela de revisão).
"""
from __future__ import annotations

import re
from pathlib import Path

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, send_file, session, url_for)
from flask_login import current_user, login_required

from app.db import SessionLocal
from app.i18n import SUPPORTED_LANGS
from app.models import FormSubmission
from app.services.news_service import get_latest_news
from app.services.pdf_service import (document_checklist_available,
                                       fill_form_for_submission,
                                       generate_checklist_for_submission,
                                       generate_document_checklist_for_submission,
                                       missing_required_fields)
from scripts.run_questionnaire import DATE_RE, US_STATES, active_questions

wizard_bp = Blueprint("wizard", __name__)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_USERS_DIR = ROOT / "output" / "users"

# todos os formulários do projeto, na ordem em que aparecem na página
# inicial e no dashboard. "i-539-cartas" é um pseudo-formulário: não tem PDF
# oficial/mapping próprio (ver PDF_BACKED_FORMS abaixo) -- gera o resumo da
# narrativa + até 4 cartas complementares (endereço/patrocínio/empregador/
# responsável pela empresa) via scripts/generate_cartas_i539.py, não
# scripts/fill_form.py.
FORM_SLUGS_ORDER = ["i-130", "i-130a", "i-485", "i-765", "i-131", "i-864", "i-751",
                    "i-90", "n-400", "i-539", "i-539-cartas"]

# Formulários administrativos/complementares (notificação G-1145, pagamento
# G-1450/G-1650, e o I-539A por dependente) -- preenchíveis pelo mesmo motor
# de formulário único, mas NÃO aparecem como blocos próprios em /servicos
# (não têm data/service_pages/<slug>.json): G-1145 e I-539A só são
# alcançados a partir de um pacote (data/packages.json / app/packages.py)
# ou, no caso do I-539A, do botão "adicionar dependente" numa submissão
# I-539 existente (ver wizard.add_dependent). G-1450/G-1650 são exceção
# deliberada (pedido do usuário, 2026-07-23): aparecem também na grade
# principal da home/dashboard via MAIN_GRID_EXTRA_SLUGS abaixo, mesmo sem
# página de serviço própria -- os links dessas duas vão direto pra
# wizard.start, nunca pra wizard.service_detail. Ver ENABLED_FORMS abaixo
# (união das duas listas) para o que de fato pode ser iniciado via
# /forms/<slug>/start.
AUXILIARY_FORM_SLUGS = ["g-1145", "g-1450", "g-1650", "i-539a", "i-134"]

# Valores reais da pergunta "servico" em data/questionnaires/i-539.json --
# usado por wizard.start() para pré-preencher essa pergunta quando o
# usuário já escolhe o serviço em /servicos/i-539 (seletor rápido), antes
# mesmo de entrar no wizard. Qualquer valor fora desta lista é ignorado.
I539_SERVICO_VALUES = {"eos", "cos_f1", "cos_f2", "cos_b2"}

ENABLED_FORMS = list(FORM_SLUGS_ORDER) + AUXILIARY_FORM_SLUGS

# Subconjunto de AUXILIARY_FORM_SLUGS que também aparece na grade principal
# (página inicial + dashboard "começar um formulário"), mesmo não tendo
# página de serviço própria em /servicos. G-1145 e I-539A ficam de fora
# desta lista de propósito (ver comentário acima).
MAIN_GRID_EXTRA_SLUGS = ["g-1450", "g-1650"]

# Formulários de referência: não são preenchidos por este produto -- exigem
# um terceiro credenciado (ex.: o I-693 só pode ser completado e assinado por
# um "civil surgeon" designado pela USCIS). Não têm questionnaire/mapping
# próprios, então não entram em FORM_SLUGS_ORDER/ENABLED_FORMS; aparecem na
# grade da página inicial com um selo distinto ("Documento de referência")
# e um link de download direto do PDF oficial em branco (ver reference_pdf()
# abaixo), só para o cliente conhecer o documento com antecedência.
REFERENCE_FORM_SLUGS = ["i-693"]

# formulários com PDF oficial + mapping (todo o resto usa fill_form_for_submission);
# "i-539-cartas" é o único de fora -- tratado à parte em generate()/download().
PDF_BACKED_FORMS = [s for s in FORM_SLUGS_ORDER if s != "i-539-cartas"]

CARTAS_DISPLAY_NAME = {"pt": "I-539 — Cartas Complementares", "en": "I-539 — Supplementary Letters"}


def _load_questionnaire(slug: str) -> dict:
    """Carrega o questionário em português e, se o idioma da sessão for
    inglês e existir um overlay de tradução para esse formulário
    (data/translations/<slug>.en.json), aplica label/hint/opções em
    inglês por cima -- sem tocar no arquivo original em português. Só o
    I-90 tem overlay por enquanto; os outros 7 formulários continuam em
    português mesmo com o site em inglês (o próprio wizard avisa isso)."""
    import json
    from app.i18n import get_lang

    path = ROOT / "data" / "questionnaires" / f"{slug}.json"
    qdata = json.loads(path.read_text(encoding="utf-8"))

    lang = get_lang()
    if lang == "pt":
        return qdata

    overlay_path = ROOT / "data" / "translations" / f"{slug}.{lang}.json"
    if not overlay_path.exists():
        return qdata

    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    q_overlay = overlay.get("questions", {})
    s_overlay = overlay.get("sections", {})

    for q in qdata["questions"]:
        ov = q_overlay.get(q["id"])
        if not ov:
            continue
        if "label" in ov:
            q["label"] = ov["label"]
        if "hint" in ov:
            q["hint"] = ov["hint"]
        if "options" in ov:
            for opt in q.get("options", []):
                if opt["value"] in ov["options"]:
                    opt["label"] = ov["options"][opt["value"]]
    for s in qdata.get("sections", []):
        if s["id"] in s_overlay:
            s["title"] = s_overlay[s["id"]]

    return qdata


def _questionnaire_has_translation(slug: str, lang: str) -> bool:
    if lang == "pt":
        return True
    return (ROOT / "data" / "translations" / f"{slug}.{lang}.json").exists()


def _load_registry_entry(slug: str) -> dict:
    import json
    from scripts.generate_checklist import FORM_SLUGS
    reg = json.loads((ROOT / "data" / "registry.json").read_text(encoding="utf-8"))
    return reg["forms"].get(FORM_SLUGS.get(slug, slug.upper()), {})


def _form_display_name(slug: str) -> str:
    """Nome do formulário na vitrine (landing/dashboard) -- em inglês
    quando o site está em inglês, já que o nome oficial do formulário é
    em inglês mesmo (é o nome real que a USCIS usa); em português quando
    o site está em português."""
    from app.i18n import get_lang
    lang = get_lang()
    if slug == "i-539-cartas":
        return CARTAS_DISPLAY_NAME[lang]
    entry = _load_registry_entry(slug)
    if lang == "en":
        return entry.get("name", slug.upper())
    return entry.get("name_pt", slug.upper())


def _load_field_equivalences() -> dict:
    """Carrega data/field_equivalences.json (mapa de campos de 'núcleo de
    identidade' equivalentes entre formulários -- nome, nascimento, SSN/
    A-Number, endereço, contato). i-539a fica de fora do arquivo inteiro de
    propósito: seus campos descrevem um dependente, não o titular da conta
    -- ver a nota de papéis no próprio arquivo."""
    import json
    path = ROOT / "data" / "field_equivalences.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _build_autofill(user_id: int, target_slug: str) -> tuple[dict, dict]:
    """Monta um pré-preenchimento do núcleo de identidade para uma
    submissão nova, puxando -- para cada campo canônico que o formulário-
    alvo coleta -- o valor mais recentemente salvo pelo mesmo usuário em
    QUALQUER outra submissão sua (completa ou em andamento) que colete o
    mesmo campo. Retorna (prefill, sources): prefill é um dict pronto para
    FormSubmission.set_answers(); sources é {question_id: form_slug de
    origem}, usado só para a UI mostrar de onde veio cada valor (ver
    wizard_view() e o aviso em wizard_step.html) -- o usuário sempre
    confirma ou altera antes de seguir, nunca é silencioso."""
    equivalences = _load_field_equivalences()
    prior = (
        SessionLocal.query(FormSubmission)
        .filter(FormSubmission.user_id == user_id, FormSubmission.form_slug != target_slug)
        .order_by(FormSubmission.updated_at.desc())
        .all()
    )
    prefill: dict = {}
    sources: dict = {}
    for per_form in equivalences.values():
        target_qid = per_form.get(target_slug)
        if not target_qid:
            continue
        for submission in prior:
            source_qid = per_form.get(submission.form_slug)
            if not source_qid:
                continue
            value = submission.get_answers().get(source_qid)
            if value:
                prefill[target_qid] = value
                sources[target_qid] = submission.form_slug
                break
    return prefill, sources


def _section_title(qdata: dict, question: dict) -> str | None:
    """Título da seção (ex.: 'Parte 1 — Informações Básicas') da pergunta
    atual, usado no cabeçalho do wizard pra dar contexto de onde ela está
    dentro do formulário -- reaproveita a lista `sections` que cada
    questionário já carrega, sem duplicar essa informação em outro lugar."""
    section_id = question.get("section")
    if not section_id:
        return None
    for s in qdata.get("sections", []):
        if s["id"] == section_id:
            return s["title"]
    return None


def _get_owned_submission(submission_id: int) -> FormSubmission:
    submission = SessionLocal.get(FormSubmission, submission_id)
    if submission is None or submission.user_id != current_user.id:
        abort(404)
    return submission


def _submission_dir(submission: FormSubmission) -> Path:
    return OUTPUT_USERS_DIR / str(submission.user_id) / str(submission.id)


def _display_value(question: dict, value) -> str:
    """Traduz o valor bruto salvo (ex: 'sim', 'nao') de volta para o rótulo
    mostrado ao usuário (ex: 'Sim'), para a tela de revisão."""
    options = {opt["value"]: opt["label"] for opt in question.get("options", [])}
    if isinstance(value, list):
        return ", ".join(options.get(v, v) for v in value)
    return options.get(value, value)


@wizard_bp.route("/set-lang/<lang>")
def set_lang(lang: str):
    if lang in SUPPORTED_LANGS:
        session["lang"] = lang
    return redirect(request.referrer or url_for("wizard.index"))


@wizard_bp.route("/formularios/<slug>/pdf-referencia")
def reference_pdf(slug: str):
    """Download público (sem login) do PDF oficial em branco de um formulário
    de referência (ver REFERENCE_FORM_SLUGS) -- não é gerado nem preenchido
    por este produto, é só o documento oficial para o cliente conhecer."""
    if slug not in REFERENCE_FORM_SLUGS:
        abort(404)
    entry = _load_registry_entry(slug)
    pdf_path = ROOT / entry["local_pdf"]
    return send_file(pdf_path, as_attachment=True, download_name=f"{slug.upper()}.pdf")


@wizard_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("wizard.dashboard"))
    from app.i18n import get_lang
    lang = get_lang()
    catalog = [
        {"slug": slug, "name": _form_display_name(slug), "reference": False,
         "enabled": slug in ENABLED_FORMS}
        for slug in list(FORM_SLUGS_ORDER) + MAIN_GRID_EXTRA_SLUGS
    ]
    for slug in REFERENCE_FORM_SLUGS:
        entry = _load_registry_entry(slug)
        note = entry.get("reference_only_note_en") if lang == "en" else entry.get("reference_only_note")
        catalog.append({
            "slug": slug, "name": _form_display_name(slug), "reference": True,
            "enabled": False, "reference_note": note,
            "civil_surgeon_url": entry.get("civil_surgeon_finder_url"),
        })
    return render_template("index.html", catalog=catalog, news_items=get_latest_news())


@wizard_bp.route("/servicos")
def services():
    catalog = [
        {"slug": slug, "name": _form_display_name(slug),
         "enabled": slug in ENABLED_FORMS}
        for slug in FORM_SLUGS_ORDER
    ]
    return render_template("services.html", catalog=catalog)


_SERVICE_CONTENT_FIELDS = [
    "tagline", "what_is", "who_needs", "eligibility", "required_evidence",
    "whats_included", "how_it_works", "common_mistakes", "faq", "related_note",
    "legal_note",
    # Campos só usados pela página do I-539 (regra de admissão fixa, taxa
    # SEVIS, busca de escola certificada) -- ausentes/None nas outras
    # páginas, o template já trata isso como "seção não aplicável".
    "rule_change_title", "rule_change_body",
    "sevis_fee_title", "sevis_fee_intro", "sevis_fee_facts",
    "sevis_fee_video_caption", "sevis_fee_disclaimer",
    "school_search_title", "school_search_body", "school_search_link_label",
]


def _load_service_content(slug: str) -> dict:
    """Carrega data/service_pages/<slug>.json e resolve os campos para o
    idioma atual da sessão (cada campo tem uma variante <campo>_en; sem
    overlay -- este conteúdo é próprio, não uma tradução por cima de um
    original, diferente do padrão usado nos questionários)."""
    import json
    from app.i18n import get_lang

    path = ROOT / "data" / "service_pages" / f"{slug}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    lang = get_lang()
    return {
        field: raw.get(f"{field}_en") if lang == "en" and raw.get(f"{field}_en") is not None
        else raw.get(field)
        for field in _SERVICE_CONTENT_FIELDS
    }


SERVICE_TO_ELIGIBILITY_QUIZ = {
    "n-400": "cidadania",
    "i-751": "gc-roc",
    "i-485": "gc-aos",
    "i-130": "gc-consular",
}


@wizard_bp.route("/servicos/<slug>", methods=["GET", "POST"])
def service_detail(slug: str):
    if slug not in FORM_SLUGS_ORDER:
        abort(404)
    content_path = ROOT / "data" / "service_pages" / f"{slug}.json"
    if not content_path.exists():
        abort(404)

    content = _load_service_content(slug)
    registry_entry = _load_registry_entry(slug) if slug != "i-539-cartas" else {}
    related_catalog = [
        {"slug": s, "name": _form_display_name(s)}
        for s in FORM_SLUGS_ORDER if s != slug
    ]

    calc_result, calc_error, calc_form = _run_filing_date_calculator(slug)

    return render_template(
        "service_detail.html",
        slug=slug,
        name=_form_display_name(slug),
        content=content,
        registry=registry_entry,
        related_catalog=related_catalog,
        eligibility_quiz=SERVICE_TO_ELIGIBILITY_QUIZ.get(slug),
        calc_result=calc_result,
        calc_error=calc_error,
        calc_form=calc_form,
    )


def _run_filing_date_calculator(slug: str):
    """Processa o POST das calculadoras de janela de protocolo em
    service_detail.html (I-751: data de expiração -> data mais cedo pra
    protocolar; N-400: data do Green Card + base de elegibilidade -> mesma
    coisa). Pura leitura/validação de formulário -- o cálculo em si vive em
    app/services/filing_date_calculator.py, sem I/O. Retorna
    (calc_result: dict|None, calc_error: str|None, calc_form: dict) --
    calc_form sempre tem as chaves esperadas pelo template, vazias em GET."""
    from app.i18n import t
    from app.services.filing_date_calculator import (InvalidDateError,
                                                       compute_i751_filing_date,
                                                       compute_n400_filing_window,
                                                       parse_mdy)

    calc_form = {
        "exp_month": "", "exp_day": "", "exp_year": "",
        "gc_month": "", "gc_day": "", "gc_year": "",
        "basis": "geral_5",
    }
    if request.method != "POST" or request.form.get("calc_action") not in (
            "i751_filing_date", "n400_filing_window"):
        return None, None, calc_form

    action = request.form.get("calc_action")

    if action == "i751_filing_date" and slug == "i-751":
        calc_form["exp_month"] = request.form.get("exp_month", "")
        calc_form["exp_day"] = request.form.get("exp_day", "")
        calc_form["exp_year"] = request.form.get("exp_year", "")
        try:
            expiration = parse_mdy(calc_form["exp_month"], calc_form["exp_day"], calc_form["exp_year"])
        except InvalidDateError:
            return None, t("calc_error_invalid_date"), calc_form
        result = compute_i751_filing_date(expiration)
        result["type"] = "i751"
        return result, None, calc_form

    if action == "n400_filing_window" and slug == "n-400":
        calc_form["gc_month"] = request.form.get("gc_month", "")
        calc_form["gc_day"] = request.form.get("gc_day", "")
        calc_form["gc_year"] = request.form.get("gc_year", "")
        calc_form["basis"] = request.form.get("basis", "geral_5")
        try:
            gc_date = parse_mdy(calc_form["gc_month"], calc_form["gc_day"], calc_form["gc_year"])
        except InvalidDateError:
            return None, t("calc_error_invalid_date"), calc_form
        years = 3 if calc_form["basis"] == "conjuge_3" else 5
        result = compute_n400_filing_window(gc_date, years)
        result["type"] = "n400"
        return result, None, calc_form

    return None, None, calc_form


@wizard_bp.route("/dashboard")
@login_required
def dashboard():
    submissions = (
        SessionLocal.query(FormSubmission)
        .filter_by(user_id=current_user.id)
        .order_by(FormSubmission.updated_at.desc())
        .all()
    )
    # Dependentes (I-539A) agrupados sob a submissão-pai (I-539) para exibição
    # aninhada no dashboard -- ver app/templates/dashboard.html.
    dependents_by_parent: dict[int, list[FormSubmission]] = {}
    for s in submissions:
        if s.parent_submission_id:
            dependents_by_parent.setdefault(s.parent_submission_id, []).append(s)
    top_level = [s for s in submissions if not s.parent_submission_id]

    catalog = [
        {"slug": slug, "name": _form_display_name(slug)}
        for slug in list(FORM_SLUGS_ORDER) + MAIN_GRID_EXTRA_SLUGS
    ]
    return render_template("dashboard.html", submissions=top_level, catalog=catalog,
                           dependents_by_parent=dependents_by_parent,
                           dependent_form_enabled=("i-539a" in ENABLED_FORMS),
                           i134_form_enabled=("i-134" in ENABLED_FORMS),
                           news_items=get_latest_news())


@wizard_bp.route("/forms/<slug>/start")
@login_required
def start(slug: str):
    if slug not in ENABLED_FORMS:
        abort(404)

    existing = (
        SessionLocal.query(FormSubmission)
        .filter_by(user_id=current_user.id, form_slug=slug, status="in_progress")
        .order_by(FormSubmission.updated_at.desc())
        .first()
    )
    if existing:
        return redirect(url_for("wizard.wizard_view", submission_id=existing.id))

    # I-539 cobre 4 serviços bem diferentes (EOS/COS-F1/COS-F2/COS-B2) --
    # sem já saber qual, mandamos para o seletor em /servicos/i-539 em vez
    # de abrir o questionário direto na pergunta "qual serviço?". Isso vale
    # pra QUALQUER link que aponte direto pra cá (grade da home, dashboard,
    # botão "Começar" do catálogo) sem passar pelo seletor primeiro -- não
    # só o botão "Saiba mais", que já linkava pra lá.
    if slug == "i-539" and request.args.get("servico") not in I539_SERVICO_VALUES:
        return redirect(url_for("wizard.service_detail", slug="i-539"))

    submission = FormSubmission(user_id=current_user.id, form_slug=slug)
    prefill, sources = _build_autofill(current_user.id, slug)
    if slug == "i-539" and request.args.get("servico") in I539_SERVICO_VALUES:
        prefill["servico"] = request.args["servico"]
    submission.set_answers(prefill)
    submission.set_autofilled(sources)
    SessionLocal.add(submission)
    SessionLocal.commit()
    return redirect(url_for("wizard.wizard_view", submission_id=submission.id))


@wizard_bp.route("/forms/<slug>/new")
@login_required
def new_attempt(slug: str):
    """Inicia uma tentativa nova (ignora qualquer in_progress existente)."""
    if slug not in ENABLED_FORMS:
        abort(404)
    submission = FormSubmission(user_id=current_user.id, form_slug=slug)
    prefill, sources = _build_autofill(current_user.id, slug)
    submission.set_answers(prefill)
    submission.set_autofilled(sources)
    SessionLocal.add(submission)
    SessionLocal.commit()
    return redirect(url_for("wizard.wizard_view", submission_id=submission.id))


@wizard_bp.route("/wizard/<int:parent_submission_id>/dependentes/adicionar", methods=["POST"])
@login_required
def add_dependent(parent_submission_id: int):
    """Cria uma nova submissão I-539A vinculada a uma submissão I-539
    (parent_submission_id) -- um formulário por dependente/co-requerente
    incluído no mesmo pedido de extensão/mudança de status. Reaproveita o
    wizard de formulário único sem nenhuma UI nova: a submissão do
    dependente é só mais um FormSubmission, só que com parent_submission_id
    preenchido, o que o app/wizard.py::dashboard() usa para agrupar
    visualmente sob o I-539 principal."""
    parent = _get_owned_submission(parent_submission_id)
    if parent.form_slug != "i-539":
        abort(400)
    if "i-539a" not in ENABLED_FORMS:
        abort(404)

    dependent = FormSubmission(
        user_id=current_user.id, form_slug="i-539a",
        parent_submission_id=parent.id, package_slug=parent.package_slug,
    )
    dependent.set_answers({})
    SessionLocal.add(dependent)
    SessionLocal.commit()
    return redirect(url_for("wizard.wizard_view", submission_id=dependent.id))


@wizard_bp.route("/wizard/<int:parent_submission_id>/i134/adicionar", methods=["POST"])
@login_required
def add_i134(parent_submission_id: int):
    """Cria uma nova submissão I-134 (Declaração de Apoio Financeiro) vinculada
    a uma submissão I-539 -- oferecido quando o solicitante (COS F-1 ou
    COS B-2) não tem recursos próprios suficientes e tem um patrocinador
    LPR/cidadão qualificado (ver as perguntas i134_recursos_suficientes /
    i134_tem_patrocinador_qualificado no questionário do I-539). Serviço
    cobrado à parte pelo negócio -- USCIS não cobra taxa pelo I-134, ver
    data/registry.json. Mesma arquitetura de add_dependent() acima: zero
    código novo no motor do wizard, só mais um FormSubmission com
    parent_submission_id preenchido."""
    parent = _get_owned_submission(parent_submission_id)
    if parent.form_slug != "i-539":
        abort(400)
    if "i-134" not in ENABLED_FORMS:
        abort(404)

    # Um único I-134 cobre o caso inteiro (inclusive dependentes I-539A do
    # mesmo pedido) -- não deixa criar um segundo por engano (duplo clique,
    # replay do POST etc.), só reabre o que já existe.
    existing = (
        SessionLocal.query(FormSubmission)
        .filter_by(user_id=current_user.id, form_slug="i-134", parent_submission_id=parent.id)
        .first()
    )
    if existing:
        return redirect(url_for("wizard.wizard_view", submission_id=existing.id))

    sponsor_submission = FormSubmission(
        user_id=current_user.id, form_slug="i-134",
        parent_submission_id=parent.id, package_slug=parent.package_slug,
    )
    sponsor_submission.set_answers({})
    SessionLocal.add(sponsor_submission)
    SessionLocal.commit()
    return redirect(url_for("wizard.wizard_view", submission_id=sponsor_submission.id))


RECEIPT_NUMBER_RE = re.compile(r"^[A-Z]{3}\d{10}$")


@wizard_bp.route("/wizard/<int:submission_id>/recibo", methods=["POST"])
@login_required
def save_receipt_number(submission_id: int):
    """Salva o número de recibo do USCIS digitado pelo usuário para esta
    submissão -- só um atalho de conveniência para o link de status oficial
    no dashboard, nunca usado para consultar o USCIS automaticamente (ver
    o comentário em FormSubmission.receipt_number)."""
    submission = _get_owned_submission(submission_id)
    from app.i18n import t

    raw = request.form.get("receipt_number", "").strip().upper().replace(" ", "").replace("-", "")

    if raw and not RECEIPT_NUMBER_RE.match(raw):
        flash(t("receipt_invalid_format"), "error")
        return redirect(url_for("wizard.dashboard"))

    submission.receipt_number = raw or None
    SessionLocal.commit()
    return redirect(url_for("wizard.dashboard"))


@wizard_bp.route("/wizard/<int:submission_id>")
@login_required
def wizard_view(submission_id: int):
    submission = _get_owned_submission(submission_id)
    qdata = _load_questionnaire(submission.form_slug)
    answers = submission.get_answers()
    skipped = submission.get_skipped()
    autofilled = submission.get_autofilled()
    # Uma pergunta autopreenchida ainda não confirmada conta como "não
    # respondida" pro fluxo linear -- assim ela aparece como a etapa atual
    # (com o valor já preenchido + aviso, ver abaixo) em vez de ser pulada
    # silenciosamente. Sai de `autofilled` assim que o usuário passa por ela
    # (ver _apply_answer), então isso só acontece uma vez por campo.
    handled = (answers.keys() | skipped) - autofilled.keys()

    active = active_questions(qdata["questions"], answers)
    total = len(active)
    current_idx = next((i for i, q in enumerate(active) if q["id"] not in handled), None)

    if current_idx is None:
        return redirect(url_for("wizard.review", submission_id=submission.id))

    current = active[current_idx]
    prev_question_id = active[current_idx - 1]["id"] if current_idx > 0 else None

    answered_count = sum(1 for q in active if q["id"] in handled)
    autofill_source = autofilled.get(current["id"])
    from app.i18n import get_lang
    return render_template(
        "wizard_step.html",
        submission=submission,
        question=current,
        answered_count=answered_count,
        total=total,
        us_states=US_STATES,
        current_value=answers.get(current["id"]) if autofill_source else None,
        edit_mode=False,
        prev_question_id=prev_question_id,
        form_translated=_questionnaire_has_translation(submission.form_slug, get_lang()),
        autofill_source_name=_form_display_name(autofill_source) if autofill_source else None,
        form_name=_form_display_name(submission.form_slug),
        section_title=_section_title(qdata, current),
    )


def _apply_answer(submission: FormSubmission, qdata: dict) -> str | None:
    """Valida e salva a resposta enviada no POST atual (request.form).
    Retorna uma mensagem de erro (e não salva nada) se a validação falhar,
    ou None em caso de sucesso. Compartilhado entre o fluxo linear do
    wizard (/answer) e a edição pontual de uma resposta já dada
    (/edit/<question_id>) -- a única diferença entre os dois é para onde
    redirecionar depois, não a lógica de validação/gravação em si."""
    answers = submission.get_answers()
    skipped = submission.get_skipped()
    autofilled = submission.get_autofilled()

    question_id = request.form.get("question_id")
    question = next((q for q in qdata["questions"] if q["id"] == question_id), None)
    if question is None:
        abort(400)

    qtype = question["type"]
    required = bool(question.get("required"))

    if qtype == "checkbox_group":
        values = request.form.getlist(question_id)
        has_value = bool(values)
        value = values
    else:
        raw = request.form.get(question_id, "").strip()
        has_value = bool(raw)
        value = raw

    if qtype == "select" and has_value:
        value = value.upper()
        if value not in US_STATES:
            return "Sigla de estado inválida."

    if qtype == "date" and has_value:
        if not DATE_RE.match(value):
            return "Data inválida. Use o formato MM/DD/AAAA."

    if not has_value:
        if required:
            return "Este campo é obrigatório."
        answers.pop(question_id, None)
        skipped.add(question_id)
    else:
        answers[question_id] = value
        skipped.discard(question_id)

    if question_id in autofilled:
        autofilled.pop(question_id)
        submission.set_autofilled(autofilled)

    submission.set_answers(answers)
    submission.set_skipped(skipped)
    SessionLocal.commit()
    return None


@wizard_bp.route("/wizard/<int:submission_id>/answer", methods=["POST"])
@login_required
def answer(submission_id: int):
    submission = _get_owned_submission(submission_id)
    qdata = _load_questionnaire(submission.form_slug)

    error = _apply_answer(submission, qdata)
    if error:
        flash(error, "error")

    return redirect(url_for("wizard.wizard_view", submission_id=submission.id))


@wizard_bp.route("/wizard/<int:submission_id>/edit/<question_id>")
@login_required
def edit_question(submission_id: int, question_id: str):
    submission = _get_owned_submission(submission_id)
    qdata = _load_questionnaire(submission.form_slug)
    question = next((q for q in qdata["questions"] if q["id"] == question_id), None)
    if question is None:
        abort(404)

    # `next` diz pra onde ir depois de salvar: "wizard" quando chegou aqui
    # clicando em "voltar à pergunta anterior" (continua o fluxo normal a
    # partir dali), "review" (padrão) quando veio da tela de revisão.
    next_target = request.args.get("next", "review")
    answers = submission.get_answers()
    from app.i18n import get_lang
    return render_template(
        "wizard_step.html",
        submission=submission,
        question=question,
        current_value=answers.get(question_id),
        edit_mode=True,
        next_target=next_target,
        us_states=US_STATES,
        form_translated=_questionnaire_has_translation(submission.form_slug, get_lang()),
        form_name=_form_display_name(submission.form_slug),
        section_title=_section_title(qdata, question),
    )


@wizard_bp.route("/wizard/<int:submission_id>/edit/<question_id>", methods=["POST"])
@login_required
def edit_question_save(submission_id: int, question_id: str):
    submission = _get_owned_submission(submission_id)
    qdata = _load_questionnaire(submission.form_slug)
    next_target = request.form.get("next", "review")

    error = _apply_answer(submission, qdata)
    if error:
        flash(error, "error")
        return redirect(url_for("wizard.edit_question",
                                 submission_id=submission.id, question_id=question_id,
                                 next=next_target))

    if next_target == "wizard":
        return redirect(url_for("wizard.wizard_view", submission_id=submission.id))

    return redirect(url_for("wizard.review", submission_id=submission.id))


@wizard_bp.route("/wizard/<int:submission_id>/review")
@login_required
def review(submission_id: int):
    submission = _get_owned_submission(submission_id)
    answers = submission.get_answers()
    qdata = _load_questionnaire(submission.form_slug)

    active = active_questions(qdata["questions"], answers)
    # Reimplementado localmente (em vez de reaproveitar
    # missing_required_fields de pdf_service.py) só pra usar os rótulos já
    # traduzidos de `qdata` -- aquele helper lê o questionário original em
    # português direto do disco, então os rótulos ficariam em português
    # mesmo com o site em inglês.
    missing = [q["label"].rstrip(" *") for q in active
               if q.get("required") and q["id"] not in answers]

    answered = []
    for q in active:
        if q["id"] not in answers:
            continue
        value = answers[q["id"]]
        display = _display_value(q, value)
        answered.append((q, display))

    from app.i18n import get_lang
    return render_template(
        "review.html", submission=submission, missing=missing, answered=answered,
        form_translated=_questionnaire_has_translation(submission.form_slug, get_lang()))


@wizard_bp.route("/wizard/<int:submission_id>/generate", methods=["POST"])
@login_required
def generate(submission_id: int):
    from app.i18n import get_lang
    submission = _get_owned_submission(submission_id)
    answers = submission.get_answers()
    missing = missing_required_fields(submission.form_slug, answers)
    if missing:
        flash("Ainda há campos obrigatórios sem resposta.", "error")
        return redirect(url_for("wizard.review", submission_id=submission.id))

    lang = get_lang()
    out_dir = _submission_dir(submission)

    if submission.form_slug == "i-539-cartas":
        _generate_cartas(submission, answers, out_dir)
    else:
        pdf_path = out_dir / f"{submission.form_slug}-preenchido.pdf"
        fill_form_for_submission(submission.form_slug, answers, pdf_path, patch_xfa=True)
        checklist_path = generate_checklist_for_submission(submission.form_slug, out_dir, lang=lang)

        submission.filled_pdf_path = str(pdf_path)
        submission.checklist_pdf_path = str(checklist_path)

        if document_checklist_available(submission.form_slug):
            documents_path = generate_document_checklist_for_submission(
                submission.form_slug, answers, out_dir, lang=lang)
            submission.documents_pdf_path = str(documents_path)

    submission.status = "completed"
    from datetime import datetime, timezone
    submission.completed_at = datetime.now(timezone.utc)
    SessionLocal.commit()

    flash("PDF e checklist gerados com sucesso.", "success")
    return redirect(url_for("wizard.review", submission_id=submission.id))


def _generate_cartas(submission: FormSubmission, answers: dict, out_dir: Path) -> None:
    """Gera o resumo da narrativa + as cartas complementares aplicáveis
    (scripts/generate_cartas_i539.py) e empacota tudo num único zip -- o
    modelo FormSubmission só tem colunas fixas para um PDF por vez, e aqui
    o número de documentos gerados varia por caso (0 a 5)."""
    import zipfile
    from scripts.generate_cartas_i539 import generate_all

    cartas_dir = out_dir / "cartas"
    generated = generate_all(answers, cartas_dir)

    zip_path = out_dir / "i-539-cartas-complementares.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in generated:
            zf.write(f, arcname=f.name)

    submission.cartas_zip_path = str(zip_path) if generated else None


@wizard_bp.route("/wizard/<int:submission_id>/download/pdf")
@login_required
def download_pdf(submission_id: int):
    submission = _get_owned_submission(submission_id)
    if not submission.filled_pdf_path:
        abort(404)
    return send_file(submission.filled_pdf_path, as_attachment=True)


@wizard_bp.route("/wizard/<int:submission_id>/download/checklist")
@login_required
def download_checklist(submission_id: int):
    submission = _get_owned_submission(submission_id)
    if not submission.checklist_pdf_path:
        abort(404)
    return send_file(submission.checklist_pdf_path, as_attachment=True)


@wizard_bp.route("/wizard/<int:submission_id>/download/cartas")
@login_required
def download_cartas(submission_id: int):
    submission = _get_owned_submission(submission_id)
    if not submission.cartas_zip_path:
        abort(404)
    return send_file(submission.cartas_zip_path, as_attachment=True)


@wizard_bp.route("/wizard/<int:submission_id>/download/documents")
@login_required
def download_documents(submission_id: int):
    submission = _get_owned_submission(submission_id)
    if not submission.documents_pdf_path:
        abort(404)
    return send_file(submission.documents_pdf_path, as_attachment=True)
