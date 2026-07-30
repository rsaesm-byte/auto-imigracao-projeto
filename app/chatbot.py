"""Blueprint do assistente conversacional (chatbot): suporte geral no site e
ajuda contextual dentro do wizard de preenchimento de formulário.

Guardrails (ver references/compliance.md): o assistente nunca decide
estratégia de caso, nunca promete submissão automática à USCIS, e encaminha
temas complexos (histórico criminal, inadmissibilidade, asilo) a um advogado
humano -- mesmo enquadramento já usado em app/services/eligibility_rules.py.

O contexto "em qual pergunta o usuário está" nunca vem de texto que o
cliente mandou -- é reconstruído aqui a partir da submissão real no banco,
só quando o usuário autenticado é o dono dela (mesma checagem de
app.wizard._get_owned_submission).
"""
from __future__ import annotations

import os
import time

import requests
from flask import Blueprint, jsonify, request, session
from flask_login import current_user

from app.i18n import get_lang
from app.wizard import _form_display_name, _load_questionnaire, _load_registry_entry, _section_title
from scripts.run_questionnaire import active_questions

chatbot_bp = Blueprint("chatbot", __name__)

# Gemini via REST direta (requests já é dependência do projeto) -- sem SDK novo.
# "gemini-flash-latest" é a única opção viável na chave atual: confirmado por
# teste real que "gemini-pro-latest" retorna 429 (quota zerada no tier
# gratuito para o modelo Pro).
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
# Este modelo pensa por padrão e "thinkingBudget: 0" é rejeitado (400) --
# confirmado por teste real. Um budget pequeno e positivo (256) é aceito e
# evita que o raciocínio interno consuma sozinho todo o MAX_TOKENS antes de
# qualquer texto visível ser escrito (o que já aconteceu em teste real: 481
# tokens de "pensamento" estourando um limite de 500, resposta cortada no
# meio). MAX_TOKENS também subiu pra sobrar espaço de verdade pro texto.
THINKING_BUDGET = 256
MAX_TOKENS = 1024
MAX_HISTORY_MESSAGES = 20  # ~10 turnos, cap simples pra não deixar o histórico crescer sem limite
RATE_LIMIT_MAX_MESSAGES = 20
RATE_LIMIT_WINDOW_SECONDS = 60 * 60

_SYSTEM_BASE = {
    "pt": (
        "Você é o assistente virtual do site auto-imigração/Saes Professional Services, uma ferramenta de "
        "preparação autodirigida de formulários de imigração dos EUA (USCIS) -- I-130, I-485, "
        "I-765, I-864, I-751, I-90, N-400, I-539 e Cartas Complementares do I-539. Responda em "
        "português, em frases curtas e diretas, como um chat de suporte -- NUNCA como um "
        "documento longo: no máximo 3-4 frases curtas por resposta, sem títulos, sem markdown "
        "de cabeçalho (#, ##), sem listas extensas. Se o tema exigir mais detalhe, dê o essencial "
        "em poucas frases e ofereça continuar se a pessoa quiser saber mais.\n\n"
        "REGRAS OBRIGATÓRIAS:\n"
        "- Você NÃO é advogado e este site NÃO é um escritório de advocacia. Nunca dê "
        "aconselhamento jurídico nem decida estratégia de caso.\n"
        "- Alertas devem ser informativos ('esta situação costuma exigir X', 'isso pode atrasar "
        "o processo'), nunca uma recomendação diretiva ('você deve fazer Y').\n"
        "- Em temas complexos (histórico criminal, inadmissibilidade, asilo, deportação), diga "
        "explicitamente que a pessoa deve consultar um advogado de imigração.\n"
        "- Você nunca preenche formulários nem envia nada à USCIS em nome do usuário -- quem faz "
        "isso é o wizard do próprio site, sob revisão do usuário.\n"
        "- Se não souber a resposta com confiança, diga isso em vez de inventar."
    ),
    "en": (
        "You are the virtual assistant for the auto-imigração/Saes Professional Services site, a self-directed "
        "USCIS immigration form-preparation tool -- I-130, I-485, I-765, I-864, I-751, I-90, "
        "N-400, I-539, and I-539 Supplementary Letters. Reply in English, short and direct, like "
        "a support chat -- NEVER a long document: at most 3-4 short sentences per reply, no "
        "headings, no markdown headers (#, ##), no long lists. If the topic needs more depth, "
        "give the essentials in a few sentences and offer to continue if the person wants more.\n\n"
        "MANDATORY RULES:\n"
        "- You are NOT a lawyer and this site is NOT a law firm. Never give legal advice or "
        "decide case strategy.\n"
        "- Warnings must be informational ('this situation usually requires X', 'this may delay "
        "the process'), never a directive recommendation ('you should do Y').\n"
        "- On complex topics (criminal history, inadmissibility, asylum, deportation), explicitly "
        "say the person should consult an immigration lawyer.\n"
        "- You never fill out forms or submit anything to USCIS on the user's behalf -- that's "
        "the site's own wizard, under the user's review.\n"
        "- If you don't know the answer confidently, say so instead of making it up."
    ),
    "es": (
        "Usted es el asistente virtual del sitio auto-imigração/Saes Professional Services, una herramienta autodirigida "
        "de preparación de formularios de inmigración de USCIS -- I-130, I-485, I-765, I-864, "
        "I-751, I-90, N-400, I-539 y Cartas Complementarias del I-539. Responda en español, en "
        "frases cortas y directas, como un chat de soporte -- NUNCA como un documento largo: como "
        "máximo 3-4 frases cortas por respuesta, sin títulos, sin markdown de encabezado (#, ##), "
        "sin listas extensas. Si el tema requiere más detalle, dé lo esencial en pocas frases y "
        "ofrezca continuar si la persona quiere saber más.\n\n"
        "REGLAS OBLIGATORIAS:\n"
        "- NO es usted abogado(a) y este sitio NO es un despacho de abogados. Nunca dé "
        "asesoramiento jurídico ni decida la estrategia del caso.\n"
        "- Las advertencias deben ser informativas ('esta situación suele requerir X', 'esto puede "
        "retrasar el proceso'), nunca una recomendación directiva ('usted debe hacer Y').\n"
        "- En temas complejos (antecedentes penales, inadmisibilidad, asilo, deportación), diga "
        "explícitamente que la persona debe consultar a un abogado de inmigración.\n"
        "- Nunca complete formularios ni envíe nada a USCIS en nombre del usuario -- eso lo "
        "hace el propio asistente guiado del sitio, bajo la revisión del usuario.\n"
        "- Si no sabe la respuesta con confianza, dígalo en vez de inventar."
    ),
}


def _wizard_context_block(submission_id, question_id) -> str | None:
    """Contexto real do servidor sobre a submissão/pergunta atual -- só quando
    o usuário autenticado é dono da submissão. Nunca confia em label/hint/fee
    vindos do cliente, só no que está de fato salvo no banco e nos arquivos
    de dados do formulário."""
    if not submission_id or not current_user.is_authenticated:
        return None

    from app.db import SessionLocal
    from app.models import FormSubmission

    submission = SessionLocal.get(FormSubmission, submission_id)
    if submission is None or submission.user_id != current_user.id:
        return None

    slug = submission.form_slug
    lang = get_lang()
    form_name = _form_display_name(slug)

    lines = []
    filling_out = {
        "pt": f"O usuário está preenchendo o formulário {form_name} (submissão #{submission.id}).",
        "en": f"The user is currently filling out {form_name} (submission #{submission.id}).",
        "es": f"El usuario está completando el formulario {form_name} (expediente #{submission.id}).",
    }
    lines.append(filling_out.get(lang, filling_out["pt"]))

    if slug != "i-539-cartas":
        entry = _load_registry_entry(slug)
        fee = entry.get("fees", {}).get("filing", {})
        if fee:
            online = fee.get("online", fee.get("default"))
            paper = fee.get("paper", fee.get("default"))
            fee_line = {
                "pt": f"Taxa de protocolo (USCIS): ${online} online / ${paper} papel.",
                "en": f"USCIS filing fee: ${online} online / ${paper} paper.",
                "es": f"Tarifa de presentación (USCIS): ${online} en línea / ${paper} en papel.",
            }
            lines.append(fee_line.get(lang, fee_line["pt"]))

    if question_id:
        question = None
        section = None
        try:
            qdata = _load_questionnaire(slug)
            answers = submission.get_answers()
            active = active_questions(qdata["questions"], answers)
            question = next((q for q in active if q["id"] == question_id), None)
            if question:
                section = _section_title(qdata, question)
        except Exception:
            question = None
        if question:
            label = question.get("label", "")
            hint = question.get("hint")
            if lang == "en":
                line = f'User\'s current question: "{label}"'
                if section:
                    line += f" (section: {section})"
                if hint:
                    line += f". Hint already shown on screen: {hint}"
            elif lang == "es":
                line = f'Pregunta actual del usuario: "{label}"'
                if section:
                    line += f" (sección: {section})"
                if hint:
                    line += f". Sugerencia ya mostrada en pantalla: {hint}"
            else:
                line = f'Pergunta atual do usuário: "{label}"'
                if section:
                    line += f" (seção: {section})"
                if hint:
                    line += f". Dica já mostrada na tela: {hint}"
            lines.append(line)

    return "\n".join(lines)


def _rate_limited() -> bool:
    now = time.time()
    times = [t for t in session.get("chat_msg_times", []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(times) >= RATE_LIMIT_MAX_MESSAGES:
        session["chat_msg_times"] = times
        return True
    times.append(now)
    session["chat_msg_times"] = times
    session.modified = True
    return False


_RATE_LIMITED_MSG = {
    "pt": "Você enviou muitas mensagens em pouco tempo. Tente de novo em alguns minutos.",
    "en": "You've sent a lot of messages in a short time. Please try again in a few minutes.",
    "es": "Ha enviado muchos mensajes en poco tiempo. Inténtelo de nuevo en unos minutos.",
}
_UNAVAILABLE_MSG = {
    "pt": "Nosso assistente está temporariamente indisponível. Tente novamente mais tarde.",
    "en": "Our assistant is temporarily unavailable. Please try again later.",
    "es": "Nuestro asistente no está disponible temporalmente. Inténtelo de nuevo más tarde.",
}
_ERROR_MSG = {
    "pt": "Desculpe, não consegui responder agora. Tente de novo em instantes.",
    "en": "Sorry, I couldn't answer right now. Please try again shortly.",
    "es": "Disculpe, no pude responder en este momento. Inténtelo de nuevo en unos instantes.",
}
_CONTEXT_HEADER = {
    "pt": "\n\nCONTEXTO DA SESSÃO ATUAL:\n",
    "en": "\n\nCURRENT SESSION CONTEXT:\n",
    "es": "\n\nCONTEXTO DE LA SESIÓN ACTUAL:\n",
}


@chatbot_bp.route("/chatbot/message", methods=["POST"])
def send_message():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty"}), 400

    lang = get_lang()

    if _rate_limited():
        return jsonify({"reply": _RATE_LIMITED_MSG.get(lang, _RATE_LIMITED_MSG["pt"]), "rate_limited": True})

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"reply": _UNAVAILABLE_MSG.get(lang, _UNAVAILABLE_MSG["pt"])})

    submission_id = data.get("submission_id")
    question_id = data.get("question_id")
    context_block = _wizard_context_block(submission_id, question_id)

    system_prompt = _SYSTEM_BASE.get(lang, _SYSTEM_BASE["pt"])
    if context_block:
        system_prompt += _CONTEXT_HEADER.get(lang, _CONTEXT_HEADER["pt"]) + context_block

    history = session.get("chat_history", [])
    history.append({"role": "user", "content": message})

    try:
        resp = requests.post(
            GEMINI_URL,
            headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
            json={
                "contents": [
                    {"role": "model" if h["role"] == "assistant" else "user",
                     "parts": [{"text": h["content"]}]}
                    for h in history
                ],
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": {
                    "maxOutputTokens": MAX_TOKENS,
                    "thinkingConfig": {"thinkingBudget": THINKING_BUDGET},
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        candidates = resp.json().get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        reply = "".join(p.get("text", "") for p in parts).strip()
        if not reply:
            raise ValueError("empty response")
    except Exception:
        reply = _ERROR_MSG.get(lang, _ERROR_MSG["pt"])
        session["chat_history"] = history[-MAX_HISTORY_MESSAGES:]
        session.modified = True
        return jsonify({"reply": reply})

    history.append({"role": "assistant", "content": reply})
    session["chat_history"] = history[-MAX_HISTORY_MESSAGES:]
    session.modified = True

    return jsonify({"reply": reply})
