#!/usr/bin/env python3
"""
audit_checkbox_groups.py — Audita grupos de opção única (radio-style) no mapa de um formulário.

Por que existe:
    Em PDFs AcroForm do USCIS, um grupo de opções (ex: cor dos olhos, estado civil)
    costuma ser modelado como N campos de checkbox independentes, um por opção, cada
    um só distinguido por um índice (Campo[0], Campo[1], ..., Campo[N-1]). NADA garante
    que o índice 0 corresponda à primeira opção lógica ("Preto") — a ordem no PDF segue
    o layout visual do desenho original (ex.: grade 3x3 no papel), não a ordem lógica
    das respostas do questionário.

    Já encontramos, no I-130 real, mapeamentos com 7 de 9 índices de cor de olhos e
    6 de 6 de estado civil escritos no índice ERRADO: o PDF final marcava a opção
    errada silenciosamente, sem nenhum erro em tempo de execução.

    Este script cruza cada linha do mapa (pdf_field + check_if_answer) com o valor
    REAL gravado no PDF (lido do dicionário de aparência /AP de cada widget — a única
    fonte de verdade) e, quando o código não é autoexplicativo, busca o toolTip da
    opção correspondente no pacote XFA "template" (se existir) para dar uma pista do
    significado real em inglês. Rode isso para TODO formulário novo, para TODO grupo
    de 2+ opções, antes de considerar o mapeamento pronto — não é opcional.

Uso:
    python scripts/audit_checkbox_groups.py data/forms/I-130A.pdf data/mappings/I-130A.json

Saída: para cada grupo de 2+ opções, lista pdf_field / check_if_answer atual / código
real / pista de significado. Revise cada linha e confirme que check_if_answer bate com
a pista antes de aceitar o mapeamento. Sai com código 1 se algum código apareceu
duplicado num grupo ou se não foi possível achar nenhuma pista (não é prova de bug,
mas exige revisão manual).
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from pypdf import PdfReader

# Códigos cujo significado é óbvio pela própria string — não precisam de toolTip.
SELF_EVIDENT = {
    "APT": "apartamento", "STE": "suite/sala", "FLR": "andar",
}


def _qualified_name(widget) -> str:
    parts = []
    node = widget
    while node is not None:
        t = node.get("/T")
        if t:
            parts.insert(0, str(t))
        node = node.get("/Parent")
        if node is not None:
            node = node.get_object()
    return ".".join(parts)


def _field_type(widget) -> str | None:
    """Resolve /FT subindo /Parent se o widget não tiver o próprio (comum em kids)."""
    node = widget
    while node is not None:
        ft = node.get("/FT")
        if ft is not None:
            return str(ft)
        node = node.get("/Parent")
        if node is not None:
            node = node.get_object()
    return None


def real_on_values(reader: PdfReader) -> dict:
    """path completo do campo -> valor 'ligado' real, lido do /AP do próprio PDF.

    Só considera campos /Btn (checkbox/radio). Em campos de texto, /AP/N é um
    ÚNICO stream de aparência, não um dicionário de estados — iterar as chaves
    desse stream retorna entradas do próprio dicionário do stream (ex.: /BBox,
    /Type, /Filter), que não são valores "ligados" de nada. Sem esse filtro, um
    campo de texto comum pode aparecer com um "código" fantasma (ex.: "BBox")
    que não existe de verdade — já aconteceu ao auditar o I-130A.
    """
    result = {}
    for page in reader.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        for a in annots:
            obj = a.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            if _field_type(obj) != "/Btn":
                continue
            ap = obj.get("/AP")
            if not ap:
                continue
            n = ap.get_object().get("/N")
            if not n:
                continue
            n = n.get_object()
            try:
                states = [k for k in n.keys() if str(k) not in ("/Off", "/off")]
            except Exception:
                continue
            if states:
                result[_qualified_name(obj)] = str(states[0]).lstrip("/").strip()
    return result


def get_xfa_template(reader: PdfReader):
    """Retorna o XML do pacote XFA 'template' (onde ficam os toolTips), ou None."""
    try:
        acro = reader.trailer["/Root"]["/AcroForm"].get_object()
        xfa = acro.get("/XFA")
        if not xfa:
            return None
        xfa = xfa.get_object()
        if hasattr(xfa, "get_data"):
            return xfa.get_data().decode("utf-8", errors="replace")
        for i in range(0, len(xfa) - 1, 2):
            name = xfa[i].get_object() if hasattr(xfa[i], "get_object") else xfa[i]
            if str(name) == "template":
                return xfa[i + 1].get_object().get_data().decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def find_tooltip(template_xml: str, field_name: str, code: str):
    """Acha o toolTip do <field name=field_name> cujo <items> contém exatamente `code`
    (pode haver vários blocos com o mesmo nome, um por opção do grupo)."""
    for m in re.finditer(rf'<field name="{re.escape(field_name)}".*?</field', template_xml, re.DOTALL):
        block = m.group(0)
        items = re.search(r"<items.*?</items", block, re.DOTALL)
        if items and re.search(rf"<text[^>]*>{re.escape(code)}</text", items.group(0)):
            tt = re.search(r"<toolTip[^>]*>(.*?)</toolTip", block, re.DOTALL)
            if tt:
                return re.sub(r"\s+", " ", tt.group(1)).strip()
    return None


def audit(pdf_path: Path, mapping_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    real_on = real_on_values(reader)
    template_xml = get_xfa_template(reader)

    groups = defaultdict(list)
    for f in mapping.get("fields", []):
        if f.get("type") != "checkbox" or f.get("check_if_answer") is None:
            continue
        # Divide em "." só quando NÃO precedido de "\" — alguns campos (ex:
        # N-400 "P9_Line7\.c") têm um ponto literal escapado no próprio nome,
        # que um split ingênuo confundiria com separador de hierarquia e
        # cortaria o prefixo, agrupando errado (rótulo "c" em vez de
        # "P9_Line7.c"). Ver mesmo bug corrigido em fill_form.py.
        short = re.split(r"(?<!\\)\.", f["pdf_field"])[-1]
        m = re.match(r"^([^\[]+)", short)
        base = m.group(1) if m else short
        groups[base].append(f)

    multi = {k: v for k, v in groups.items() if len(v) >= 2}
    if not multi:
        print("Nenhum grupo de 2+ opções encontrado no mapa (nada a auditar aqui).")
        return 0

    problems = 0
    for base, rows in sorted(multi.items()):
        print(f"\n=== {base}  (qid: {rows[0].get('question_id')})  —  {len(rows)} opções ===")
        seen_codes = {}
        for f in rows:
            code = real_on.get(f["pdf_field"], "???")
            dup = code in seen_codes
            seen_codes[code] = f["pdf_field"]
            hint = SELF_EVIDENT.get(code.upper())
            if hint is None and template_xml:
                hint = find_tooltip(template_xml, base, code)
            flag = "  <<< CÓDIGO REPETIDO NO GRUPO, revise" if dup else ""
            print(f"  {f['pdf_field']:60s} check_if_answer={f.get('check_if_answer')!r:22s} "
                  f"codigo_real={code!r:8s} pista={hint or '(sem pista — confira manualmente)'}{flag}")
            if dup or hint is None:
                problems += 1

    print()
    if problems:
        print(f"REVISE: {problems} linha(s) acima sem pista automática ou com código "
              f"repetido. Confira manualmente se check_if_answer bate com a pista/código.")
    else:
        print("Nenhum problema óbvio encontrado — ainda assim, confira visualmente "
              "se check_if_answer bate com a pista de cada linha.")
    return problems


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("mapping", type=Path)
    args = ap.parse_args()
    problems = audit(args.pdf, args.mapping)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
