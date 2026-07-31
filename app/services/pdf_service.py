"""Wrapper fino em torno das funções puras de scripts/fill_form.py e
scripts/generate_checklist.py, para uso a partir do app web.

As quatro funções de fill_form.py (build_field_values, fill_acroform,
patch_xfa_stream, validate_required) não têm estado global e já são seguras
para chamar concorrentemente — a única coisa que muda aqui em relação ao
main() do CLI é que out_path é por usuário/por submissão, nunca um
diretório output/ compartilhado.
"""
from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from scripts.fill_form import (build_field_values, fill_acroform,
                                patch_xfa_stream, validate_required)
from scripts.generate_checklist import (build_checklist,
                                         build_document_checklist,
                                         has_document_rules)

ROOT = Path(__file__).resolve().parent.parent.parent


def fill_form_for_submission(form_slug: str, answers: dict, out_path: Path,
                              patch_xfa: bool = True) -> Path:
    """Preenche o PDF oficial de `form_slug` com `answers` e salva em `out_path`."""
    pdf_path = ROOT / "data" / "forms" / f"{form_slug}.pdf"
    mapping_path = ROOT / "data" / "mappings" / f"{form_slug}.json"

    mapping_data = json.loads(mapping_path.read_text(encoding="utf-8"))
    fields = mapping_data["fields"]

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.clone_reader_document_root(reader)

    field_values = build_field_values(fields, answers)
    fill_acroform(writer, reader, field_values)
    if patch_xfa:
        patch_xfa_stream(writer, field_values)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fout:
        writer.write(fout)
    return out_path


def missing_required_fields(form_slug: str, answers: dict) -> list[str]:
    """Reaproveita validate_required() de fill_form.py para a tela de revisão."""
    q_path = ROOT / "data" / "questionnaires" / f"{form_slug}.json"
    q_data = json.loads(q_path.read_text(encoding="utf-8"))
    return validate_required(q_data, answers)


def generate_checklist_for_submission(form_slug: str, out_dir: Path,
                                       lang: str = "pt") -> Path:
    """Reaproveita build_checklist() de generate_checklist.py como está —
    já recebe out_dir como parâmetro, nenhum wrapper de verdade é necessário
    além de resolver o caminho por-submissão."""
    return build_checklist(form_slug, out_dir, lang=lang)


def document_checklist_available(form_slug: str) -> bool:
    return has_document_rules(form_slug)


def generate_document_checklist_for_submission(form_slug: str, answers: dict,
                                                 out_dir: Path,
                                                 lang: str = "pt") -> Path:
    """Checklist de documentos de suporte condicionado às respostas reais —
    só disponível para formulários com data/document_rules/<slug>.json."""
    return build_document_checklist(form_slug, answers, out_dir, lang=lang)


# Cada uma das 4 cartas de terceiro do I-539 agora é sua própria submissão
# (form_slug próprio, ver app/wizard.py::CARTA_LETTER_SLUGS), em vez de
# tudo vir junto de uma resposta combinada de i-539-cartas. Cada builder já
# checa sua própria pergunta de gate e devolve None se a carta não for
# necessária para aquele caso -- generate() em wizard.py trata None como
# "carta não necessária", não como erro.
_CARTA_LETTER_BUILDERS = None


def _load_carta_letter_builders():
    global _CARTA_LETTER_BUILDERS
    if _CARTA_LETTER_BUILDERS is None:
        from scripts.generate_cartas_i539 import (build_address_letter,
                                                    build_business_caretaker_letter,
                                                    build_employer_letter,
                                                    build_sponsorship_letter)
        _CARTA_LETTER_BUILDERS = {
            "i539-carta-endereco": build_address_letter,
            "i539-carta-patrocinio": build_sponsorship_letter,
            "i539-carta-empregador": build_employer_letter,
            "i539-carta-empresa": build_business_caretaker_letter,
        }
    return _CARTA_LETTER_BUILDERS


def generate_carta_letter_for_submission(form_slug: str, answers: dict,
                                          out_path: Path) -> Path | None:
    builder = _load_carta_letter_builders()[form_slug]
    return builder(answers, out_path)


def generate_narrative_letter_for_submission(answers: dict, out_path: Path) -> Path | None:
    """Carta narrativa pessoal do I-539 (i-539-cartas) -- redigida por IA
    (Gemini) com fallback automático para o resumo cru das respostas se a
    chave não estiver configurada ou a chamada falhar. Ver
    scripts/generate_cartas_i539.py::build_narrative_document."""
    from scripts.generate_cartas_i539 import build_narrative_document, load_questionnaire
    qdata = load_questionnaire()
    return build_narrative_document(answers, qdata, out_path)
