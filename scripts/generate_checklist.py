#!/usr/bin/env python3
"""Gera um checklist de protocolo em PDF para um formulario USCIS: quem
precisa assinar e onde, como assinar corretamente (incluindo a nova regra de
assinatura em vigor a partir de 10/07/2026), taxa de protocolo, onde e como
enviar, tempo de processamento e como acompanhar o status do caso.

Uso:
    python scripts/generate_checklist.py i-130
    python scripts/generate_checklist.py --all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Flowable, HRFlowable, ListFlowable, ListItem,
                                 PageBreak, Paragraph, SimpleDocTemplate,
                                 Spacer, Table, TableStyle)

try:
    # funciona quando importado como scripts.generate_checklist (app web)
    from scripts.checklist_strings import STRINGS
except ImportError:
    # funciona quando rodado direto como script de CLI (python
    # scripts/generate_checklist.py), onde so o proprio diretorio scripts/
    # esta no sys.path, nao a raiz do projeto
    from checklist_strings import STRINGS


class CheckBox(Flowable):
    """Desenha um quadrado vetorial fixo (não um caractere de fonte -- as
    fontes base do reportlab não têm um glyph de caixa de seleção utilizável,
    o mesmo problema já visto com "⚠"), pra imprimir e marcar um "X" à mão."""

    def __init__(self, size=9):
        super().__init__()
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        self.canv.setLineWidth(1)
        self.canv.setStrokeColor(colors.HexColor("#333333"))
        self.canv.rect(0, 1, self.size, self.size)

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "data" / "registry.json"

# slug usado em data/questionnaires/<slug>.json e data/forms/<slug>.pdf
# -> codigo usado como chave em data/registry.json["forms"]
FORM_SLUGS = {
    "i-130": "I-130",
    "i-130a": "I-130A",
    "i-765": "I-765",
    "i-485": "I-485",
    "i-864": "I-864",
    "i-751": "I-751",
    "i-90": "I-90",
    "n-400": "N-400",
    "i-539": "I-539",
    "g-1145": "G-1145",
    "g-1450": "G-1450",
    "g-1650": "G-1650",
    "i-131": "I-131",
    "i-539a": "I-539A",
    "i-693": "I-693",
    "i-134": "I-134",
}

SIGNATURE_SECTION_IDS = {"assinatura", "contato_assinatura"}
SPOUSE_SIGNATURE_SECTION_IDS = {"assinatura_conjuge"}
INTERPRETER_SECTION_IDS = {"interprete"}
PREPARER_SECTION_IDS = {"preparador"}

PART_RE = re.compile(r"Parte\s+(\d+)")


def load_registry() -> dict:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_questionnaire(slug: str) -> dict:
    path = ROOT / "data" / "questionnaires" / f"{slug}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_section(qdata: dict, ids: set[str]) -> dict | None:
    for s in qdata.get("sections", []):
        if s["id"] in ids:
            return s
    return None


def part_label(section: dict | None, lang: str = "pt") -> str | None:
    """Extrai só o número da parte do título da seção em português (ex.:
    "Parte 7 — Declaração...") e formata no idioma pedido -- assim
    funciona igual pros 8 formulários mesmo sem depender do overlay de
    tradução do questionário (que só existe pro I-90 por enquanto)."""
    if not section:
        return None
    m = PART_RE.search(section.get("title", ""))
    if m:
        word = "Part" if lang == "en" else "Parte"
        return f"{word} {m.group(1)}"
    return section.get("title")


def has_questions_in_section(qdata: dict, section_id: str) -> bool:
    return any(q.get("section") == section_id for q in qdata["questions"])


def fmt_money(amount) -> str:
    if amount is None:
        return "—"
    try:
        return f"US$ {amount:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(amount)


def _checklist_table(doc_items, styles, lang: str = "pt"):
    """Monta uma lista de documentos com caixa de seleção de verdade (um
    quadrado vetorial de tamanho fixo via CheckBox, não um caractere de
    fonte "☐" -- fontes base do reportlab não têm esse glyph, o mesmo
    problema já visto com "⚠"). Cada linha é [caixa] [rótulo do
    documento], pra poder imprimir e marcar um "X" à mão. O tamanho fixo da
    caixa (ao contrário de uma borda de célula) mantém o quadrado
    proporcional mesmo quando o rótulo quebra em várias linhas."""
    label_key = "label_en" if lang == "en" else "label"
    note_key = "note_en" if lang == "en" else "note"
    rows = []
    for doc_item in doc_items:
        text = doc_item.get(label_key) or doc_item["label"]
        note = doc_item.get(note_key) or doc_item.get("note")
        if note:
            text += f" <i>({note})</i>"
        rows.append([CheckBox(), Paragraph(text, styles["TableCell"])])
    table = Table(rows, colWidths=[20, 476])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (1, 0), (1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, -1), 2),
    ]))
    return table


def _wrap_row(cells, style):
    """Envolve cada célula em Paragraph(style) para o texto quebrar linha
    dentro da largura da coluna, em vez de vazar sobre a coluna vizinha."""
    return [Paragraph(str(c), style) for c in cells]


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ChecklistTitle", parent=styles["Title"], fontSize=17,
        spaceAfter=2, textColor=colors.HexColor("#1a1a2e")))
    styles.add(ParagraphStyle(
        name="ChecklistSubtitle", parent=styles["Normal"], fontSize=10.5,
        textColor=colors.HexColor("#555555"), spaceAfter=14))
    styles.add(ParagraphStyle(
        name="SectionHeader", parent=styles["Heading2"], fontSize=13,
        spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1a1a2e"),
        borderPadding=0))
    styles.add(ParagraphStyle(
        name="Body", parent=styles["Normal"], fontSize=10, leading=14,
        spaceAfter=4))
    styles.add(ParagraphStyle(
        name="Alert", parent=styles["Normal"], fontSize=10, leading=14,
        textColor=colors.HexColor("#7a1f1f"), backColor=colors.HexColor("#fdecec"),
        borderColor=colors.HexColor("#e0a0a0"), borderWidth=0.75,
        borderPadding=8, spaceBefore=6, spaceAfter=10))
    styles.add(ParagraphStyle(
        name="Small", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.HexColor("#666666")))
    styles.add(ParagraphStyle(
        name="TableHeader", parent=styles["Normal"], fontSize=9, leading=11,
        textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(
        name="TableCell", parent=styles["Normal"], fontSize=9, leading=12))
    return styles


def build_checklist(slug: str, out_dir: Path, lang: str = "pt") -> Path:
    form_code = FORM_SLUGS[slug]
    reg = load_registry()
    finfo = reg["forms"][form_code]
    qdata = load_questionnaire(slug)
    S = STRINGS[lang]

    applicant_section = find_section(qdata, SIGNATURE_SECTION_IDS)
    spouse_section = find_section(qdata, SPOUSE_SIGNATURE_SECTION_IDS)
    interpreter_section = find_section(qdata, INTERPRETER_SECTION_IDS)
    preparer_section = find_section(qdata, PREPARER_SECTION_IDS)

    official_url = finfo.get("official_url", "")
    instructions_url = finfo.get("instructions_url", "")
    online_url = finfo.get("filing_locations", {}).get("online", "https://my.uscis.gov/")
    processing_url = finfo.get("processing_times_url", "https://egov.uscis.gov/processing-times/")
    form_name = finfo.get("name", "") if lang == "en" else finfo.get("name_pt", finfo.get("name", ""))

    styles = build_styles()
    story = []

    # ---- Cabecalho ----
    story.append(Paragraph(
        S["protocol_title"].format(form_code=form_code), styles["ChecklistTitle"]))
    story.append(Paragraph(
        f"{form_name} &nbsp;·&nbsp; {S['edition_label']}: {finfo.get('edition', '—')} "
        f"&nbsp;·&nbsp; <a href='{official_url}' color='#3355aa'>{official_url}</a>",
        styles["ChecklistSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=0.75,
                             color=colors.HexColor("#cccccc")))

    # ---- Antes de enviar ----
    story.append(Paragraph(S["before_sending_title"], styles["SectionHeader"]))
    story.append(ListFlowable([
        ListItem(Paragraph(S["before_sending_1"], styles["Body"])),
        ListItem(Paragraph(
            S["before_sending_2"].format(official_url=official_url), styles["Body"])),
        ListItem(Paragraph(
            S["before_sending_3"].format(instructions_url=instructions_url), styles["Body"])),
    ], bulletType="bullet", leftIndent=14))

    # ---- Quem precisa assinar e onde ----
    story.append(Paragraph(S["who_signs_title"], styles["SectionHeader"]))
    raw_rows = [[S["col_who"], S["col_where"], S["col_when"]]]
    if applicant_section:
        raw_rows.append([
            S["row_applicant"], part_label(applicant_section, lang) or "—",
            S["row_applicant_when"],
        ])
    if spouse_section and has_questions_in_section(qdata, "assinatura_conjuge"):
        raw_rows.append([
            S["row_spouse"], part_label(spouse_section, lang) or "—",
            S["row_spouse_when"],
        ])
    if interpreter_section and has_questions_in_section(qdata, "interprete"):
        raw_rows.append([
            S["row_interpreter"], part_label(interpreter_section, lang) or "—",
            S["row_interpreter_when"],
        ])
    if preparer_section and has_questions_in_section(qdata, "preparador"):
        raw_rows.append([
            S["row_preparer"], part_label(preparer_section, lang) or "—",
            S["row_preparer_when"],
        ])
    # Cada célula precisa ser um Paragraph, não uma string pura -- uma string
    # crua numa célula de Table do reportlab não quebra linha dentro da
    # largura da coluna, e o texto vaza por cima da coluna vizinha.
    rows = [_wrap_row(raw_rows[0], styles["TableHeader"])] + [
        _wrap_row(r, styles["TableCell"]) for r in raw_rows[1:]
    ]
    table = Table(rows, colWidths=[130, 80, 260])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f4f8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Paragraph(S["who_signs_footnote"], styles["Small"]))

    # ---- Como assinar corretamente ----
    story.append(Paragraph(S["sign_correctly_title"], styles["SectionHeader"]))
    story.append(Paragraph(S["sign_alert"], styles["Alert"]))
    story.append(ListFlowable([
        ListItem(Paragraph(S["sign_valid"], styles["Body"])),
        ListItem(Paragraph(S["sign_fresh"], styles["Body"])),
        ListItem(Paragraph(S["sign_invalid"], styles["Body"])),
        ListItem(Paragraph(S["sign_online_note"], styles["Body"])),
    ], bulletType="bullet", leftIndent=14))

    # ---- Data da assinatura ----
    story.append(Paragraph(S["sign_date_title"], styles["SectionHeader"]))
    story.append(Paragraph(S["sign_date_body"], styles["Body"]))

    story.append(PageBreak())

    # ---- Taxa ----
    fees = finfo.get("fees", {})
    filing = fees.get("filing", {})
    story.append(Paragraph(S["fee_title"], styles["SectionHeader"]))
    raw_fee_rows = [[S["col_method"], S["col_amount"]]]
    if filing.get("online") is not None:
        raw_fee_rows.append([S["fee_online"], fmt_money(filing.get("online"))])
    if filing.get("paper") is not None:
        raw_fee_rows.append([S["fee_paper"], fmt_money(filing.get("paper"))])
    if filing.get("reduced") is not None:
        raw_fee_rows.append([S["fee_reduced"], fmt_money(filing.get("reduced"))])
    fee_rows = [_wrap_row(raw_fee_rows[0], styles["TableHeader"])] + [
        _wrap_row(r, styles["TableCell"]) for r in raw_fee_rows[1:]
    ]
    fee_table = Table(fee_rows, colWidths=[220, 100])
    fee_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f4f8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(fee_table)
    if filing.get("notes"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(filing["notes"], styles["Small"]))
    story.append(Paragraph(
        f"<b>{S['payable_to_label']}:</b> "
        f"{fees.get('payable_to', 'U.S. Department of Homeland Security')}. "
        f"{S['fee_confirm']}", styles["Body"]))

    # ---- Onde e como enviar ----
    story.append(Paragraph(S["where_send_title"], styles["SectionHeader"]))
    story.append(ListFlowable([
        ListItem(Paragraph(S["where_online"].format(online_url=online_url), styles["Body"])),
        ListItem(Paragraph(S["where_paper"].format(official_url=official_url), styles["Body"])),
    ], bulletType="bullet", leftIndent=14))

    # ---- Tempo de processamento ----
    story.append(Paragraph(S["processing_title"], styles["SectionHeader"]))
    story.append(Paragraph(
        S["processing_body"].format(processing_url=processing_url, form_code=form_code),
        styles["Body"]))

    # ---- Status do caso ----
    story.append(Paragraph(S["status_title"], styles["SectionHeader"]))
    story.append(ListFlowable([
        ListItem(Paragraph(S["status_1"], styles["Body"])),
        ListItem(Paragraph(S["status_2"], styles["Body"])),
        ListItem(Paragraph(S["status_3"], styles["Body"])),
        ListItem(Paragraph(S["status_4"], styles["Body"])),
    ], bulletType="bullet", leftIndent=14))

    # ---- Mudança de endereço (AR-11) ----
    story.append(Paragraph(S["address_title"], styles["SectionHeader"]))
    story.append(Paragraph(S["address_alert"], styles["Alert"]))
    story.append(ListFlowable([
        ListItem(Paragraph(S["address_online"], styles["Body"])),
        ListItem(Paragraph(S["address_paper"], styles["Body"])),
        ListItem(Paragraph(S["address_consequence"], styles["Body"])),
    ], bulletType="bullet", leftIndent=14))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#cccccc")))
    story.append(Paragraph(S["protocol_footer"], styles["Small"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-checklist-en.pdf" if lang == "en" else "-checklist.pdf"
    out_path = out_dir / f"{slug}{suffix}"
    doc = SimpleDocTemplate(
        str(out_path), pagesize=letter,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=S["protocol_title"].format(form_code=form_code),
    )
    doc.build(story)
    return out_path


def has_document_rules(slug: str) -> bool:
    return (ROOT / "data" / "document_rules" / f"{slug}.json").exists()


def _matched_documents(rules: list[dict], answers: dict) -> list[dict]:
    """Cada regra tem `questions` (lista de question_ids a checar) e ou
    `equals` (um valor) ou `equals_any` (lista de valores) -- `equals_any`
    existe pra formulários com dezenas de categorias que compartilham a
    mesma lista de documentos (ex: I-485), sem precisar duplicar a regra
    uma vez por valor."""
    matched = []
    for rule in rules:
        targets = rule.get("equals_any") or [rule.get("equals")]
        for qid in rule["questions"]:
            if answers.get(qid) in targets:
                matched.extend(rule["documents"])
                break
    return matched


def build_document_checklist(slug: str, answers: dict, out_dir: Path,
                              lang: str = "pt") -> Path:
    """Gera o checklist de documentos de suporte exigidos, condicionado às
    respostas de fato dadas no questionário (ex: motivo da aplicação do
    I-90) -- no mesmo espírito do checklist de evidências que a própria
    USCIS publica nas instruções de cada formulário.

    Requer data/document_rules/<slug>.json (ver data/document_rules/i-90.json
    para o formato). Levanta FileNotFoundError se ainda não existir para o
    formulário pedido -- só o I-90 está coberto por enquanto.
    """
    form_code = FORM_SLUGS[slug]
    rules_path = ROOT / "data" / "document_rules" / f"{slug}.json"
    rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
    S = STRINGS[lang]

    styles = build_styles()
    story = []

    story.append(Paragraph(
        S["documents_title"].format(form_code=form_code), styles["ChecklistTitle"]))
    story.append(Paragraph(S["documents_subtitle"], styles["ChecklistSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=0.75,
                             color=colors.HexColor("#cccccc")))

    note_key = "confidence_note_en" if lang == "en" else "confidence_note"
    story.append(Paragraph(
        rules_data.get(note_key, rules_data.get("confidence_note", "")),
        styles["Small"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph(S["documents_always_title"], styles["SectionHeader"]))
    always = rules_data.get("always", [])
    story.append(_checklist_table(always, styles, lang))

    matched = _matched_documents(rules_data.get("rules", []), answers)
    story.append(Spacer(1, 6))
    story.append(Paragraph(S["documents_specific_title"], styles["SectionHeader"]))
    if matched:
        story.append(_checklist_table(matched, styles, lang))
    else:
        story.append(Paragraph(S["documents_no_match"], styles["Body"]))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#cccccc")))
    story.append(Paragraph(S["documents_footer"], styles["Small"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-documentos-en.pdf" if lang == "en" else "-documentos.pdf"
    out_path = out_dir / f"{slug}{suffix}"
    doc = SimpleDocTemplate(
        str(out_path), pagesize=letter,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=S["documents_title"].format(form_code=form_code),
    )
    doc.build(story)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?", help="ex: i-130")
    parser.add_argument("--all", action="store_true",
                         help="gera para todos os 8 formularios")
    parser.add_argument("--out-dir", default=None,
                         help="diretorio de saida (padrao: output/checklists)")
    parser.add_argument("--documents", action="store_true",
                         help="gera tambem o checklist de documentos de suporte "
                              "(requer data/document_rules/<slug>.json)")
    parser.add_argument("--answers", default=None,
                         help="respostas JSON para o checklist de documentos "
                              "(ex: output/answers-i90-e2e.json)")
    parser.add_argument("--lang", default="pt", choices=["pt", "en"],
                         help="idioma do checklist gerado (padrao: pt)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "output" / "checklists"

    if args.all:
        slugs = list(FORM_SLUGS.keys())
    elif args.slug:
        slugs = [args.slug]
    else:
        parser.error("informe um slug de formulario ou use --all")
        return

    for slug in slugs:
        if slug not in FORM_SLUGS:
            print(f"AVISO: slug desconhecido, pulando: {slug}", file=sys.stderr)
            continue
        out_path = build_checklist(slug, out_dir, lang=args.lang)
        print(f"gerado: {out_path}")

        if args.documents:
            if not has_document_rules(slug):
                print(f"  (sem regras de documentos ainda para {slug}, pulando)")
                continue
            answers = {}
            if args.answers:
                answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
            doc_path = build_document_checklist(slug, answers, out_dir, lang=args.lang)
            print(f"gerado: {doc_path}")


if __name__ == "__main__":
    main()
