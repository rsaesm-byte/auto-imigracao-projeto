#!/usr/bin/env python3
"""Gera os documentos complementares do I-539 a partir das respostas do
questionário separado data/questionnaires/i-539-cartas.json:

- Resumo da narrativa pessoal: compila as respostas do cliente às
  perguntas de narrativa em um PDF "Uso Interno" -- usado apenas como
  fallback (ver abaixo). A carta final é redigida automaticamente via IA
  (Gemini, API do Google, `draft_narrative_letter`/
  `build_drafted_narrative_letter`), com o prompt dedicado de cada serviço
  (data/prompts/i539-eos-narrative.txt, i539-b2-narrative.txt,
  i539-f1-narrative.txt, i539-f2-narrative.txt -- ver
  NARRATIVE_PROMPT_FILE_BY_SERVICE) como system prompt e as respostas do
  cliente como contexto -- sempre em inglês, pronta para revisão e
  assinatura. Se GEMINI_API_KEY não estiver configurada ou a chamada
  falhar, `build_narrative_document` cai automaticamente para o resumo cru
  das respostas (Uso Interno) em vez de deixar o documento faltando.
- Carta de Endereço (assinada pelo titular do comprovante de endereço, se
  não for o próprio requerente) — em inglês, pronta para imprimir e assinar.
- Carta de Patrocínio (assinada pelo patrocinador financeiro, se os
  extratos bancários não forem do requerente) — em inglês.
- Carta do Empregador (assinada pelo empregador, se o requerente não tiver
  empresa própria) — em inglês.
- Carta de responsável pela empresa (assinada por quem vai administrar o
  negócio do requerente enquanto ele estiver nos EUA, se ele tiver empresa
  própria) — em inglês.

Cada carta só é gerada se a pergunta de gate correspondente estiver
respondida com o valor que a exige — ver GATES abaixo.

Uso:
    python scripts/generate_cartas_i539.py output/answers-cartas-joao.json
    python scripts/generate_cartas_i539.py output/answers-cartas-joao.json --out-dir output/cartas
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                 Spacer)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
QUESTIONNAIRE_PATH = ROOT / "data" / "questionnaires" / "i-539-cartas.json"
PROMPTS_DIR = ROOT / "data" / "prompts"

if load_dotenv is not None:
    load_dotenv(ROOT / ".env")

# Gemini via REST direta (requests já é dependência do projeto) -- mesmo
# padrão de app/chatbot.py. "gemini-flash-latest" é a única opção viável na
# chave atual: confirmado por teste real que "gemini-pro-latest" retorna 429
# (quota zerada no tier gratuito para o modelo Pro).
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
# Cada serviço tem seu próprio prompt do usuário, um por alvo real de
# extensão/mudança de status (data/prompts/i539-<servico>-narrative.txt).
# Até 2026-07-31 os 3 alvos de mudança de status (B2/F1/F2) compartilhavam
# um único prompt genérico (i539-cos-narrative.txt, focado em estudo nos
# EUA) porque o usuário só tinha fornecido um prompt de COS para os três —
# ele não fazia sentido pra quem está pedindo B2 (turista) ou F2
# (dependente), só coincidentemente funcionava razoável pra F1. Substituído
# por 3 prompts dedicados, um por serviço, derivados dos modelos de carta
# reais que a equipe já usa (_COS_Letter_B2/F1/F2.docx) — i539-cos-
# narrative.txt continua no repositório sem uso, mantido só como histórico.
NARRATIVE_PROMPT_FILE_BY_SERVICE = {
    "eos": "i539-eos-narrative.txt",
    "cos_b2": "i539-b2-narrative.txt",
    "cos_f1": "i539-f1-narrative.txt",
    "cos_f2": "i539-f2-narrative.txt",
}

SERVICE_LABELS = {
    "eos": "Extension of Status (EOS)",
    "cos_b2": "Change of Status to B-2 Visitor",
    "cos_f1": "Change of Status to F-1 Student",
    "cos_f2": "Change of Status to F-2 Dependent",
}

NARRATIVE_SECTION_BY_SERVICE = {
    "eos": "narrativa_eos",
    "cos_b2": "narrativa_b2",
    "cos_f1": "narrativa_f1",
    "cos_f2": "narrativa_f2",
}

TODAY = datetime.date.today().strftime("%B %d, %Y")


def load_questionnaire() -> dict:
    return json.loads(QUESTIONNAIRE_PATH.read_text(encoding="utf-8"))


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="LetterTitle", parent=styles["Title"], fontSize=15,
        spaceAfter=10, textColor=colors.HexColor("#1a1a2e")))
    styles.add(ParagraphStyle(
        name="LetterBody", parent=styles["Normal"], fontSize=11, leading=16,
        spaceAfter=12))
    styles.add(ParagraphStyle(
        name="LetterDate", parent=styles["Normal"], fontSize=11, leading=15,
        spaceAfter=18))
    styles.add(ParagraphStyle(
        name="SigLabel", parent=styles["Normal"], fontSize=10, leading=13,
        textColor=colors.HexColor("#333333")))
    styles.add(ParagraphStyle(
        name="NarrQuestion", parent=styles["Heading3"], fontSize=11,
        spaceBefore=10, spaceAfter=2, textColor=colors.HexColor("#1a1a2e")))
    styles.add(ParagraphStyle(
        name="NarrHint", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.HexColor("#666666"), spaceAfter=4))
    styles.add(ParagraphStyle(
        name="NarrAnswer", parent=styles["Normal"], fontSize=10.5, leading=14,
        spaceAfter=8, leftIndent=6))
    styles.add(ParagraphStyle(
        name="NarrMissing", parent=styles["Normal"], fontSize=10, leading=13,
        textColor=colors.HexColor("#a33"), spaceAfter=8, leftIndent=6))
    return styles


def _signature_block(styles, story, role_label: str, name: str) -> None:
    story.append(Spacer(1, 24 * mm))
    story.append(HRFlowable(width="45%", thickness=0.75, color=colors.HexColor("#333333")))
    story.append(Paragraph(f"Signature — {role_label}", styles["SigLabel"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Printed Name: {name}", styles["SigLabel"]))
    story.append(Paragraph("Date: _____________________", styles["SigLabel"]))


def _doc(out_path: Path) -> SimpleDocTemplate:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return SimpleDocTemplate(
        str(out_path), pagesize=letter,
        topMargin=25 * mm, bottomMargin=20 * mm,
        leftMargin=25 * mm, rightMargin=25 * mm,
    )


# ── Carta de Endereço ──────────────────────────────────────────────────────

def build_address_letter(answers: dict, out_path: Path) -> Path | None:
    if answers.get("endereco_comprovante_proprio") != "nao":
        return None
    styles = build_styles()
    story = []
    story.append(Paragraph("Letter of Address Confirmation", styles["LetterTitle"]))
    story.append(Paragraph(TODAY, styles["LetterDate"]))
    story.append(Paragraph("To Whom It May Concern,", styles["LetterBody"]))

    holder = answers.get("carta_endereco_titular_nome", "____________________")
    holder_addr = answers.get("carta_endereco_titular_endereco", "____________________")
    relationship = answers.get("carta_endereco_titular_parentesco", "____________________")
    applicant = answers.get("nome_completo_requerente", "the applicant")

    body = (
        f"I, {holder}, residing at {holder_addr}, hereby confirm that the address listed "
        f"above is my current residential address in my home country. I further confirm that "
        f"{applicant} is my {relationship}, and I authorize the use of my address, together with "
        f"the attached proof of address, in support of their U.S. nonimmigrant status application."
    )
    story.append(Paragraph(body, styles["LetterBody"]))

    contact_bits = []
    tax_id = answers.get("carta_endereco_titular_tax_id")
    doc_id = answers.get("carta_endereco_titular_doc_id")
    email = answers.get("carta_endereco_titular_email")
    phone = answers.get("carta_endereco_titular_telefone")
    birth = answers.get("carta_endereco_titular_cidade_nascimento")
    if tax_id:
        contact_bits.append(f"Taxpayer ID: {tax_id}")
    if doc_id:
        contact_bits.append(f"ID Number: {doc_id}")
    if email:
        contact_bits.append(f"Email: {email}")
    if phone:
        contact_bits.append(f"Phone: {phone}")
    if birth:
        contact_bits.append(f"City/State of Birth: {birth}")
    if contact_bits:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), styles["LetterBody"]))

    story.append(Paragraph("Sincerely,", styles["LetterBody"]))
    _signature_block(styles, story, "Address Holder", holder)

    _doc(out_path).build(story)
    return out_path


# ── Carta de Patrocínio ────────────────────────────────────────────────────

def build_sponsorship_letter(answers: dict, out_path: Path) -> Path | None:
    if answers.get("patrocinio_terceiro") != "sim":
        return None
    styles = build_styles()
    story = []
    story.append(Paragraph("Affidavit of Financial Sponsorship", styles["LetterTitle"]))
    story.append(Paragraph(TODAY, styles["LetterDate"]))
    story.append(Paragraph("To Whom It May Concern,", styles["LetterBody"]))

    sponsor = answers.get("carta_patrocinio_nome", "____________________")
    sponsor_addr = answers.get("carta_patrocinio_endereco", "____________________")
    relationship = answers.get("carta_patrocinio_parentesco", "____________________")
    applicant = answers.get("nome_completo_requerente", "the applicant")

    body = (
        f"I, {sponsor}, residing at {sponsor_addr}, hereby declare that I am the {relationship} "
        f"of {applicant}. I am voluntarily providing financial sponsorship for their temporary "
        f"stay in the United States. I confirm, as evidenced by the enclosed bank statements, "
        f"that I have sufficient financial resources to fully support {applicant} — including "
        f"housing, food, transportation, health insurance, and other living expenses — for the "
        f"requested period, without {applicant} needing to work or rely on public assistance in "
        f"the United States."
    )
    story.append(Paragraph(body, styles["LetterBody"]))

    contact_bits = []
    email = answers.get("carta_patrocinio_email")
    phone = answers.get("carta_patrocinio_telefone")
    birth = answers.get("carta_patrocinio_cidade_nascimento")
    if email:
        contact_bits.append(f"Email: {email}")
    if phone:
        contact_bits.append(f"Phone: {phone}")
    if birth:
        contact_bits.append(f"City/State of Birth: {birth}")
    if contact_bits:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), styles["LetterBody"]))

    story.append(Paragraph("Sincerely,", styles["LetterBody"]))
    _signature_block(styles, story, "Financial Sponsor", sponsor)

    _doc(out_path).build(story)
    return out_path


# ── Carta do Empregador ─────────────────────────────────────────────────────

def build_employer_letter(answers: dict, out_path: Path) -> Path | None:
    if answers.get("tem_empresa_propria") != "nao":
        return None
    styles = build_styles()
    story = []
    story.append(Paragraph("Letter of Employment", styles["LetterTitle"]))
    story.append(Paragraph(TODAY, styles["LetterDate"]))
    story.append(Paragraph("To Whom It May Concern,", styles["LetterBody"]))

    company = answers.get("carta_empregador_nome_empresa", "____________________")
    owner = answers.get("carta_empregador_proprietario_nome", "____________________")
    company_addr = answers.get("carta_empregador_endereco_empresa", "____________________")
    applicant = answers.get("nome_completo_requerente", "the applicant")

    body = (
        f"I, {owner}, owner of {company}, located at {company_addr}, hereby confirm that "
        f"{applicant} is a valued associate of this company and that a position remains "
        f"available to them upon their return from their temporary stay in the United States. "
        f"This letter is provided to support {applicant}'s demonstration of ties to their home "
        f"country and their intent to return at the conclusion of their authorized stay."
    )
    story.append(Paragraph(body, styles["LetterBody"]))

    contact_bits = []
    owner_cpf = answers.get("carta_empregador_proprietario_cpf")
    cnpj = answers.get("carta_empregador_cnpj")
    email = answers.get("carta_empregador_proprietario_email")
    phone = answers.get("carta_empregador_proprietario_telefone")
    birth = answers.get("carta_empregador_proprietario_cidade_nascimento")
    if owner_cpf:
        contact_bits.append(f"Owner Taxpayer ID: {owner_cpf}")
    if cnpj:
        contact_bits.append(f"Company Registration No.: {cnpj}")
    if email:
        contact_bits.append(f"Email: {email}")
    if phone:
        contact_bits.append(f"Phone: {phone}")
    if birth:
        contact_bits.append(f"Owner's City/State of Birth: {birth}")
    if contact_bits:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), styles["LetterBody"]))

    story.append(Paragraph("Sincerely,", styles["LetterBody"]))
    _signature_block(styles, story, "Employer", owner)

    _doc(out_path).build(story)
    return out_path


# ── Carta de responsável pela empresa ───────────────────────────────────────

def build_business_caretaker_letter(answers: dict, out_path: Path) -> Path | None:
    if answers.get("tem_empresa_propria") != "sim":
        return None
    styles = build_styles()
    story = []
    story.append(Paragraph("Letter of Business Management During Absence", styles["LetterTitle"]))
    story.append(Paragraph(TODAY, styles["LetterDate"]))
    story.append(Paragraph("To Whom It May Concern,", styles["LetterBody"]))

    applicant = answers.get("nome_completo_requerente", "the undersigned")
    company = answers.get("carta_empresa_nome", "____________________")
    company_addr = answers.get("carta_empresa_endereco", "____________________")
    caretaker = answers.get("carta_empresa_cuidador_nome", "____________________")
    role = answers.get("carta_empresa_cuidador_cargo", "____________________")

    body = (
        f"I, {applicant}, owner of {company}, located at {company_addr}, hereby confirm that "
        f"{caretaker} ({role}) will be responsible for the management and day-to-day operations "
        f"of my company during my temporary stay in the United States. This letter is provided "
        f"to support my demonstration of ties to my home country — including an active business "
        f"that will continue to operate under trusted management — and my intent to return at "
        f"the conclusion of my authorized stay."
    )
    story.append(Paragraph(body, styles["LetterBody"]))

    company_bits = []
    cnpj = answers.get("carta_empresa_cnpj")
    owner_cpf = answers.get("carta_empresa_proprietario_cpf")
    if cnpj:
        company_bits.append(f"Company Registration No.: {cnpj}")
    if owner_cpf:
        company_bits.append(f"Owner Taxpayer ID: {owner_cpf}")
    if company_bits:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(company_bits), styles["LetterBody"]))

    story.append(Paragraph("Sincerely,", styles["LetterBody"]))
    _signature_block(styles, story, "Business Owner (Applicant)", applicant)

    caretaker_contact = []
    email = answers.get("carta_empresa_cuidador_email")
    phone = answers.get("carta_empresa_cuidador_telefone")
    caretaker_cpf = answers.get("carta_empresa_cuidador_cpf")
    if email:
        caretaker_contact.append(f"Email: {email}")
    if phone:
        caretaker_contact.append(f"Phone: {phone}")
    if caretaker_cpf:
        caretaker_contact.append(f"Taxpayer ID: {caretaker_cpf}")
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"Acknowledged and accepted by the designated manager:", styles["LetterBody"]))
    if caretaker_contact:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(caretaker_contact), styles["LetterBody"]))
    _signature_block(styles, story, "Business Manager During Absence", caretaker)

    _doc(out_path).build(story)
    return out_path


# ── Carta narrativa redigida por IA ─────────────────────────────────────────

def _load_narrative_prompt(servico: str) -> str | None:
    fname = NARRATIVE_PROMPT_FILE_BY_SERVICE.get(servico)
    if not fname:
        return None
    path = PROMPTS_DIR / fname
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _build_qa_context(answers: dict, qdata: dict, section_id: str) -> str:
    lines = []
    applicant = answers.get("nome_completo_requerente")
    if applicant:
        lines.append(f"Applicant name: {applicant}")
    lines.append(f"Service: {SERVICE_LABELS.get(answers.get('servico'), '')}")
    lines.append("")
    lines.append("Questionnaire responses (client's own words, may be in Portuguese or Spanish):")
    for q in qdata["questions"]:
        if q["section"] != section_id:
            continue
        answer = answers.get(q["id"])
        if not answer:
            continue
        lines.append(f"\n{q['label']}\n{answer}")
    return "\n".join(lines)


def draft_narrative_letter(answers: dict, qdata: dict) -> str | None:
    """Chama a API do Gemini (Google) para redigir a carta narrativa final em
    inglês, usando o prompt do usuário (EOS ou COS, data/prompts/) como
    system prompt e as respostas do questionário como contexto. Retorna None
    -- sem levantar exceção -- se faltar API key, prompt, ou respostas, para
    que a geração dos outros documentos nunca trave por causa desta carta."""
    servico = answers.get("servico")
    section_id = NARRATIVE_SECTION_BY_SERVICE.get(servico)
    if not section_id:
        return None

    system_prompt = _load_narrative_prompt(servico)
    if not system_prompt:
        print(f"AVISO: prompt de narrativa não encontrado para servico={servico!r} "
              f"em {PROMPTS_DIR} — pulando a carta narrativa.", file=sys.stderr)
        return None

    qa_context = _build_qa_context(answers, qdata, section_id)
    if "\n" not in qa_context.strip():
        return None  # nenhuma pergunta de narrativa foi respondida

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("AVISO: GEMINI_API_KEY não configurada (variável de ambiente ou .env) "
              "-- pulando a carta narrativa redigida por IA.", file=sys.stderr)
        return None

    response = requests.post(
        GEMINI_URL,
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        json={
            "contents": [{"role": "user", "parts": [{"text": qa_context}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"maxOutputTokens": 8192},
        },
        timeout=120,
    )
    response.raise_for_status()
    candidates = response.json().get("candidates") or []
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    return text or None


def _markdown_ish_to_story(text: str, styles):
    """Conversor mínimo: trata linhas começando com # como título (negrito,
    estilo de pergunta), converte **negrito** inline, escapa caracteres
    especiais de XML ANTES de inserir as tags próprias (senão as tags que a
    gente insere seriam escapadas de novo)."""
    import re
    import xml.sax.saxutils as saxutils

    story = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        heading_match = re.match(r"^#{1,3}\s+(.*)", line)
        if heading_match:
            heading_text = saxutils.escape(heading_match.group(1))
            story.append(Paragraph(f"<b>{heading_text}</b>", styles["NarrQuestion"]))
            continue
        escaped = saxutils.escape(line)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        story.append(Paragraph(escaped, styles["LetterBody"]))
    return story


def build_drafted_narrative_letter(answers: dict, qdata: dict, out_path: Path) -> Path | None:
    text = draft_narrative_letter(answers, qdata)
    if not text:
        return None

    styles = build_styles()
    story = [
        Paragraph("Personal Statement", styles["LetterTitle"]),
        Paragraph(TODAY, styles["LetterDate"]),
    ]
    story.extend(_markdown_ish_to_story(text, styles))
    _doc(out_path).build(story)
    return out_path


# ── Resumo da narrativa (uso interno, sem IA) ───────────────────────────────
# Este é o entregável atual da narrativa: a geração via IA está pausada (ver
# docstring do módulo), então generate_all() usa este resumo cru das
# respostas como base para a equipe redigir a carta final à mão.

def build_narrative_summary(answers: dict, qdata: dict, out_path: Path) -> Path | None:
    servico = answers.get("servico")
    section_id = NARRATIVE_SECTION_BY_SERVICE.get(servico)
    if not section_id:
        return None

    styles = build_styles()
    story = []
    story.append(Paragraph("Resumo da Narrativa — Uso Interno", styles["LetterTitle"]))
    story.append(Paragraph(
        f"Serviço: {SERVICE_LABELS.get(servico, servico)}  |  Gerado em {TODAY}",
        styles["NarrHint"]))
    story.append(Paragraph(
        "Este documento compila as respostas do cliente às perguntas de narrativa. "
        "Use como base para redigir a carta pessoal de extensão/mudança de status — "
        "não é a carta final.", styles["LetterBody"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))

    any_answer = False
    for q in qdata["questions"]:
        if q["section"] != section_id:
            continue
        story.append(Paragraph(q["label"], styles["NarrQuestion"]))
        if q.get("hint"):
            story.append(Paragraph(q["hint"], styles["NarrHint"]))
        answer = answers.get(q["id"])
        if answer:
            any_answer = True
            story.append(Paragraph(answer.replace("\n", "<br/>"), styles["NarrAnswer"]))
        else:
            story.append(Paragraph("(sem resposta)", styles["NarrMissing"]))

    if not any_answer:
        return None

    _doc(out_path).build(story)
    return out_path


def build_narrative_document(answers: dict, qdata: dict, out_path: Path) -> Path | None:
    """Tenta redigir a carta narrativa final via Gemini; se faltar API key,
    faltar prompt, ou a chamada falhar (draft_narrative_letter retorna None
    em qualquer um desses casos, sem levantar exceção), cai para o resumo
    cru das respostas em vez de deixar o documento inteiro faltando."""
    result = build_drafted_narrative_letter(answers, qdata, out_path)
    if result:
        return result
    return build_narrative_summary(answers, qdata, out_path)


# ── Main ─────────────────────────────────────────────────────────────────

def generate_all(answers: dict, out_dir: Path) -> list[Path]:
    qdata = load_questionnaire()
    generated = []
    builders = [
        ("i-539-carta-narrativa.pdf", lambda p: build_narrative_document(answers, qdata, p)),
        ("i-539-carta-endereco.pdf", lambda p: build_address_letter(answers, p)),
        ("i-539-carta-patrocinio.pdf", lambda p: build_sponsorship_letter(answers, p)),
        ("i-539-carta-empregador.pdf", lambda p: build_employer_letter(answers, p)),
        ("i-539-carta-empresa-responsavel.pdf", lambda p: build_business_caretaker_letter(answers, p)),
    ]
    for fname, builder in builders:
        result = builder(out_dir / fname)
        if result:
            generated.append(result)

    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera cartas complementares e resumo de narrativa do I-539.")
    parser.add_argument("answers", help="Respostas JSON (ex: output/answers-cartas-joao.json)")
    parser.add_argument("--out-dir", default="output/cartas", help="Diretório de saída")
    args = parser.parse_args()

    answers_path = Path(args.answers)
    if not answers_path.exists():
        sys.exit(f"ERRO: respostas não encontradas: {answers_path}")

    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    out_dir = ROOT / args.out_dir
    generated = generate_all(answers, out_dir)

    if not generated:
        print("Nenhum documento gerado — nenhuma das perguntas de gate exigiu uma carta, "
              "e/ou nenhuma pergunta de narrativa foi respondida.")
        return

    print(f"{len(generated)} documento(s) gerado(s):")
    for p in generated:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
