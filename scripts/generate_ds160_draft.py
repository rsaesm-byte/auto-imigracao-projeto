#!/usr/bin/env python3
"""Gera o PDF do rascunho de DS-160 (data/questionnaires/ds160.json) com a
marca Saes Professional Services -- documento de apoio pra equipe preencher
o DS-160 oficial no site do Departamento de Estado (CEAC), que não tem
PDF/AcroForm próprio (mesma razão de app/wizard.py::"i-539-cartas" não ter
mapping: o formulário real só existe online).

Uso:
    python scripts/generate_ds160_draft.py output/answers-ds160-exemplo.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                 Spacer, Table, TableStyle)

try:
    from scripts.run_questionnaire import active_questions
except ImportError:
    from run_questionnaire import active_questions

ROOT = Path(__file__).resolve().parent.parent
QUESTIONNAIRE_PATH = ROOT / "data" / "questionnaires" / "ds160.json"

NAO_RESPONDIDO = "— NÃO RESPONDIDO —"


def _load_questionnaire() -> dict:
    return json.loads(QUESTIONNAIRE_PATH.read_text(encoding="utf-8"))


def _display_value(question: dict, value) -> str:
    """Mesma lógica de app/wizard.py::_display_value -- reimplementada aqui
    pra este script continuar rodável isoladamente, sem depender do pacote
    Flask (mesmo padrão dos outros scripts/generate_*.py)."""
    options = {opt["value"]: opt["label"] for opt in question.get("options", [])}
    if isinstance(value, list):
        if not value:
            return ""
        return ", ".join(options.get(v, v) for v in value)
    if value is None:
        return ""
    return options.get(value, str(value))


def _wrap_row(cells, style):
    return [Paragraph(str(c), style) for c in cells]


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="DraftTitle", parent=styles["Title"], fontSize=17,
        spaceAfter=2, textColor=colors.HexColor("#1a1a2e")))
    styles.add(ParagraphStyle(
        name="DraftSubtitle", parent=styles["Normal"], fontSize=10.5,
        textColor=colors.HexColor("#555555"), spaceAfter=10))
    styles.add(ParagraphStyle(
        name="SectionHeader", parent=styles["Heading2"], fontSize=12.5,
        spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#1a1a2e")))
    styles.add(ParagraphStyle(
        name="Alert", parent=styles["Normal"], fontSize=9.5, leading=13,
        textColor=colors.HexColor("#7a1f1f"), backColor=colors.HexColor("#fdecec"),
        borderColor=colors.HexColor("#e0a0a0"), borderWidth=0.75,
        borderPadding=8, spaceBefore=4, spaceAfter=10))
    styles.add(ParagraphStyle(
        name="Small", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.HexColor("#666666")))
    styles.add(ParagraphStyle(
        name="TableHeader", parent=styles["Normal"], fontSize=9, leading=11,
        textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(
        name="TableCell", parent=styles["Normal"], fontSize=9, leading=12))
    styles.add(ParagraphStyle(
        name="TableCellMissing", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#b00020"), fontName="Helvetica-Bold"))
    return styles


def build_ds160_draft(answers: dict, out_path: Path, client_name: str = "") -> Path:
    qdata = _load_questionnaire()
    active = active_questions(qdata["questions"], answers)
    by_section: dict[str, list[dict]] = {}
    for q in active:
        by_section.setdefault(q["section"], []).append(q)

    tipo_visto = answers.get("tipo_visto")
    tipo_visto_label = {"b1_b2": "B1/B2 — Turismo/Negócios",
                         "f1_f2": "F1/F2 — Estudante"}.get(tipo_visto, tipo_visto or "—")

    styles = build_styles()
    story = []

    story.append(Paragraph("Rascunho — Visto Americano (DS-160)", styles["DraftTitle"]))
    subtitle = f"Tipo de visto: {tipo_visto_label}"
    if client_name:
        subtitle = f"{client_name} &nbsp;·&nbsp; {subtitle}"
    subtitle += f" &nbsp;·&nbsp; Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y')}"
    story.append(Paragraph(subtitle, styles["DraftSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#cccccc")))

    story.append(Paragraph(
        "Este documento reúne as respostas do rascunho preenchido pelo cliente. O DS-160 oficial "
        "só existe no sistema do Departamento de Estado americano (CEAC) -- use este PDF como apoio "
        "para preenchê-lo lá, campo a campo. Qualquer linha marcada como <b>NÃO RESPONDIDO</b> precisa "
        "ser resolvida com o cliente antes do protocolo: o CEAC não aceita campos em branco.",
        styles["Alert"]))

    missing_count = 0
    for section in qdata["sections"]:
        questions = by_section.get(section["id"])
        if not questions:
            continue
        story.append(Paragraph(section["title"], styles["SectionHeader"]))
        raw_rows = [["Pergunta", "Resposta"]]
        for q in questions:
            value = answers.get(q["id"])
            display = _display_value(q, value)
            if not display:
                display = NAO_RESPONDIDO
                missing_count += 1
            raw_rows.append([q["label"], display])

        rows = [_wrap_row(raw_rows[0], styles["TableHeader"])]
        for label, display in raw_rows[1:]:
            cell_style = styles["TableCellMissing"] if display == NAO_RESPONDIDO else styles["TableCell"]
            rows.append([Paragraph(label, styles["TableCell"]), Paragraph(display, cell_style)])

        table = Table(rows, colWidths=[280, 220])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f8")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 10))
    if missing_count:
        story.append(Paragraph(
            f"<b>{missing_count} pergunta(s) sem resposta</b> -- revisar com o cliente antes de "
            "protocolar no CEAC.", styles["Alert"]))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Paragraph(
        "Adequação à Lei Geral de Proteção de Dados: a Saes Professional Services trata os dados "
        "pessoais coletados neste rascunho com responsabilidade, segurança e transparência, em "
        "conformidade com a LGPD. Dúvidas: saes.professionalservices@gmail.com. É de responsabilidade "
        "do cliente a exatidão das informações acima -- qualquer erro no preenchimento pode impactar "
        "o processo perante o Consulado Americano. A Saes Professional Services não se responsabiliza "
        "por eventuais negativas de visto ou solicitações de novos documentos pelo Consulado.",
        styles["Small"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Assinatura do solicitante: _______________________________________________",
                            styles["Small"]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=letter,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="Rascunho — Visto Americano (DS-160)",
    )
    doc.build(story)
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gera o PDF do rascunho de DS-160.")
    parser.add_argument("answers", help="Respostas JSON (ex: output/answers-ds160-exemplo.json)")
    parser.add_argument("--out", default="output/ds160-rascunho.pdf", help="Caminho do PDF de saída")
    parser.add_argument("--client-name", default="", help="Nome do cliente, exibido no cabeçalho")
    args = parser.parse_args(argv)

    answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    out_path = build_ds160_draft(answers, Path(args.out), client_name=args.client_name)
    print(f"Gerado: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
