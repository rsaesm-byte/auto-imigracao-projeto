"""
fill_form.py — Preenche um formulário USCIS em PDF com as respostas coletadas.

Uso:
    python scripts/fill_form.py \\
        data/forms/i-130.pdf \\
        data/mappings/i-130.json \\
        answers.json \\
        output/i-130-filled.pdf \\
        [--questionnaire data/questionnaires/i-130.json]

Abordagem:
    1. Lê o mapeamento (question_id por campo) e as respostas do wizard.
    2. Resolve o valor de cada campo: texto direto, checkbox por check_if_answer,
       grupo de checkboxes (lista), campo de peso dividido em dígitos.
    3. Atualiza os campos AcroForm do PDF usando pypdf.
    4. Também tenta atualizar o stream XFA (XML interno) para compatibilidade
       com Adobe Reader, que renderiza XFA em vez de AcroForm.

Nota sobre XFA:
    Formulários USCIS usam XFA (Adobe XML Forms Architecture). O pypdf atualiza
    a camada AcroForm (compatibilidade), mas o Adobe Reader pode exibir a camada
    XFA por cima. O flag --patch-xfa ativa a atualização do XML interno — use-o
    para melhor resultado no Adobe Reader. Para preenchimento perfeito sem Adobe
    Reader, considere pdftk (ferramenta externa gratuita).
"""

import sys
import json
import re
import argparse
from copy import deepcopy
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        NameObject, create_string_object, ArrayObject,
        DictionaryObject, ByteStringObject, BooleanObject,
    )
except ImportError:
    print("ERROR: pypdf não instalado. Execute: pip install pypdf", file=sys.stderr)
    sys.exit(1)


# ── Resolução de valores ───────────────────────────────────────────────────────

def _last_qualified_segment(pdf_field: str) -> str:
    """Último segmento do caminho completo de um campo (com índice "[n]"
    incluso), respeitando pontos escapados com barra invertida.

    Alguns formulários (ex: N-400) têm campos cujo nome próprio contém um
    ponto literal (ex: "P9_Line7\\.c", referente ao item "7.c" impresso no
    formulário) — o PDF representa isso como "\\." dentro do nome. Um split
    ingênuo em "." (`pdf_field.split(".")[-1]`) quebra a string nesse ponto
    escapado e descarta o prefixo, produzindo um segmento errado ("c" em vez
    de "P9_Line7.c"). Bug descoberto no N-400 (ver xfa-hybrid-forms.md).
    """
    return re.split(r"(?<!\\)\.", pdf_field)[-1]


def _short_field_tag(pdf_field: str) -> str:
    """Como `_last_qualified_segment`, mas sem o índice "[n]" — é o nome de
    tag usado no pacote "datasets" do XFA (ver `_update_xfa_xml`).

    O nome do campo pode conter "\\." (ponto literal escapado — ver
    `_last_qualified_segment`), mas a tag XML real no datasets usa o ponto
    sem escape (ex: elemento `<P9_Line7.c>`, não `<P9_Line7\\.c>`) — por
    isso desfazemos o escape aqui antes de retornar.
    """
    short = _last_qualified_segment(pdf_field)
    m = re.match(r"^([^\[]+)", short)
    tag = m.group(1) if m else short
    return tag.replace("\\.", ".")


def _weight_digit(pdf_field: str, weight_str: str) -> str:
    """Divide peso (ex: '155') nos campos Pound1/2/3 (centena/dezena/unidade).

    Detecção pelo NOME do campo no PDF — mantida só por compatibilidade com
    mapeamentos antigos (I-130) que já contam com isso. Para formulários novos,
    prefira a chave "digit_split" no mapeamento (ver _weight_digit_by_position):
    o I-751, por exemplo, tem os mesmos 3 campos de dígito de peso só que
    nomeados "HeightInches1/2/3" (nome errado, herdado de outro desenho) — o
    nome do campo no PDF não é confiável pra detectar isso, o mapeamento sim.
    """
    digits = weight_str.strip().lstrip("0") or "0"
    padded = digits.zfill(3)[-3:]          # garante 3 dígitos, trunca à esquerda
    if "Pound1" in pdf_field:
        d = padded[0]
        return "" if d == "0" else d       # centena: omite zero à esquerda
    if "Pound2" in pdf_field:
        return padded[1]
    if "Pound3" in pdf_field:
        return padded[2]
    return weight_str


def _weight_digit_by_position(weight_str: str, position: int) -> str:
    """Divide peso (ex: '155') em 3 dígitos por posição explícita no mapeamento
    (1=centena, 2=dezena, 3=unidade) — não depende do nome do campo no PDF."""
    digits = weight_str.strip().lstrip("0") or "0"
    padded = digits.zfill(3)[-3:]
    d = padded[position - 1]
    if position == 1:
        return "" if d == "0" else d       # centena: omite zero à esquerda
    return d


def resolve_value(field: dict, answers: dict) -> str | None:
    """Retorna o valor pronto para o PDF, ou None se o campo deve ser ignorado."""
    qid = field.get("question_id", "")
    if not qid or qid == "_ignore":
        return None

    answer = answers.get(qid)
    if answer is None:
        return None

    ftype  = field.get("type", "text")
    check  = field.get("check_if_answer")       # valor (ou lista de valores) que ativa este checkbox
    pdf_fn = field.get("pdf_field", "")

    # "value_map" traduz a resposta de uma pergunta de negócio (ex.: "servico"
    # = "cos_f1") para o código exigido pelo PDF (ex.: "F1") antes de seguir o
    # fluxo normal. Usado quando UMA pergunta precisa alimentar tanto um grupo
    # de checkbox (via check_if_answer em lista, ver abaixo) quanto um campo de
    # texto/choice com um código diferente do valor da resposta. Se a resposta
    # não está no mapa (ex.: "eos" não tem status de destino), o campo fica
    # sem preencher — não é erro, é o comportamento esperado (Item 2 do I-539
    # só se aplica a quem pediu mudança de status).
    value_map = field.get("value_map")
    if value_map is not None:
        mapped = value_map.get(str(answer))
        if mapped is None:
            return None
        answer = mapped

    # ── Texto / Data / Select ──────────────────────────────────────────────
    if ftype in ("text", "date", "select", "choice", "unknown"):
        # Peso dividido em 3 campos de dígito — preferir a chave explícita do
        # mapeamento ("digit_split": 1|2|3); o nome do campo no PDF não é
        # confiável entre formulários (ver nota em _weight_digit).
        digit_split = field.get("digit_split")
        if digit_split:
            return _weight_digit_by_position(str(answer), digit_split)
        if any(p in pdf_fn for p in ("Pound1", "Pound2", "Pound3")):
            return _weight_digit(pdf_fn, str(answer))
        return str(answer)

    # ── Checkbox ───────────────────────────────────────────────────────────
    if ftype == "checkbox":
        if check is None:
            # Checkbox simples sem check_if_answer (raro)
            return "/Yes" if answer else "/Off"
        if isinstance(answer, list):
            # checkbox_group: a resposta é lista de valores selecionados
            target = check if isinstance(check, list) else [check]
            return "/Yes" if any(c in answer for c in target) else "/Off"
        if isinstance(check, list):
            # UMA pergunta de escolha única cujo valor deve ativar este
            # checkbox quando bate com QUALQUER um de vários valores (ex.:
            # 3 dos 4 valores de "servico" mapeiam para "mudança de status").
            return "/Yes" if str(answer) in check else "/Off"
        return "/Yes" if str(answer) == str(check) else "/Off"

    # ── Radio (PDF radio = conjunto de checkboxes mutuamente exclusivos) ───
    if ftype == "radio":
        if check is not None:
            if isinstance(check, list):
                return "/Yes" if str(answer) in check else "/Off"
            return "/Yes" if str(answer) == str(check) else "/Off"
        return str(answer)

    return str(answer)


# ── Coleta dos valores para todos os campos ───────────────────────────────────

def build_field_values(fields: list[dict], answers: dict) -> dict[str, str]:
    """Constrói {pdf_field_path: value} para todos os campos mapeados."""
    result: dict[str, str] = {}
    for f in fields:
        val = resolve_value(f, answers)
        if val is not None:
            result[f["pdf_field"]] = val
    return result


# ── Preenchimento AcroForm via pypdf ──────────────────────────────────────────

def _get_field_on_value(widget) -> str:
    """Descobre o valor 'ligado' de um checkbox consultando o /AP (appearances)."""
    try:
        ap = widget.get("/AP")
        if ap:
            n_dict = ap.get("/N")
            if n_dict:
                for key in n_dict:
                    if str(key) not in ("/Off", "/off"):
                        return str(key)
    except Exception:
        pass
    return "/Yes"


def _iter_widgets(reader: PdfReader):
    """Gera (page_index, widget_object) para todos os campos do formulário."""
    for page_idx, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots:
            try:
                obj = ref.get_object()
            except Exception:
                continue
            if obj.get("/Subtype") == "/Widget":
                yield page_idx, obj


def _build_writer_widgets(writer: PdfWriter) -> dict[str, list]:
    """Mapa nome completo do campo -> lista de widgets no writer.

    Usa os objetos do WRITER (não do reader) para poder editar. Uma lista com
    mais de um widget acontece quando o mesmo campo aparece em mais de uma
    página (ex: nome do peticionário repetido na folha de continuação).
    """
    writer_widgets: dict[str, list] = {}
    for page_idx, _ in enumerate(writer.pages):
        page = writer.pages[page_idx]
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots:
            try:
                obj = ref.get_object()
            except Exception:
                continue
            if obj.get("/Subtype") != "/Widget":
                continue
            full_name = _resolve_widget_name(obj)
            writer_widgets.setdefault(full_name, []).append(obj)
    return writer_widgets


def fill_acroform(writer: PdfWriter, reader: PdfReader, field_values: dict[str, str]) -> int:
    """
    Atualiza campos AcroForm do PDF.

    Estratégia:
    - Itera widgets em cada página.
    - Resolve o nome completo (path hierárquico) de cada widget.
    - Se o path está em field_values, define o valor.
    - Para checkboxes/radio: usa o valor "/Yes"/"/Off"; tenta descobrir o
      valor "on" real do campo.

    Retorna o número de campos efetivamente preenchidos.
    """
    # Mapa inverso: nome parcial/completo → lista de widgets no writer
    # Precisamos dos objetos do WRITER (não do reader) para poder editar.
    writer_widgets = _build_writer_widgets(writer)

    filled = 0
    for pdf_field, value in field_values.items():
        widgets = writer_widgets.get(pdf_field, [])
        if not widgets:
            # Tenta match pelo nome parcial (último componente, com índice)
            tail = _last_qualified_segment(pdf_field)
            for key, wlist in writer_widgets.items():
                if key.endswith(tail) or _last_qualified_segment(key) == tail:
                    widgets = wlist
                    break

        for widget in widgets:
            try:
                ftype = widget.get("/FT")
                if ftype in ("/Btn",):
                    # Checkbox / radio
                    on_val = _get_field_on_value(widget) if value == "/Yes" else "/Off"
                    actual_val = on_val if value == "/Yes" else NameObject("/Off")
                    widget.update({
                        NameObject("/V"): NameObject(actual_val),
                        NameObject("/AS"): NameObject(actual_val),
                    })
                else:
                    # Texto, select, etc.
                    widget.update({
                        NameObject("/V"): create_string_object(value),
                        NameObject("/DV"): create_string_object(value),
                    })
                filled += 1
            except Exception as e:
                print(f"  Aviso: não foi possível preencher '{pdf_field}': {e}",
                      file=sys.stderr)

    return filled


def _resolve_widget_name(widget) -> str:
    """Sobe a hierarquia de /Parent para montar o nome completo do campo."""
    parts = []
    obj = widget
    while obj is not None:
        t = obj.get("/T")
        if t:
            parts.append(str(t))
        parent_ref = obj.get("/Parent")
        if parent_ref is None:
            break
        try:
            obj = parent_ref.get_object()
        except Exception:
            break
    return ".".join(reversed(parts))


# ── Atualização do stream XFA (opcional) ─────────────────────────────────────

def _replace_stream_data_raw(stream_obj, new_data: bytes) -> None:
    """
    Substitui o conteúdo de um StreamObject por bytes NÃO comprimidos.

    get_data() sempre retorna o conteúdo já descomprimido. Se gravássemos esses
    bytes de volta em stream_obj._data sem tocar em /Filter, o dicionário do
    stream continuaria declarando /FlateDecode sobre dados que não são mais
    zlib-válidos — qualquer leitor (inclusive nosso próprio inspecionador e o
    Adobe Reader) falha ao descomprimir e o pacote XFA vira bytes vazios.
    Por isso removemos /Filter e /DecodeParms: o stream passa a ser gravado
    como dado bruto, maior mas consistente com o que está de fato armazenado.
    """
    if "/Filter" in stream_obj:
        del stream_obj["/Filter"]
    if "/DecodeParms" in stream_obj:
        del stream_obj["/DecodeParms"]
    stream_obj._data = new_data
    stream_obj.update({NameObject("/Length"): len(new_data)})


def patch_xfa_stream(writer: PdfWriter, field_values: dict[str, str]) -> bool:
    """
    Atualiza o pacote "datasets" do XFA com os valores dos campos, para que o
    Adobe Reader (que prioriza XFA sobre AcroForm quando o PDF tem os dois)
    mostre os mesmos dados já gravados no AcroForm.

    Retorna True se encontrou e atualizou o stream XFA, False caso contrário.
    """
    try:
        root    = writer._root_object
        acroform = root.get("/AcroForm")
        if not acroform:
            return False
        xfa_ref = acroform.get("/XFA")
        if not xfa_ref:
            return False

        writer_widgets = _build_writer_widgets(writer)

        # Descreve cada campo respondido de forma estruturada: nome curto (tag no
        # datasets), tipo, e para checkboxes o valor "ligado" REAL do widget (lido
        # do /AP do próprio PDF — nunca adivinhado), necessário porque grupos de
        # opção única (ex: cor dos olhos) guardam esse código no datasets, não um
        # booleano. Ver _update_xfa_xml para o porquê.
        entries: list[dict] = []
        for pdf_field, value in field_values.items():
            tag = _short_field_tag(pdf_field)

            widgets = writer_widgets.get(pdf_field, [])
            is_checkbox = bool(widgets) and widgets[0].get("/FT") == "/Btn"

            if is_checkbox:
                on_value = _get_field_on_value(widgets[0]).lstrip("/")
                entries.append({"tag": tag, "kind": "checkbox",
                                 "selected": value == "/Yes", "on_value": on_value})
            else:
                entries.append({"tag": tag, "kind": "text", "value": value})

        # XFA pode ser uma referência direta a um stream ou um array
        # de pares [nome, stream]. O dataset fica em "datasets".
        xfa_obj = xfa_ref.get_object() if hasattr(xfa_ref, "get_object") else xfa_ref

        if isinstance(xfa_obj, ArrayObject):
            # Pares: ["preamble", stream, "datasets", stream, ...]
            for i in range(0, len(xfa_obj) - 1, 2):
                name_obj = xfa_obj[i].get_object() if hasattr(xfa_obj[i], "get_object") else xfa_obj[i]
                if str(name_obj) == "datasets":
                    stream_obj = xfa_obj[i + 1].get_object()
                    xml_bytes = stream_obj.get_data()
                    updated = _update_xfa_xml(xml_bytes, entries)
                    _replace_stream_data_raw(stream_obj, updated)
                    return True
        else:
            # Stream único
            xml_bytes = xfa_obj.get_data()
            updated = _update_xfa_xml(xml_bytes, entries)
            _replace_stream_data_raw(xfa_obj, updated)
            return True

    except Exception as exc:
        print(f"  Aviso XFA: {exc}", file=sys.stderr)
    return False


def _update_xfa_xml(xml_bytes: bytes, entries: list[dict]) -> bytes:
    """
    Substitui valores dentro do pacote XFA "datasets".

    O "datasets" do XFA NÃO usa <field name="..."><value><text>...</text></value></field>
    (isso é a estrutura do pacote "template"). Ele guarda os dados como XML simples,
    um elemento por campo, nomeado com o SOM name curto do campo. Formatos observados
    na prática:
        <Pt2Line11_SSN/>                             campo de texto, vazio
        <CheckBox1>0</CheckBox1>                     checkbox isolado cujo on-value
            REAL (lido do /AP) é literalmente a string "1" — "0"/"1" aqui não é uma
            convenção universal, é uma coincidência deste campo específico.
        <Part3_Checkbox>C</Part3_Checkbox>           OUTRO checkbox isolado, mesma
            estrutura (1 widget, 1 nó de dado), mas cujo on-value real é "C" — usar
            "1" genérico aqui gravaria um código sem sentido. Já corrigido: qualquer
            grupo (1 candidato ou N) que caia em M=1 elemento real usa o on-value
            verdadeiro do widget selecionado (lido do /AP em patch_xfa_stream),
            nunca "1"/"0" hardcoded. NÃO reintroduza esse atalho.
        <Pt3Line5_EyeColor>BRN</Pt3Line5_EyeColor>   grupo de opção única: o AcroForm
            tem 9 campos de checkbox (um por cor), mas o datasets tem UM elemento só,
            guardando o código do widget marcado (ex: "BRN" p/ Brown) — nunca um
            booleano.
    Por isso usamos um parser XML (não regex) para navegar a árvore.
    """
    import xml.etree.ElementTree as ET
    from collections import defaultdict

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes

    tag_elements: dict[str, list] = defaultdict(list)
    for elem in root.iter():
        tag_elements[elem.tag.rsplit("}", 1)[-1]].append(elem)

    by_tag: dict[str, list] = defaultdict(list)
    for e in entries:
        by_tag[e["tag"]].append(e)

    for tag, group in by_tag.items():
        targets = tag_elements.get(tag, [])
        if not targets:
            # Nada no datasets com esse nome — o template pode ter esse campo com
            # bind="none" (não participa do modelo de dados; só existe no AcroForm).
            continue

        is_checkbox_group = all(e["kind"] == "checkbox" for e in group)

        if is_checkbox_group and len(targets) == 1:
            # Um nó de dado real, N candidato(s) (grupo de opção única OU um
            # único checkbox independente — mesmo tratamento). O on-value real
            # do widget (ex: "C", "A") é o que vai no nó, NUNCA "1" genérico:
            # já vimos casos onde o próprio template define on="C"/off="" para
            # um checkbox isolado, então "1" seria um código sem sentido ali.
            selected = [e for e in group if e["selected"]]
            if len(selected) == 1:
                targets[0].text = selected[0]["on_value"]
            # Nenhuma seleção (pergunta não respondida): deixa o nó como está.
            continue

        if is_checkbox_group:
            # M == N: um nó por opção. Grava o on-value real quando marcado;
            # no não marcado, mantém "0" como melhor esforço (não temos como
            # ler o "off-value" específico de cada opção sem reprocessar o
            # template por completo, mas o AcroForm — fonte de verdade — já
            # está correto de qualquer forma).
            for elem, e in zip(targets, group):
                elem.text = e["on_value"] if e["selected"] else "0"
            continue

        # Campos de texto. Se todas as respostas do grupo são idênticas (o mesmo
        # campo repetido em mais de uma página, ex: nome do peticionário na folha
        # de continuação, ligado ao MESMO nó de dado), grava o valor em todos os
        # nós reais encontrados.
        values = {e["value"] for e in group}
        if len(values) == 1:
            only_value = next(iter(values))
            for elem in targets:
                elem.text = only_value
            continue

        # Valores diferentes para o mesmo nome (ex: país de nascimento de filhos
        # diferentes, mesmo subform repetido). Sem inspecionar o "template" não dá
        # pra confirmar a correspondência exata — usamos a ordem de aparição como
        # melhor esforço, que é o padrão observado nesses grupos repetidos.
        if len(targets) != len(group):
            print(f"  Info XFA: \"{tag}\" preenchido por ordem de aparição "
                  f"({len(group)} valor(es) para {len(targets)} elemento(s)).",
                  file=sys.stderr)
        for elem, e in zip(targets, group):
            elem.text = e["value"]

    return ET.tostring(root, encoding="utf-8")


# ── Validação de campos obrigatórios ─────────────────────────────────────────

def validate_required(questionnaire: dict, answers: dict) -> list[str]:
    missing = []
    for q in questionnaire.get("questions", []):
        if not q.get("required"):
            continue
        show_if = q.get("show_if")
        if show_if:
            dep = answers.get(show_if["question"])
            expected = show_if.get("equals")
            if isinstance(expected, list):
                if str(dep) not in [str(e) for e in expected]:
                    continue
            elif dep != expected:
                continue
        if not answers.get(q["id"]):
            missing.append(f"[{q['id']}] {q['label']}")
    return missing


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preenche formulário USCIS em PDF com respostas do wizard."
    )
    parser.add_argument("pdf",      help="PDF de entrada (ex: data/forms/i-130.pdf)")
    parser.add_argument("mapping",  help="Mapeamento JSON (ex: data/mappings/i-130.json)")
    parser.add_argument("answers",  help="Respostas JSON (ex: output/answers-joao.json)")
    parser.add_argument("output",   help="PDF de saída (ex: output/i-130-joao.pdf)")
    parser.add_argument("--questionnaire", "-q",
                        help="Questionário JSON para validar campos obrigatórios")
    parser.add_argument("--patch-xfa", action="store_true",
                        help="Tenta atualizar o stream XFA interno (melhor p/ Adobe Reader)")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Pula a checagem de campos obrigatórios")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    map_path = Path(args.mapping)
    ans_path = Path(args.answers)
    out_path = Path(args.output)

    for p, label in [(pdf_path, "PDF"), (map_path, "mapeamento"), (ans_path, "respostas")]:
        if not p.exists():
            print(f"ERRO: {label} não encontrado: {p}", file=sys.stderr)
            sys.exit(1)

    # ── Carrega dados ──────────────────────────────────────────────────────
    mapping_data = json.loads(map_path.read_text(encoding="utf-8"))
    fields       = mapping_data["fields"]
    answers      = json.loads(ans_path.read_text(encoding="utf-8"))

    print(f"Formulário : {mapping_data.get('form', '?')}")
    print(f"Respostas  : {len(answers)} campos preenchidos pelo usuário")

    # ── Validação opcional ─────────────────────────────────────────────────
    if args.questionnaire and not args.skip_validation:
        q_data  = json.loads(Path(args.questionnaire).read_text(encoding="utf-8"))
        missing = validate_required(q_data, answers)
        if missing:
            print(f"\nATENÇÃO: {len(missing)} campo(s) obrigatório(s) sem resposta:")
            for m in missing:
                print(f"  - {m}")
            print()

    # ── Resolve valores ────────────────────────────────────────────────────
    field_values = build_field_values(fields, answers)
    text_count  = sum(1 for v in field_values.values() if not v.startswith("/"))
    check_count = sum(1 for v in field_values.values() if v == "/Yes")
    print(f"Campos resolvidos: {len(field_values)} "
          f"({text_count} texto, {check_count} checkboxes marcados)")

    # ── Lê e clona PDF ────────────────────────────────────────────────────
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.clone_reader_document_root(reader)

    # ── Preenche AcroForm ─────────────────────────────────────────────────
    filled = fill_acroform(writer, reader, field_values)
    print(f"AcroForm  : {filled} widget(s) atualizado(s)")

    # /NeedAppearances avisa o leitor de PDF para regenerar a aparência visual
    # dos campos a partir do /V atual em vez de usar a aparência (/AP) antiga
    # já gravada no PDF em branco. Sem isso, campos "choice" não-editáveis
    # (ex.: dropdown de status atual do I-539) continuam mostrando a
    # aparência em branco original em qualquer leitor que não seja o Adobe
    # Reader (que ignora isso e prioriza a camada XFA) — mesmo com o /V
    # correto já gravado. Bug real encontrado ao renderizar o I-539 preenchido
    # com pymupdf: o valor "B2" estava certo no /V e no XFA datasets, mas
    # invisível na página até setar essa flag.
    writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)

    # ── Patch XFA (opcional) ──────────────────────────────────────────────
    if args.patch_xfa:
        ok = patch_xfa_stream(writer, field_values)
        print(f"XFA patch : {'aplicado' if ok else 'não encontrado / ignorado'}")

    # ── Salva PDF ─────────────────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fout:
        writer.write(fout)

    size_kb = out_path.stat().st_size // 1024
    print(f"\nPDF salvo : {out_path}  ({size_kb} KB)")
    print()
    print("NOTA: Formulários USCIS usam XFA (Adobe XML Forms).")
    print("      Abra em Adobe Acrobat Reader para visualizar corretamente.")
    print("      Use --patch-xfa para melhor resultado no Adobe Reader.")
    if not args.patch_xfa:
        print("      Para preenchimento garantido: pdftk fill_form (ferramenta externa).")


if __name__ == "__main__":
    main()
