"""Blueprint da preparação para o teste de educação cívica/inglês da naturalização
(N-400): página de referência com as 128 perguntas oficiais do teste 2025
(M-1778) e um simulador de prática que reproduz o formato real da
entrevista (sorteio de perguntas, parada antecipada ao atingir o número de
acertos/erros que decide o resultado).

Sem login, sem persistência em banco -- mesmo raciocínio de privacidade do
app/eligibility.py: é uma ferramenta pública de estudo, as respostas do
simulado ficam só na sessão do navegador."""
from __future__ import annotations

import json
import random
from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

civics_bp = Blueprint("civics", __name__, url_prefix="/exame-cidadania")

ROOT = Path(__file__).resolve().parent.parent
_QUESTIONS_PATH = ROOT / "data" / "civics_test" / "questions_2025.json"

# Regras oficiais do teste de educação cívica 2025 (M-1778 / uscis.gov/citizenship/study-for-the-test):
# até 20 perguntas de um total de 128, precisa acertar 12 para passar, reprova
# se errar 9. O oficial para de perguntar assim que um desses dois números é
# atingido -- reproduzimos essa parada antecipada no simulador.
MODES = {
    "full": {"pool": "all", "asked": 20, "need_correct": 12, "max_wrong": 8},
    "65_20": {"pool": "starred", "asked": 10, "need_correct": 6, "max_wrong": 4},
}


def _load_questions() -> list[dict]:
    data = json.loads(_QUESTIONS_PATH.read_text(encoding="utf-8"))
    return data["questions"]


def _by_id(qid: int) -> dict | None:
    return next((q for q in _load_questions() if q["id"] == qid), None)


def _grouped_reference() -> list[dict]:
    """Agrupa as 128 perguntas por seção > subseção, na ordem oficial,
    para a página de referência (não usado pelo simulador)."""
    questions = _load_questions()
    groups: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for q in questions:
        key = (q["section"], q["subsection"])
        if key not in groups:
            groups[key] = {
                "section": q["section"], "section_pt": q["section_pt"],
                "subsection": q["subsection"], "subsection_pt": q["subsection_pt"],
                "questions": [],
            }
            order.append(key)
        groups[key]["questions"].append(q)
    return [groups[k] for k in order]


@civics_bp.route("/")
def index():
    return render_template("civics_index.html")


@civics_bp.route("/perguntas")
def questions_reference():
    return render_template("civics_questions.html", groups=_grouped_reference())


@civics_bp.route("/praticar/iniciar", methods=["POST"])
def practice_start():
    mode = request.form.get("mode", "full")
    if mode not in MODES:
        abort(400)
    cfg = MODES[mode]
    questions = _load_questions()
    pool = questions if cfg["pool"] == "all" else [q for q in questions if q["starred"]]
    chosen = random.sample(pool, cfg["asked"])

    session["civics"] = {
        "mode": mode,
        "question_ids": [q["id"] for q in chosen],
        "position": 0,
        "correct": 0,
        "wrong": 0,
        "finished": False,
        "verdict": None,
        "missed_ids": [],
        "feedback": None,
    }
    session.modified = True
    return redirect(url_for("civics.practice_view"))


@civics_bp.route("/praticar")
def practice_view():
    state = session.get("civics")
    if not state:
        return redirect(url_for("civics.index"))

    cfg = MODES[state["mode"]]

    # Múltipla escolha (perguntas não-dinâmicas) passa por uma tela de
    # feedback antes de avançar -- practice_answer() já atualizou
    # acertos/erros/posição/veredito, só falta o usuário confirmar "Continuar"
    # pra sair da tela de feedback (ver practice_continue()).
    if state.get("feedback"):
        fb = state["feedback"]
        question = _by_id(fb["question_id"])
        return render_template(
            "civics_practice_feedback.html",
            state=state, cfg=cfg, question=question, feedback=fb,
        )

    if state["finished"]:
        missed = [_by_id(qid) for qid in state["missed_ids"]]
        return render_template(
            "civics_practice_result.html",
            state=state, cfg=cfg, missed=[q for q in missed if q],
        )

    qid = state["question_ids"][state["position"]]
    question = _by_id(qid)
    mc_options = None
    if not question["dynamic"]:
        mc_options = list(question["mc_options"])
        random.shuffle(mc_options)
    return render_template(
        "civics_practice_step.html",
        state=state, cfg=cfg, question=question, mc_options=mc_options,
        position=state["position"] + 1, total=cfg["asked"],
    )


def _apply_result(state: dict, cfg: dict, qid: int, got_it_right: bool) -> None:
    """Atualiza acertos/erros e decide se o simulado terminou (mesma lógica
    de parada antecipada oficial), mas NÃO avança a posição -- isso só
    acontece em practice_continue(), depois que o usuário vê o feedback."""
    if got_it_right:
        state["correct"] += 1
    else:
        state["wrong"] += 1
        state["missed_ids"].append(qid)

    if state["correct"] >= cfg["need_correct"]:
        state["finished"] = True
        state["verdict"] = "pass"
    elif state["wrong"] > cfg["max_wrong"]:
        state["finished"] = True
        state["verdict"] = "fail"
    elif state["position"] + 1 >= cfg["asked"]:
        state["finished"] = True
        state["verdict"] = "pass" if state["correct"] > state["wrong"] else "fail"


@civics_bp.route("/praticar/responder", methods=["POST"])
def practice_answer():
    state = session.get("civics")
    if not state or state["finished"] or state.get("feedback"):
        return redirect(url_for("civics.practice_view"))

    cfg = MODES[state["mode"]]
    qid = state["question_ids"][state["position"]]
    question = _by_id(qid)

    if question["dynamic"]:
        # Pergunta de resposta dinâmica (ex: presidente atual) -- sem forma de
        # gerar alternativas erradas confiáveis, então continua no formato de
        # autoavaliação (a resposta oficial já foi revelada antes de clicar).
        got_it_right = request.form.get("result") == "correct"
        _apply_result(state, cfg, qid, got_it_right)
        if not state["finished"]:
            state["position"] += 1
        session["civics"] = state
        session.modified = True
        return redirect(url_for("civics.practice_view"))

    # Múltipla escolha: a alternativa escolhida vem como texto (não índice),
    # comparada direto com mc_correct -- não depende de nenhuma ordem/estado
    # de embaralhamento sincronizado entre o GET que mostrou as opções e este
    # POST, então não há risco de dessincronia.
    chosen = request.form.get("choice", "")
    got_it_right = chosen == question["mc_correct"]
    _apply_result(state, cfg, qid, got_it_right)
    state["feedback"] = {
        "question_id": qid,
        "chosen": chosen,
        "was_correct": got_it_right,
    }
    session["civics"] = state
    session.modified = True
    return redirect(url_for("civics.practice_view"))


@civics_bp.route("/praticar/continuar", methods=["POST"])
def practice_continue():
    state = session.get("civics")
    if not state or not state.get("feedback"):
        return redirect(url_for("civics.practice_view"))

    state["feedback"] = None
    if not state["finished"]:
        state["position"] += 1
    session["civics"] = state
    session.modified = True
    return redirect(url_for("civics.practice_view"))
