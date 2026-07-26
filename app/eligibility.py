"""Blueprint dos quizzes públicos de pré-triagem de elegibilidade.

Diferente do wizard principal (app/wizard.py), aqui não há login nem
persistência em banco -- as respostas ficam só na sessão do navegador
(session["elig_answers"][slug]), o que é deliberado: é um formulário curto
de triagem respondido antes de o visitante criar conta, e reduzir a coleta
de PII a "o mínimo necessário, pelo tempo necessário" é a própria política
de privacidade do produto (ver references/compliance.md). O resultado é um
veredito informativo (elegível / requer atenção / não é o serviço certo),
nunca uma promessa de aprovação -- ver o aviso fixo em eligibility_result.html.
"""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from app.services.eligibility_rules import EVALUATORS
from scripts.run_questionnaire import DATE_RE, active_questions

eligibility_bp = Blueprint("eligibility", __name__, url_prefix="/elegibilidade")

ROOT = Path(__file__).resolve().parent.parent
QUIZ_SLUGS = ["cidadania", "gc-roc", "gc-aos", "gc-consular"]


def _load_quiz(slug: str) -> dict:
    path = ROOT / "data" / "eligibility_quizzes" / f"{slug}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _session_answers(slug: str) -> dict:
    store = session.setdefault("elig_answers", {})
    return store.setdefault(slug, {})


def _pick(obj: dict, key: str, lang: str):
    if lang == "en":
        alt = obj.get(f"{key}_en")
        if alt:
            return alt
    return obj.get(key)


def _localize_question(q: dict, lang: str) -> dict:
    out = {
        "id": q["id"],
        "type": q["type"],
        "label": _pick(q, "label", lang),
        "required": q.get("required", True),
    }
    hint = _pick(q, "hint", lang)
    if hint:
        out["hint"] = hint
    if "options" in q:
        out["options"] = [
            {"value": opt["value"], "label": _pick(opt, "label", lang)}
            for opt in q["options"]
        ]
    return out


@eligibility_bp.route("/")
def index():
    from app.i18n import get_lang
    lang = get_lang()
    quizzes = [
        {"slug": slug, "title": _pick(q, "title", lang), "subtitle": _pick(q, "subtitle", lang)}
        for slug in QUIZ_SLUGS
        for q in [_load_quiz(slug)]
    ]
    return render_template("eligibility_index.html", quizzes=quizzes)


@eligibility_bp.route("/<slug>")
def quiz_view(slug: str):
    if slug not in QUIZ_SLUGS:
        abort(404)
    from app.i18n import get_lang
    lang = get_lang()
    quiz = _load_quiz(slug)
    answers = _session_answers(slug)
    active = active_questions(quiz["questions"], answers)
    total = len(active)
    current = next((q for q in active if q["id"] not in answers), None)

    if current is None:
        return redirect(url_for("eligibility.result", slug=slug))

    answered_count = sum(1 for q in active if q["id"] in answers)
    return render_template(
        "eligibility_step.html",
        slug=slug,
        quiz_title=_pick(quiz, "title", lang),
        question=_localize_question(current, lang),
        answered_count=answered_count,
        total=total,
    )


@eligibility_bp.route("/<slug>/responder", methods=["POST"])
def answer(slug: str):
    if slug not in QUIZ_SLUGS:
        abort(404)
    quiz = _load_quiz(slug)
    answers = _session_answers(slug)

    question_id = request.form.get("question_id")
    question = next((q for q in quiz["questions"] if q["id"] == question_id), None)
    if question is None:
        abort(400)

    from app.i18n import t

    raw = request.form.get(question_id, "").strip()
    if not raw:
        flash(t("elig_field_required"), "error")
        return redirect(url_for("eligibility.quiz_view", slug=slug))

    if question["type"] == "date" and not DATE_RE.match(raw):
        flash(t("elig_invalid_date"), "error")
        return redirect(url_for("eligibility.quiz_view", slug=slug))

    answers[question_id] = raw
    session.modified = True
    return redirect(url_for("eligibility.quiz_view", slug=slug))


@eligibility_bp.route("/<slug>/resultado")
def result(slug: str):
    if slug not in QUIZ_SLUGS:
        abort(404)
    from app.i18n import get_lang
    lang = get_lang()
    quiz = _load_quiz(slug)
    answers = _session_answers(slug)
    active = active_questions(quiz["questions"], answers)

    if any(q["id"] not in answers for q in active):
        return redirect(url_for("eligibility.quiz_view", slug=slug))

    outcome = EVALUATORS[slug](answers)
    messages = [
        {"tone": m["tone"], "text": m["text_en"] if lang == "en" else m["text"]}
        for m in outcome["messages"]
    ]
    filing_window = None
    if outcome["filing_window"]:
        fw = outcome["filing_window"]
        filing_window = {"tone": fw["tone"], "text": fw["text_en"] if lang == "en" else fw["text"]}

    return render_template(
        "eligibility_result.html",
        slug=slug,
        quiz_title=_pick(quiz, "title", lang),
        maps_to=quiz.get("maps_to"),
        verdict=outcome["verdict"],
        messages=messages,
        filing_window=filing_window,
    )


@eligibility_bp.route("/<slug>/reiniciar", methods=["POST"])
def restart(slug: str):
    if slug not in QUIZ_SLUGS:
        abort(404)
    store = session.setdefault("elig_answers", {})
    store[slug] = {}
    session.modified = True
    return redirect(url_for("eligibility.quiz_view", slug=slug))
