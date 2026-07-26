"""
build_mapping_i765.py — Aplica os question_id ao esqueleto de mapeamento do I-765.

Uso:
    python scripts/build_mapping_i765.py
    # Sobrescreve data/mappings/i-765.json com question_id preenchidos.

Nota sobre nomes de campo enganosos (confirmado de novo neste formulário):
    - "Line17a/b_CountryOfBirth" na verdade são os países de CIDADANIA (item 14),
      não país de nascimento (esse é "Line18c_CountryOfBirth", item 15.C).
    - "Line19_DOB" = Data de Nascimento (item 16); "Line19_Checkbox" = pergunta
      totalmente diferente (item 12, "já pediu I-765 antes?") — mesmo prefixo
      "Line19", campos sem nenhuma relação. Confira sempre o toolTip completo.
    - Vários campos do Part 4 (intérprete) e Part 5 (preparador) têm prefixo
      interno "Pt5Line3..." ou "Pt6Line3..." só por causa de como o desenho foi
      copiado de um formulário pra outro — o toolTip confirma a qual Parte cada
      um pertence de verdade.

Nota sobre grupos sem tooltip via XFA:
    "Part2Line5_Checkbox" (mesmo endereço?), "Line19_Checkbox" (já pediu antes?),
    "PtLine29_YesNo" e "PtLine30b_YesNo" (perguntas de antecedente criminal) não
    tinham <field> correspondente no pacote XFA "template" com esse nome exato
    (prováveis campos gerados dinamicamente). O significado foi confirmado lendo
    o texto extraído da própria página (page.extract_text()), não adivinhado.

Nota sobre "Line3a/b/c" (índice não é ordem de leitura, mesmo em campo de texto):
    Existem duas instâncias de "Line3a_FamilyName" (outro nome 3 e outro nome 4),
    ambas mostrando os mesmos dois candidatos de toolTip ("3.A" e "4.A") por não
    haver correspondência direta. Como são campos de texto, não há /AP para
    desambiguar — confirmado via posição vertical (/Rect): índice [1] fica ACIMA
    (item 3) e índice [0] fica ABAIXO (item 4). Não assuma que o índice segue a
    ordem de leitura — meça.
"""

import json
import re
from pathlib import Path


def cb(question_id: str, check_if_answer: str) -> dict:
    return {"type": "checkbox", "question_id": question_id, "check_if_answer": check_if_answer}


def txt(question_id: str) -> dict:
    return {"type": "text", "question_id": question_id}


MAPPING_RULES: dict[str, object] = {

    # Campos administrativos / advogado — fora do escopo do questionário do cliente
    "PDF417BarCode1":        {"question_id": "_ignore", "notes": "Código de barras automático"},
    "CheckBox1":             {"question_id": "_ignore", "notes": "Checkbox G-28 anexado (advogado)"},
    "attorneyBarNumber":     {"question_id": "_ignore", "notes": "OAB/Bar do advogado"},
    "USCISELISAcctNumber":   {"question_id": "_ignore", "notes": "Conta USCIS Online do advogado"},

    # ── Parte 1 — Motivo da aplicação ───────────────────────────────────────────
    # índice segue a ordem lógica aqui (confirmado via /AP: 1, 2, 3)
    "Part1_Checkbox": [cb("motivo_aplicacao", "inicial"), cb("motivo_aplicacao", "substituicao"), cb("motivo_aplicacao", "renovacao")],

    # ── Parte 2 — Informações sobre você ────────────────────────────────────────
    "Line1a_FamilyName": {"question_id": "nome_sobrenome"},
    "Line1b_GivenName":  {"question_id": "nome_nome"},
    "Line1c_MiddleName": {"question_id": "nome_meio"},

    "Line2a_FamilyName": {"question_id": "outro_nome2_sobrenome"},
    "Line2b_GivenName":  {"question_id": "outro_nome2_nome"},
    "Line2c_MiddleName": {"question_id": "outro_nome2_meio"},
    # índice [1] = item 3 (posição mais alta na página), índice [0] = item 4 (mais baixa)
    "Line3a_FamilyName": [txt("outro_nome4_sobrenome"), txt("outro_nome3_sobrenome")],
    "Line3b_GivenName":  [txt("outro_nome4_nome"), txt("outro_nome3_nome")],
    "Line3c_MiddleName": [txt("outro_nome4_meio"), txt("outro_nome3_meio")],

    # Endereço de correio (item 5)
    "Line4a_InCareofName":        {"question_id": "end_correio_cuidados_de"},
    "Line4b_StreetNumberName":    {"question_id": "end_correio_rua"},
    "Pt2Line5_Unit": [cb("end_correio_tipo_unidade", "ste"), cb("end_correio_tipo_unidade", "flr"), cb("end_correio_tipo_unidade", "apt")],
    "Pt2Line5_AptSteFlrNumber":   {"question_id": "end_correio_num_unidade"},
    "Pt2Line5_CityOrTown":        {"question_id": "end_correio_cidade"},
    "Pt2Line5_State":             {"question_id": "end_correio_estado"},
    "Pt2Line5_ZipCode":           {"question_id": "end_correio_cep"},

    # Item 6 — endereço físico é igual ao de correio?
    "Part2Line5_Checkbox": [cb("end_fisico_igual_correio", "nao"), cb("end_fisico_igual_correio", "sim")],

    # Endereço físico (item 7, só relevante se item 6 = não)
    "Pt2Line7_StreetNumberName":  {"question_id": "end_fisico_rua"},
    "Pt2Line7_Unit": [cb("end_fisico_tipo_unidade", "ste"), cb("end_fisico_tipo_unidade", "flr"), cb("end_fisico_tipo_unidade", "apt")],
    "Pt2Line7_AptSteFlrNumber":   {"question_id": "end_fisico_num_unidade"},
    "Pt2Line7_CityOrTown":        {"question_id": "end_fisico_cidade"},
    "Pt2Line7_State":             {"question_id": "end_fisico_estado"},
    "Pt2Line7_ZipCode":           {"question_id": "end_fisico_cep"},

    # Outras informações
    "Line7_AlienNumber":       {"question_id": "alien_number"},
    "Line8_ElisAccountNumber": {"question_id": "uscis_online"},
    "Line9_Checkbox":  [cb("sexo", "feminino"), cb("sexo", "masculino")],
    "Line10_Checkbox": [cb("estado_civil", "viuvo"), cb("estado_civil", "divorciado"),
                         cb("estado_civil", "solteiro"), cb("estado_civil", "casado")],
    "Line19_Checkbox": [cb("pediu_i765_antes", "nao"), cb("pediu_i765_antes", "sim")],
    "Line12b_SSN": {"question_id": "ssn"},
    # ATENÇÃO: nome interno diz "CountryOfBirth" mas o toolTip confirma que é
    # país de CIDADANIA (item 14), não nascimento (esse é Line18c, item 15.C).
    "Line17a_CountryOfBirth": {"question_id": "cidadania_pais1",
        "notes": "Nome interno ENGANOSO: tooltip diz item 14.A (Country/Countries of Citizenship), não nascimento"},
    "Line17b_CountryOfBirth": {"question_id": "cidadania_pais2",
        "notes": "Idem — item 14.B, cidadania"},

    # Local de nascimento (item 15)
    "Line18a_CityTownOfBirth": {"question_id": "nascimento_cidade"},
    "Line18b_CityTownOfBirth": {"question_id": "nascimento_estado_provincia"},
    "Line18c_CountryOfBirth":  {"question_id": "nascimento_pais"},
    "Line19_DOB": {"question_id": "data_nascimento",
        "notes": "Nome interno 'Line19' colide com Line19_Checkbox (item 12) — são campos totalmente diferentes"},

    # Última entrada nos EUA (itens 17-26)
    "Line20a_I94Number":         {"question_id": "i94_numero"},
    "Line20b_Passport":          {"question_id": "passaporte_numero"},
    "Line20c_TravelDoc":         {"question_id": "doc_viagem_numero"},
    "Line20d_CountryOfIssuance": {"question_id": "passaporte_pais_emissao"},
    "Line20e_ExpDate":           {"question_id": "passaporte_data_expiracao"},
    "Line21_DateOfLastEntry":    {"question_id": "ultima_entrada_data"},
    "place_entry":               {"question_id": "ultima_entrada_local",
        "notes": "Sem tooltip via XFA; confirmado por texto da página (item 23)"},
    "Line23_StatusLastEntry":    {"question_id": "ultima_entrada_status"},
    "Line24_CurrentStatus":      {"question_id": "status_atual"},
    "Line26_SEVISnumber":        {"question_id": "sevis_numero"},

    # Categoria de elegibilidade (item 27) — 3 caixas separadas, ex: (c)(35)
    "section_1": {"question_id": "elig_categoria_classe", "notes": "ex: 'a' ou 'c' — sem tooltip via XFA, confirmado por posição/contexto (item 27)"},
    "section_2": {"question_id": "elig_categoria_numero"},
    "section_3": {"question_id": "elig_categoria_sub", "notes": "ex: 'iii', opcional"},

    # (c)(3)(C) STEM OPT — item 28
    "Line27a_Degree":        {"question_id": "stem_grau"},
    "Line27b_Everify":       {"question_id": "stem_everify_empregador"},
    "Line27c_EverifyIDNumber": {"question_id": "stem_everify_id"},

    # (c)(26) — item 29
    "Line28_ReceiptNumber": {"question_id": "c26_recibo_numero"},

    # (c)(8) — item 30: antecedente criminal
    "PtLine29_YesNo": [cb("c8_preso_condenado", "sim"), cb("c8_preso_condenado", "nao")],

    # (c)(35)/(c)(36) — item 31
    "Line30a_ReceiptNumber": {"question_id": "c35_c36_recibo_numero"},
    "PtLine30b_YesNo": [cb("c35_c36_preso_condenado", "sim"), cb("c35_c36_preso_condenado", "nao")],

    # ── Parte 3 — Declaração do(a) requerente ───────────────────────────────────
    "Pt3Line1Checkbox": [cb("leu_ingles", "leu_interprete"), cb("leu_ingles", "leu_ingles")],
    "Pt3Line1b_Language":          {"question_id": "idioma_interprete"},
    "Part3_Checkbox":              {"question_id": "preparador_ajudou", "check_if_answer": "sim"},
    "Pt3Line2_RepresentativeName": {"question_id": "preparador_nome"},
    "Pt3Line3_DaytimePhoneNumber1": {"question_id": "telefone"},
    "Pt3Line4_MobileNumber1":      {"question_id": "celular"},
    "Pt3Line5_Email":              {"question_id": "email"},
    "Pt3Line7a_Signature":         {"question_id": "_ignore", "notes": "Assinatura física do requerente"},
    "Pt3Line7b_DateofSignature":   {"question_id": "data_assinatura"},
    "Pt4Line6_Checkbox": {"question_id": "abc_settlement", "check_if_answer": "sim",
        "notes": "Salvadorenho/Guatemalteco elegível pelo acordo ABC settlement"},

    # ── Parte 4 — Intérprete (se usado) ─────────────────────────────────────────
    "Pt4Line1a_InterpreterFamilyName": {"question_id": "int_sobrenome"},
    "Pt4Line1b_InterpreterGivenName":  {"question_id": "int_nome"},
    "Pt4Line2_InterpreterBusinessorOrg": {"question_id": "int_organizacao"},
    "Pt5Line3a_StreetNumberName":  {"question_id": "int_end_rua",
        "notes": "Prefixo interno 'Pt5' mas tooltip confirma Parte 4 (intérprete)"},
    "Pt5Line3b_Unit": [cb("int_end_tipo_unidade", "ste"), cb("int_end_tipo_unidade", "flr"), cb("int_end_tipo_unidade", "apt")],
    "Pt5Line3b_AptSteFlrNumber":   {"question_id": "int_end_num_unidade"},
    "Pt5Line3c_CityOrTown":        {"question_id": "int_end_cidade"},
    "Pt5Line3d_State":             {"question_id": "int_end_estado"},
    "Pt5Line3e_ZipCode":           {"question_id": "int_end_cep"},
    "Pt5Line3f_Province":          {"question_id": "int_end_provincia"},
    "Pt5Line3g_PostalCode":        {"question_id": "int_end_codigo_postal"},
    "Pt5Line3h_Country":           {"question_id": "int_end_pais"},
    "Pt4Line4_InterpreterDaytimeTelephone": {"question_id": "int_telefone"},
    "Pt4Line5_MobileNumber":       {"question_id": "int_celular"},
    "Pt4Line6_Email":              {"question_id": "int_email"},
    "Part4_NameofLanguage":        {"question_id": "int_idioma"},
    "Pt4Line6a_Signature":         {"question_id": "_ignore", "notes": "Assinatura física do intérprete"},
    "Pt4Line6b_DateofSignature":   {"question_id": "int_data_assinatura"},

    # ── Parte 5 — Preparador (se diferente do requerente) ───────────────────────
    "Pt5Line1a_PreparerFamilyName": {"question_id": "prep_sobrenome"},
    "Pt5Line1b_PreparerGivenName":  {"question_id": "prep_nome"},
    "Pt5Line2_BusinessName":        {"question_id": "prep_organizacao"},
    "Pt6Line3a_StreetNumberName":   {"question_id": "prep_end_rua",
        "notes": "Prefixo interno 'Pt6' mas tooltip confirma Parte 5 (preparador)"},
    "Pt6Line3b_Unit": [cb("prep_end_tipo_unidade", "ste"), cb("prep_end_tipo_unidade", "flr"), cb("prep_end_tipo_unidade", "apt")],
    "Pt6Line3b_AptSteFlrNumber":    {"question_id": "prep_end_num_unidade"},
    "Pt6Line3c_CityOrTown":         {"question_id": "prep_end_cidade"},
    "Pt6Line3d_State":              {"question_id": "prep_end_estado"},
    "Pt6Line3e_ZipCode":            {"question_id": "prep_end_cep"},
    "Pt6Line3f_Province":           {"question_id": "prep_end_provincia"},
    "Pt6Line3g_PostalCode":         {"question_id": "prep_end_codigo_postal"},
    "Pt6Line3h_Country":            {"question_id": "prep_end_pais"},
    "Pt5Line4_DaytimePhoneNumber1": {"question_id": "prep_telefone"},
    "Pt5Line5_PreparerFaxNumber":   {"question_id": "prep_celular",
        "notes": "tooltip real: 'Preparer's Mobile Telephone Number', apesar do nome interno dizer Fax"},
    "Pt5Line6_Email":               {"question_id": "prep_email"},
    # Declaração do preparador (advogado vs não-advogado) — fora do escopo, mesmo
    # tratamento dado ao equivalente no I-130/I-130A.
    "Part5Line7_Checkbox":  {"question_id": "_ignore"},
    "Part5Line7b_Checkbox": {"question_id": "_ignore"},
    "Pt5Line8a_Signature":          {"question_id": "_ignore", "notes": "Assinatura física do preparador"},
    "Pt5Line8b_DateofSignature":    {"question_id": "prep_data_assinatura"},

    # ── Parte 6 — Informações adicionais (espaço extra) — não preenchido por padrão
    "Pt6Line3a_PageNumber": {"question_id": "_ignore"},
    "Pt6Line3b_PartNumber": {"question_id": "_ignore"},
    "Pt6Line3c_ItemNumber": {"question_id": "_ignore"},
    "Pt6Line4a_PageNumber": {"question_id": "_ignore"},
    "Pt6Line4b_PartNumber": {"question_id": "_ignore"},
    "Pt6Line4c_ItemNumber": {"question_id": "_ignore"},
    "Pt6Line4d_AdditionalInfo": {"question_id": "_ignore"},
    "Pt6Line5a_PageNumber": {"question_id": "_ignore"},
    "Pt6Line5b_PartNumber": {"question_id": "_ignore"},
    "Pt6Line5c_ItemNumber": {"question_id": "_ignore"},
    "Pt6Line5d_AdditionalInfo": {"question_id": "_ignore"},
    "Pt6Line6a_PageNumber": {"question_id": "_ignore"},
    "Pt6Line6b_PartNumber": {"question_id": "_ignore"},
    "Pt6Line6c_ItemNumber": {"question_id": "_ignore"},
    "Pt6Line6d_AdditionalInfo": {"question_id": "_ignore"},
    "Pt6Line7a_PageNumber": {"question_id": "_ignore"},
    "Pt6Line7b_PartNumber": {"question_id": "_ignore"},
    "Pt6Line7c_ItemNumber": {"question_id": "_ignore"},
    "Pt6Line7d_AdditionalInfo": {"question_id": "_ignore"},
}


def apply_rules(skeleton_path: Path, out_path: Path) -> None:
    data = json.loads(skeleton_path.read_text(encoding="utf-8"))
    fields = data["fields"]

    result_fields = []
    unmapped = []
    group_counters: dict[str, int] = {}

    for f in fields:
        pdf_field = f["pdf_field"]
        ftype = f["type"]
        if ftype == "unknown" or "BarCode" in pdf_field:
            continue

        short = pdf_field.split(".")[-1]
        m = re.match(r"^([^\[]+)", short)
        base = m.group(1) if m else short

        rule = MAPPING_RULES.get(base)

        if isinstance(rule, list):
            i = group_counters.get(base, 0)
            group_counters[base] = i + 1
            if i >= len(rule):
                unmapped.append(pdf_field)
                continue
            item = rule[i]
            entry = {"pdf_field": pdf_field, "type": item.get("type", ftype),
                      "question_id": item["question_id"]}
            if "check_if_answer" in item:
                entry["check_if_answer"] = item["check_if_answer"]
            result_fields.append(entry)
            continue

        if rule is None:
            unmapped.append(pdf_field)
            continue

        entry = {"pdf_field": pdf_field, "type": ftype, "question_id": rule["question_id"]}
        if "check_if_answer" in rule:
            entry["check_if_answer"] = rule["check_if_answer"]
        result_fields.append(entry)

    if unmapped:
        print(f"AVISO: {len(unmapped)} campo(s) sem regra de mapeamento:")
        for u in unmapped:
            print(f"  - {u}")
    else:
        print("Todos os campos cobertos.")

    out_data = {"form": "I-765", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/i-765.skeleton.json",
                base_dir / "data/mappings/i-765.json")
