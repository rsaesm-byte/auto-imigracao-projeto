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
import shutil
from pathlib import Path

from flask import (Blueprint, abort, flash, redirect, render_template,
                    request, send_file, session, url_for)
from flask_login import current_user, login_required

from app.crm_models import Case, Client, VisaDraftType
from app.db import SessionLocal
from app.i18n import SUPPORTED_LANGS
from app.models import FormSubmission, Payment
from app.services.news_service import get_latest_news
from app.services.pdf_service import (document_checklist_available,
                                       fill_form_for_submission,
                                       generate_carta_letter_for_submission,
                                       generate_checklist_for_submission,
                                       generate_document_checklist_for_submission,
                                       generate_narrative_letter_for_submission,
                                       missing_required_fields)
from scripts.run_questionnaire import DATE_RE, US_STATES, active_questions

wizard_bp = Blueprint("wizard", __name__)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_USERS_DIR = ROOT / "output" / "users"

# todos os formulários do projeto, na ordem em que aparecem na página
# inicial e no dashboard. "i-539-cartas" é um pseudo-formulário: não tem PDF
# oficial/mapping próprio (ver PDF_BACKED_FORMS abaixo) -- gera só a carta
# narrativa pessoal via scripts/generate_cartas_i539.py, não
# scripts/fill_form.py. As 4 cartas de terceiro (endereço/patrocínio/
# empregador/responsável pela empresa) que antes vinham juntas nessa mesma
# submissão viraram formulários próprios (CARTA_LETTER_SLUGS abaixo),
# vinculados a este caso via parent_submission_id -- mesmo padrão do
# I-539A/I-134 (ver add_carta_letter).
FORM_SLUGS_ORDER = ["i-130", "i-130a", "i-485", "i-765", "i-131", "i-864", "i-751",
                    "i-90", "n-400", "i-539", "i-134", "i-539-cartas"]

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
#
# O I-134 morava aqui até 2026-07-26 (só alcançável via wizard.add_i134, a
# partir de uma submissão I-539 existente). Passou para FORM_SLUGS_ORDER a
# pedido do usuário: agora também tem página própria em /servicos/i-134
# (data/service_pages/i-134.json) e aparece na grade principal como
# qualquer outro formulário -- o atalho "adicionar ao I-539" continua
# funcionando do mesmo jeito, em paralelo.
# As 4 cartas de terceiro do I-539, cada uma um formulário próprio vinculado
# a um caso "I-539 — Cartas Complementares" (parent_submission_id) -- ver
# add_carta_letter() e _cartas_case(). Nome de exibição próprio (não vem do
# registry.json oficial da USCIS, já que essas cartas não são formulários
# oficiais) por idioma, mesmo padrão de CARTAS_DISPLAY_NAME abaixo.
CARTA_LETTER_SLUGS = [
    "i539-carta-endereco", "i539-carta-patrocinio",
    "i539-carta-empregador", "i539-carta-empresa",
]

# "ds160" também não tem página de serviço/formulário público próprio --
# de propósito (pedido do usuário): só fica alcançável quando a equipe
# marca no CRM que o cliente contratou visto B1/B2 ou F1/F2
# (Case.ds160_visa_type, ver app/crm_models.py::VisaDraftType). Ver
# _ds160_gate_case()/dashboard() abaixo pro gate, e start() pra
# re-checagem de segurança (não basta esconder o link -- a rota em si
# recusa sem o gate).
AUXILIARY_FORM_SLUGS = ["g-1145", "g-1450", "g-1650", "i-539a", "ds160"] + CARTA_LETTER_SLUGS

CARTA_LETTER_DISPLAY_NAME = {
    "i539-carta-endereco": {
        "pt": "Carta de Confirmação de Endereço",
        "en": "Address Confirmation Letter",
        "es": "Carta de Confirmación de Dirección",
    },
    "i539-carta-patrocinio": {
        "pt": "Carta de Patrocínio Financeiro",
        "en": "Financial Sponsorship Letter",
        "es": "Carta de Patrocinio Financiero",
    },
    "i539-carta-empregador": {
        "pt": "Carta do Empregador",
        "en": "Employer Letter",
        "es": "Carta del Empleador",
    },
    "i539-carta-empresa": {
        "pt": "Carta de Responsável pela Empresa",
        "en": "Business Caretaker Letter",
        "es": "Carta del Responsable de la Empresa",
    },
}

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

CARTAS_DISPLAY_NAME = {
    "pt": "I-539 — Cartas Complementares",
    "en": "I-539 — Supplementary Letters",
    "es": "I-539 — Cartas Complementarias",
}

DS160_DISPLAY_NAME = {
    "pt": "Rascunho — Visto Americano (DS-160)",
    "en": "Draft — US Visa (DS-160)",
    "es": "Borrador — Visa Americana (DS-160)",
}

# Vistos de não-imigrante vendidos pela Saes -- listados em /servicos a
# pedido do usuário, mas SEM botão de autoatendimento (diferente de todo
# outro item de FORM_SLUGS_ORDER): o processo é conduzido pela equipe do
# início ao fim (contrata -> equipe abre o Case no CRM -> só then o
# rascunho de DS-160 é liberado, ver AUXILIARY_FORM_SLUGS/_ds160_gate_case
# acima). "Começar" aqui vira "Fale com a equipe" no template, nunca
# wizard.start -- por isso NÃO entram em FORM_SLUGS_ORDER/ENABLED_FORMS.
VISA_SERVICE_SLUGS = ["visto-b1-b2", "visto-f1-f2"]

VISA_SERVICE_DISPLAY_NAME = {
    "visto-b1-b2": {"pt": "Visto B1/B2 — Turismo e Negócios",
                     "en": "B1/B2 Visa — Tourism and Business",
                     "es": "Visa B1/B2 — Turismo y Negocios"},
    "visto-f1-f2": {"pt": "Visto F1/F2 — Estudante",
                     "en": "F1/F2 Visa — Student",
                     "es": "Visa F1/F2 — Estudiante"},
}


def _load_questionnaire(slug: str) -> dict:
    """Carrega o questionário em português e, se o idioma da sessão não for
    português e existir um overlay de tradução para esse formulário e
    idioma (data/translations/<slug>.<lang>.json, ex. <slug>.en.json ou
    <slug>.es.json), aplica label/hint/opções por cima -- sem tocar no
    arquivo original em português. Um formulário sem overlay num dado
    idioma continua em português mesmo com o site nesse idioma (o próprio
    wizard avisa isso, ver _questionnaire_has_translation)."""
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


def _load_reviews() -> dict:
    """Avaliações reais do Google (Saes Professional Services), fixas em
    data/reviews.json -- texto original do cliente, sem tradução por
    idioma (mesma convenção de um depoimento real: mantém a língua em que
    foi escrito)."""
    import json
    return json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8"))


def _form_display_name(slug: str, lang: str | None = None) -> str:
    """Nome do formulário na vitrine (landing/dashboard) -- em inglês
    quando o site está em inglês, já que o nome oficial do formulário é
    em inglês mesmo (é o nome real que a USCIS usa); traduzido (name_pt/
    name_es) nos outros idiomas, com fallback pro nome em português se o
    idioma atual ainda não tiver essa variante preenchida no registro.
    `lang` força um idioma específico (usado pela mensagem do WhatsApp em
    app/payment_gate.py, que precisa do rótulo sempre em inglês
    independente do idioma da sessão) -- por padrão usa o idioma da sessão."""
    from app.i18n import DEFAULT_LANG, get_lang
    lang = lang or get_lang()
    if slug == "i-539-cartas":
        return CARTAS_DISPLAY_NAME.get(lang, CARTAS_DISPLAY_NAME[DEFAULT_LANG])
    if slug == "ds160":
        return DS160_DISPLAY_NAME.get(lang, DS160_DISPLAY_NAME[DEFAULT_LANG])
    if slug in VISA_SERVICE_DISPLAY_NAME:
        names = VISA_SERVICE_DISPLAY_NAME[slug]
        return names.get(lang, names[DEFAULT_LANG])
    if slug in CARTA_LETTER_DISPLAY_NAME:
        names = CARTA_LETTER_DISPLAY_NAME[slug]
        return names.get(lang, names[DEFAULT_LANG])
    entry = _load_registry_entry(slug)
    if lang == "en":
        return entry.get("name", slug.upper())
    if lang != DEFAULT_LANG:
        alt = entry.get(f"name_{lang}")
        if alt:
            return alt
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
        note = entry.get(f"reference_only_note_{lang}") if lang != "pt" else None
        note = note or entry.get("reference_only_note")
        catalog.append({
            "slug": slug, "name": _form_display_name(slug), "reference": True,
            "enabled": False, "reference_note": note,
            "civil_surgeon_url": entry.get("civil_surgeon_finder_url"),
        })
    return render_template("index.html", catalog=catalog, news_items=get_latest_news(),
                           reviews=_load_reviews())


@wizard_bp.route("/servicos")
def services():
    catalog = [
        {"slug": slug, "name": _form_display_name(slug),
         "enabled": slug in ENABLED_FORMS, "contact_only": False}
        for slug in FORM_SLUGS_ORDER
    ]
    catalog += [
        {"slug": slug, "name": _form_display_name(slug), "enabled": False, "contact_only": True}
        for slug in VISA_SERVICE_SLUGS
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
    "i134_notice_title", "i134_notice_body",
    "sevis_fee_title", "sevis_fee_intro", "sevis_fee_facts",
    "sevis_fee_video_caption", "sevis_fee_disclaimer",
    "school_search_title", "school_search_body", "school_search_link_label",
]


def _load_service_content(slug: str) -> dict:
    """Carrega data/service_pages/<slug>.json e resolve os campos para o
    idioma atual da sessão (cada campo tem uma variante <campo>_<lang>, ex.
    <campo>_en/<campo>_es; sem overlay -- este conteúdo é próprio, não uma
    tradução por cima de um original, diferente do padrão usado nos
    questionários). Cai pro campo em português (sem sufixo) se a variante do
    idioma atual não existir."""
    import json
    from app.i18n import DEFAULT_LANG, get_lang

    path = ROOT / "data" / "service_pages" / f"{slug}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    lang = get_lang()
    return {
        field: raw.get(f"{field}_{lang}") if lang != DEFAULT_LANG and raw.get(f"{field}_{lang}") is not None
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
    if slug not in FORM_SLUGS_ORDER and slug not in VISA_SERVICE_SLUGS:
        abort(404)
    content_path = ROOT / "data" / "service_pages" / f"{slug}.json"
    if not content_path.exists():
        abort(404)

    content = _load_service_content(slug)
    registry_entry = {} if slug == "i-539-cartas" or slug in VISA_SERVICE_SLUGS else _load_registry_entry(slug)
    related_catalog = [
        {"slug": s, "name": _form_display_name(s)}
        for s in FORM_SLUGS_ORDER if s != slug
    ]

    calc_result, calc_error, calc_form = _run_filing_date_calculator(slug)

    from app.services.pricing import in_package_price_cents, individual_price_cents

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
        our_fee_individual=individual_price_cents(slug),
        our_fee_package=in_package_price_cents(slug),
        contact_only=slug in VISA_SERVICE_SLUGS,
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

    # "ds160" nunca entra no catalog público acima -- só aparece aqui
    # quando a equipe já marcou o gate no CRM (ver _ds160_gate_case) e o
    # usuário ainda não tem nenhuma submissão desse slug (uma vez criada,
    # ela já aparece sozinha na tabela "Em andamento" via `submissions`
    # genérico, sem precisar de nada especial aqui).
    ds160_gate_case = _ds160_gate_case(current_user.id)
    ds160_already_started = any(s.form_slug == "ds160" for s in submissions)

    return render_template("dashboard.html", submissions=top_level, catalog=catalog,
                           dependents_by_parent=dependents_by_parent,
                           dependent_form_enabled=("i-539a" in ENABLED_FORMS),
                           i134_form_enabled=("i-134" in ENABLED_FORMS),
                           carta_letters_enabled=all(s in ENABLED_FORMS for s in CARTA_LETTER_SLUGS),
                           carta_letter_slugs=CARTA_LETTER_SLUGS,
                           ds160_gate_case=None if ds160_already_started else ds160_gate_case,
                           news_items=get_latest_news())


@wizard_bp.route("/forms/<slug>/start")
@login_required
def start(slug: str):
    if slug not in ENABLED_FORMS:
        abort(404)
    if slug in CARTA_LETTER_SLUGS:
        # Só alcançáveis a partir de um caso "I-539 — Cartas Complementares"
        # já existente (ver add_carta_letter) -- nunca direto, senão a
        # submissão nasceria órfã (sem parent_submission_id) e _cartas_case()
        # não teria como aplicar o gate de pagamento a ela.
        abort(404)

    ds160_case = None
    if slug == "ds160":
        # Re-checagem de verdade, não só esconder o link: mesmo que o
        # usuário descubra/salve esta URL, sem o gate marcado no CRM
        # (ver _ds160_gate_case) a rota recusa igual.
        ds160_case = _ds160_gate_case(current_user.id)
        if ds160_case is None:
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
    if slug == "ds160" and ds160_case is not None:
        # A equipe já sabe qual visto é (marcou o gate) -- pré-preenche
        # pra não perguntar de novo, mas o cliente ainda pode conferir/
        # mudar na primeira pergunta do questionário.
        prefill["tipo_visto"] = ds160_case.ds160_visa_type.value
        submission.case_id = ds160_case.id
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
    if slug in CARTA_LETTER_SLUGS:
        abort(404)
    submission = FormSubmission(user_id=current_user.id, form_slug=slug)
    prefill, sources = _build_autofill(current_user.id, slug)
    submission.set_answers(prefill)
    submission.set_autofilled(sources)
    SessionLocal.add(submission)
    SessionLocal.commit()
    return redirect(url_for("wizard.wizard_view", submission_id=submission.id))


@wizard_bp.route("/comecar-para-outra-pessoa")
@login_required
def start_for_other():
    """Página dedicada (link de destaque no dashboard) para o usuário
    escolher qual formulário preencher para OUTRA pessoa -- cada tile aqui
    aponta pra wizard.new_attempt (sempre cria uma submissão nova),
    diferente da grade normal do dashboard que aponta pra wizard.start
    (retoma a submissão em andamento do próprio usuário, se houver)."""
    catalog = [
        {"slug": slug, "name": _form_display_name(slug)}
        for slug in list(FORM_SLUGS_ORDER) + MAIN_GRID_EXTRA_SLUGS
    ]
    return render_template("start_for_other.html", catalog=catalog)


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


@wizard_bp.route("/wizard/<int:parent_submission_id>/cartas/<kind>/adicionar", methods=["POST"])
@login_required
def add_carta_letter(parent_submission_id: int, kind: str):
    """Cria uma nova submissão para uma das 4 cartas de terceiro do I-539
    (endereco/patrocinio/empregador/empresa), vinculada ao caso "I-539 —
    Cartas Complementares" (parent_submission_id) -- mesma arquitetura de
    add_dependent()/add_i134() acima: zero código novo no motor do wizard,
    só mais um FormSubmission com parent_submission_id preenchido. `kind` é
    o sufixo depois de "i539-carta-" (endereco/patrocinio/empregador/
    empresa), nunca o slug inteiro, pra manter a URL curta.

    O nome completo do requerente já digitado na narrativa é copiado como
    pré-preenchimento (mesmo mecanismo de "autofilled" usado pelo
    cross-form autofill em _build_autofill, então a UI mostra o aviso
    normal de "auto-preenchido" e o usuário sempre confirma antes de
    seguir) -- assim a pessoa não digita o próprio nome de novo em cada
    carta."""
    parent = _get_owned_submission(parent_submission_id)
    if parent.form_slug != "i-539-cartas":
        abort(400)
    slug = f"i539-carta-{kind}"
    if slug not in CARTA_LETTER_SLUGS or slug not in ENABLED_FORMS:
        abort(404)

    # Só uma de cada carta por caso -- não deixa criar uma segunda por
    # engano (duplo clique, replay do POST etc.), só reabre a que já existe.
    existing = (
        SessionLocal.query(FormSubmission)
        .filter_by(user_id=current_user.id, form_slug=slug, parent_submission_id=parent.id)
        .first()
    )
    if existing:
        return redirect(url_for("wizard.wizard_view", submission_id=existing.id))

    letter_submission = FormSubmission(
        user_id=current_user.id, form_slug=slug,
        parent_submission_id=parent.id, package_slug=parent.package_slug,
    )
    applicant_name = parent.get_answers().get("nome_completo_requerente")
    if applicant_name:
        letter_submission.set_answers({"nome_completo_requerente": applicant_name})
        letter_submission.set_autofilled({"nome_completo_requerente": parent.form_slug})
    else:
        letter_submission.set_answers({})
    SessionLocal.add(letter_submission)
    SessionLocal.commit()
    return redirect(url_for("wizard.wizard_view", submission_id=letter_submission.id))


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


@wizard_bp.route("/wizard/<int:submission_id>/apagar", methods=["POST"])
@login_required
def delete_submission(submission_id: int):
    """Apaga permanentemente uma submissão a pedido do usuário no dashboard --
    inclusive qualquer dependente vinculado (I-539A, I-134) e os arquivos já
    gerados em output/users/. Não existia nenhuma forma de desfazer um
    formulário começado por engano antes desta rota."""
    from app.i18n import t
    submission = _get_owned_submission(submission_id)

    children = (
        SessionLocal.query(FormSubmission)
        .filter_by(parent_submission_id=submission.id)
        .all()
    )

    # Um Payment (histórico de cobrança de verdade, ver app/models.py) pode
    # apontar pra esta submissão ou por um de seus dependentes via
    # submission_id -- desde que app/db.py passou a ligar
    # PRAGMA foreign_keys=ON, apagar a submissão sem soltar essa referência
    # primeiro quebraria o commit abaixo com IntegrityError. O pagamento em
    # si nunca é apagado (dinheiro de verdade já trocou de mãos), só perde
    # a referência pra uma submissão que não existe mais.
    submission_ids = [submission.id] + [c.id for c in children]
    (SessionLocal.query(Payment)
     .filter(Payment.submission_id.in_(submission_ids))
     .update({Payment.submission_id: None}, synchronize_session=False))

    for child in children:
        shutil.rmtree(_submission_dir(child), ignore_errors=True)
        SessionLocal.delete(child)

    shutil.rmtree(_submission_dir(submission), ignore_errors=True)
    SessionLocal.delete(submission)
    SessionLocal.commit()
    flash(t("submission_deleted"), "success")
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

    cartas_case = _cartas_case(submission)

    payment_case = _payment_case(submission)
    payment_status = None
    payment_amount_display = None
    checkout_url = None
    if payment_case is not None:
        from app.services.pricing import find_payment_for_case
        payment = find_payment_for_case(payment_case)
        payment_status = payment.status if payment is not None else "unpaid"
        payment_amount_display = f"${payment_case.price_cents / 100:,.2f}"
        checkout_url = url_for("payment_gate.checkout", submission_id=submission.id)

    from app.i18n import get_lang
    return render_template(
        "review.html", submission=submission, missing=missing, answered=answered,
        form_translated=_questionnaire_has_translation(submission.form_slug, get_lang()),
        cartas_case_paid=(cartas_case.paid if cartas_case is not None else None),
        payment_status=payment_status, payment_amount_display=payment_amount_display,
        checkout_url=checkout_url)


def _ds160_gate_case(user_id: int) -> Case | None:
    """Caso do CRM (app/crm_models.py) que libera o rascunho de DS-160 para
    este usuário -- None enquanto nenhuma equipe marcou
    Case.ds160_visa_type (ver app/crm_staff_pipeline.py::
    case_ds160_gate_update). Usado tanto pra decidir se o tile aparece no
    dashboard quanto, de novo, dentro de start() -- esconder o link não
    basta, a rota tem que recusar sozinha (ver docstring de
    AUXILIARY_FORM_SLUGS)."""
    client = SessionLocal.query(Client).filter_by(user_id=user_id).first()
    if client is None:
        return None
    return (
        SessionLocal.query(Case)
        .filter(Case.client_id == client.id, Case.ds160_visa_type.is_not(None))
        .order_by(Case.updated_at.desc())
        .first()
    )


def _cartas_case(submission: FormSubmission) -> FormSubmission | None:
    """Devolve a submissão "I-539 — Cartas Complementares" que rege o
    pagamento de `submission`: ela mesma, se `submission` já for o caso; a
    submissão-pai, se `submission` for uma das 4 cartas de terceiro
    vinculadas (ver CARTA_LETTER_SLUGS); None para qualquer outro
    formulário (não gated por pagamento). Não confundir com o `parent`
    genérico do I-539A/I-134 -- só as Cartas Complementares têm gate de
    pagamento hoje."""
    if submission.form_slug == "i-539-cartas":
        return submission
    if submission.form_slug in CARTA_LETTER_SLUGS and submission.parent_submission_id:
        return SessionLocal.get(FormSubmission, submission.parent_submission_id)
    return None


def _payment_case(submission: FormSubmission):
    """Caso de pagamento genérico (Zelle/Venmo/cartão/wire + comprovante,
    ver app/payment_gate.py) para qualquer formulário avulso ou pacote com
    preço em data/service_fees.json -- nunca para as Cartas Complementares
    do I-539, que têm o gate mais simples de _cartas_case() acima. Devolve
    None quando não há gate (Cartas/carta de terceiro, ou preço não
    definido -- ex.: formulários vendidos "somente em pacote" quando
    preenchidos avulsos, fora do fluxo normal de /pacotes).

    I-134 é tratado à parte: nunca herda o caso do I-539 pai (ao contrário
    de todo outro dependente, que soma no caso da raiz via `root` abaixo)
    porque seu preço muda conforme o contexto -- $75 quando o I-539 pai
    pertence a um pacote de mudança/extensão de status (EOS/COS), $100
    quando o I-539 pai foi preenchido avulso (decisão do usuário,
    2026-07-31)."""
    from app.services.pricing import (PaymentCase, in_package_price_cents,
                                       individual_price_cents, package_display_name,
                                       package_price_cents)
    if submission.form_slug in ("i-539-cartas", "ds160") or submission.form_slug in CARTA_LETTER_SLUGS:
        return None
    if submission.form_slug == "i-134":
        price = (in_package_price_cents("i-134") if submission.package_slug
                  else individual_price_cents("i-134"))
        if not price:
            return None
        return PaymentCase(kind="form", key=str(submission.id), price_cents=price,
                            label=_form_display_name("i-134"),
                            label_en=_form_display_name("i-134", lang="en"))
    if submission.package_slug:
        price = package_price_cents(submission.package_slug)
        if not price:
            return None
        return PaymentCase(kind="package", key=submission.package_slug, price_cents=price,
                            label=package_display_name(submission.package_slug),
                            label_en=package_display_name(submission.package_slug, lang="en"))
    root = submission
    while root.parent_submission_id:
        root = SessionLocal.get(FormSubmission, root.parent_submission_id)
    price = individual_price_cents(root.form_slug)
    if not price:
        return None
    return PaymentCase(kind="form", key=str(root.id), price_cents=price,
                        label=_form_display_name(root.form_slug),
                        label_en=_form_display_name(root.form_slug, lang="en"))


def _payment_status_for(submission: FormSubmission) -> str | None:
    """Usado pelos templates (registrado como global Jinja `payment_status_for`
    em app/__init__.py) para mostrar o selo de pagamento no dashboard --
    None quando o formulário não é gated, senão "unpaid"/"pending"/"confirmed"."""
    from app.services.pricing import find_payment_for_case
    case = _payment_case(submission)
    if case is None:
        return None
    payment = find_payment_for_case(case)
    return payment.status if payment is not None else "unpaid"


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

    cartas_case = _cartas_case(submission)
    if cartas_case is not None and not cartas_case.paid:
        flash("Este caso ainda aguarda confirmação de pagamento. Entre em contato "
              "com a nossa equipe para liberar a geração das cartas.", "error")
        return redirect(url_for("wizard.review", submission_id=submission.id))

    payment_case = _payment_case(submission)
    if payment_case is not None:
        from app.services.pricing import find_payment_for_case
        payment = find_payment_for_case(payment_case)
        if payment is None or payment.status != "confirmed":
            flash("Este caso ainda aguarda confirmação de pagamento. Finalize o "
                  "pagamento para liberar a geração do documento.", "error")
            return redirect(url_for("wizard.review", submission_id=submission.id))

    lang = get_lang()
    out_dir = _submission_dir(submission)

    if submission.form_slug == "i-539-cartas":
        pdf_path = out_dir / "i-539-carta-narrativa.pdf"
        result = generate_narrative_letter_for_submission(answers, pdf_path)
        submission.filled_pdf_path = str(result) if result else None
    elif submission.form_slug in CARTA_LETTER_SLUGS:
        pdf_path = out_dir / f"{submission.form_slug}.pdf"
        result = generate_carta_letter_for_submission(submission.form_slug, answers, pdf_path)
        submission.filled_pdf_path = str(result) if result else None
    elif submission.form_slug == "ds160":
        from scripts.generate_ds160_draft import build_ds160_draft
        pdf_path = out_dir / "ds160-rascunho.pdf"
        client_name = " ".join(filter(None, [
            answers.get("nome_passaporte"), answers.get("sobrenome_passaporte")])) or current_user.email
        build_ds160_draft(answers, pdf_path, client_name=client_name)
        submission.ds160_draft_pdf_path = str(pdf_path)
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
    """OBSOLETO desde 2026-07-31 (as 4 cartas de terceiro viraram
    formulários próprios, ver CARTA_LETTER_SLUGS) -- generate() não chama
    mais esta função para submissões novas. Mantida só porque
    download_cartas()/cartas_zip_path ainda servem zips já gerados antes
    dessa mudança; não apagar sem migrar esses registros antigos."""
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


@wizard_bp.route("/wizard/<int:submission_id>/download/ds160")
@login_required
def download_ds160(submission_id: int):
    submission = _get_owned_submission(submission_id)
    if not submission.ds160_draft_pdf_path:
        abort(404)
    return send_file(submission.ds160_draft_pdf_path, as_attachment=True)


@wizard_bp.route("/wizard/<int:submission_id>/download/documents")
@login_required
def download_documents(submission_id: int):
    submission = _get_owned_submission(submission_id)
    if not submission.documents_pdf_path:
        abort(404)
    return send_file(submission.documents_pdf_path, as_attachment=True)
