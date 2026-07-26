"""
build_mapping_i130a.py — Aplica os question_id ao esqueleto de mapeamento do I-130A.

Uso:
    python scripts/build_mapping_i130a.py
    # Sobrescreve data/mappings/i-130a.json com question_id preenchidos.

Nota importante sobre nomes de campo enganosos:
    Vários nomes internos de campo do I-130A NÃO batem com o número de item real
    do formulário (ex.: o campo "Pt1Line14_CountryofBirth" na verdade corresponde
    ao item "15. City/Town/Village of Residence" — o nome interno ficou "preso"
    num número de linha antigo do desenho do formulário). As regras abaixo foram
    escritas usando o toolTip real de cada campo (extraído do pacote XFA
    "template"), não o nome do campo. Não "corrija" isso achando que é erro de
    digitação — confira o toolTip antes de mudar qualquer coisa aqui.

Nota sobre regras em lista (grupos por índice):
    Quando o mesmo nome-base de campo aparece mais de uma vez no PDF (radio-style
    checkbox OU até campo de texto reaproveitado para dois dados diferentes, como
    "Pt5Line4_InterpreterDaytimeTelephone" = telefone fixo E celular do intérprete),
    a regra é uma LISTA de dicts, um por ocorrência, NA ORDEM em que o campo
    aparece no PDF (índice [0], [1], [2]...). Para checkbox, essa ordem foi
    confirmada lendo o valor real do /AP de cada widget (nunca por posição visual
    — ver xfa-hybrid-forms.md). Para o par de telefone do intérprete (texto, sem
    /AP), a ordem foi confirmada pela posição vertical (/Rect) dos widgets no PDF.
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
    "PDF417BarCode1":         {"question_id": "_ignore", "notes": "Código de barras automático"},
    "CheckBox1":              {"question_id": "_ignore", "notes": "Checkbox G-28 anexado (advogado)"},
    "VolagNumber":            {"question_id": "_ignore", "notes": "Número VOLAG interno"},
    "AttorneyStateBarNumber": {"question_id": "_ignore", "notes": "OAB/Bar do advogado"},
    "USCISOnlineAcctNumber":  {"question_id": "_ignore", "notes": "Conta USCIS Online do advogado"},

    # ── Parte 1 — Informações sobre você (cônjuge beneficiário) ────────────────
    "Pt1Line1_AlienNumber":          {"question_id": "sb_alien_number"},
    "Pt2Line3_USCISELISActNumber":   {"question_id": "sb_uscis_online",
        "notes": "Nome interno enganoso: tooltip diz 'Part 1... 2. USCIS Online Account Number'"},
    "Pt1Line3a_FamilyName":          {"question_id": "sb_sobrenome"},
    "Pt1Line3b_GivenName":           {"question_id": "sb_nome"},
    "Pt1Line3c_MiddleName":          {"question_id": "sb_nome_meio"},

    # Endereço atual (Physical Address 1 — item 4) + datas (item 5)
    "Pt1Line4a_StreetNumberName":    {"question_id": "sb_end_rua"},
    "Pt1Line4b_Unit": [cb("sb_end_tipo_unidade", "apt"), cb("sb_end_tipo_unidade", "ste"), cb("sb_end_tipo_unidade", "flr")],
    "Pt1Line4b_AptSteFlrNumber":     {"question_id": "sb_end_num_unidade"},
    "Pt1Line4c_CityOrTown":          {"question_id": "sb_end_cidade"},
    "Pt1Line4d_State":               {"question_id": "sb_end_estado"},
    "Pt1Line4e_ZipCode":             {"question_id": "sb_end_cep"},
    "Pt1Line4f_Province":            {"question_id": "sb_end_provincia"},
    "Pt1Line4g_PostalCode":          {"question_id": "sb_end_codigo_postal"},
    "Pt1Line4h_Country":             {"question_id": "sb_end_pais"},
    "Pt1Line5a_DateFrom":            {"question_id": "sb_end_desde"},
    "Pt1Line5b_DateTo":              {"question_id": "sb_end_ate"},

    # Endereço anterior (Physical Address 2 — item 6) + datas (item 7)
    "Pt1Line6a_StreetNumberName":    {"question_id": "sb_end_ant1_rua"},
    "Pt1Line6b_Unit": [cb("sb_end_ant1_tipo_unidade", "apt"), cb("sb_end_ant1_tipo_unidade", "ste"), cb("sb_end_ant1_tipo_unidade", "flr")],
    "Pt1Line6b_AptSteFlrNumber":     {"question_id": "sb_end_ant1_num_unidade"},
    "Pt1Line6c_CityOrTown":          {"question_id": "sb_end_ant1_cidade"},
    "Pt1Line6d_State":               {"question_id": "sb_end_ant1_estado"},
    "Pt1Line6e_ZipCode":             {"question_id": "sb_end_ant1_cep"},
    "Pt1Line6f_Province":            {"question_id": "sb_end_ant1_provincia"},
    "Pt1Line6g_PostalCode":          {"question_id": "sb_end_ant1_codigo_postal"},
    "Pt1Line6h_Country":             {"question_id": "sb_end_ant1_pais"},
    "Pt1Line7a_DateFrom":            {"question_id": "sb_end_ant1_desde"},
    "Pt1Line7b_DateTo":              {"question_id": "sb_end_ant1_ate"},

    # Último endereço fora dos EUA (item 8) + datas (item 9)
    "Pt1Line8a_StreetNumberName":    {"question_id": "sb_end_ext_rua"},
    "Pt1Line8b_Unit": [cb("sb_end_ext_tipo_unidade", "apt"), cb("sb_end_ext_tipo_unidade", "ste"), cb("sb_end_ext_tipo_unidade", "flr")],
    "Pt1Line8b_AptSteFlrNumber":     {"question_id": "sb_end_ext_num_unidade"},
    "Pt1Line8c_CityOrTown":          {"question_id": "sb_end_ext_cidade"},
    "Pt1Line8d_Province":            {"question_id": "sb_end_ext_provincia"},
    "Pt1Line8e_PostalCode":          {"question_id": "sb_end_ext_codigo_postal"},
    "Pt1Line8f_Country":             {"question_id": "sb_end_ext_pais"},
    "Pt1Line9a_DateFrom":            {"question_id": "sb_end_ext_desde"},
    "Pt1Line9b_DateTo":              {"question_id": "sb_end_ext_ate"},

    # Informações sobre o Pai/Mãe 1 (itens 10-16)
    "Pt1Line10_FamilyName":          {"question_id": "pai1_sobrenome"},
    "Pt1Line10_GivenName":           {"question_id": "pai1_nome"},
    "Pt1Line10_MiddleName":          {"question_id": "pai1_nome_meio"},
    "Pt1Line11_DateofBirth":         {"question_id": "pai1_data_nascimento"},
    "Pt1Line12_Male":   {"question_id": "pai1_sexo", "check_if_answer": "masculino"},
    "Pt1Line12_Female": {"question_id": "pai1_sexo", "check_if_answer": "feminino"},
    "Pt1Line12CityTownOfBirth":      {"question_id": "pai1_cidade_nascimento",
        "notes": "Nome interno enganoso: tooltip diz item 13 (City/Town/Village of Birth)"},
    "Pt1Line13_CountryofBirth":      {"question_id": "pai1_pais_nascimento",
        "notes": "tooltip: item 14 (Country of Birth)"},
    "Pt1Line14_CountryofBirth":      {"question_id": "pai1_cidade_residencia",
        "notes": "Nome interno ENGANOSO: tooltip diz item 15 City/Town/Village of RESIDENCE, não Country of Birth"},
    "Pt1Line15_CountryofResidence":  {"question_id": "pai1_pais_residencia"},

    # Informações sobre o Pai/Mãe 2 (itens 17-23)
    "Pt1Line16_FamilyName":          {"question_id": "pai2_sobrenome"},
    "Pt1Line16_GivenName":           {"question_id": "pai2_nome"},
    "Pt1Line16_MiddleName":          {"question_id": "pai2_nome_meio"},
    "Pt1Line17_DateofBirth":         {"question_id": "pai2_data_nascimento"},
    "Pt1Line19_Male":   {"question_id": "pai2_sexo", "check_if_answer": "masculino"},
    "Pt1Line19_Female": {"question_id": "pai2_sexo", "check_if_answer": "feminino"},
    "Pt1Line18_CityTownOfBirth":     {"question_id": "pai2_cidade_nascimento"},
    "Pt1Line19_CountryofBirth":      {"question_id": "pai2_pais_nascimento"},
    "Pt1Line20_CityTownVillageofRes":{"question_id": "pai2_cidade_residencia"},
    "Pt1Line21_CountryofResidence":  {"question_id": "pai2_pais_residencia"},

    # ── Parte 2 — Informações sobre seu emprego (últimos 5 anos) ───────────────
    # Empregador 1 (atual)
    "Pt2Line1_EmployerOrCompName":   {"question_id": "emp1_nome"},
    "Pt2Line2a_StreetNumberName":    {"question_id": "emp1_end_rua"},
    "Pt2Line2b_Unit": [cb("emp1_end_tipo_unidade", "apt"), cb("emp1_end_tipo_unidade", "ste"), cb("emp1_end_tipo_unidade", "flr")],
    "Pt2Line2b_AptSteFlrNumber":     {"question_id": "emp1_end_num_unidade"},
    "Pt2Line2c_CityOrTown":          {"question_id": "emp1_end_cidade"},
    "Pt2Line2d_State":               {"question_id": "emp1_end_estado"},
    "Pt2Line2e_ZipCode":             {"question_id": "emp1_end_cep"},
    "Pt2Line2f_Province":            {"question_id": "emp1_end_provincia"},
    "Pt2Line2g_PostalCode":          {"question_id": "emp1_end_codigo_postal"},
    "Pt2Line2h_Country":             {"question_id": "emp1_end_pais"},
    "Pt2Line3_Occupation":           {"question_id": "emp1_ocupacao"},
    "Pt2Line4a_DateFrom":            {"question_id": "emp1_desde"},
    "Pt2Line4b_DateTo":              {"question_id": "emp1_ate"},

    # Empregador 2 (anterior)
    "Pt2Line5_EmployerOrCompName":   {"question_id": "emp2_nome"},
    "Pt2Line6_StreetNumberName":     {"question_id": "emp2_end_rua"},
    "Pt2Line6_Unit": [cb("emp2_end_tipo_unidade", "apt"), cb("emp2_end_tipo_unidade", "ste"), cb("emp2_end_tipo_unidade", "flr")],
    "Pt2Line6_AptSteFlrNumber":      {"question_id": "emp2_end_num_unidade"},
    "Pt2Line6_CityOrTown":           {"question_id": "emp2_end_cidade"},
    "Pt2Line6_State":                {"question_id": "emp2_end_estado"},
    "Pt2Line6_ZipCode":              {"question_id": "emp2_end_cep"},
    "Pt2Line6_Province":             {"question_id": "emp2_end_provincia"},
    "Pt2Line6_PostalCode":           {"question_id": "emp2_end_codigo_postal"},
    "Pt2Line6_Country":              {"question_id": "emp2_end_pais"},
    "Pt2Line7_Occupation":           {"question_id": "emp2_ocupacao"},
    "Pt2Line8a_DateFrom":            {"question_id": "emp2_desde"},
    "Pt2Line8b_DateTo":              {"question_id": "emp2_ate"},

    # ── Parte 3 — Emprego fora dos EUA (se não informado acima) ────────────────
    "Pt3Line1_EmployerOrCompName":   {"question_id": "emp3_nome"},
    "Pt3Line2a_StreetNumberName":    {"question_id": "emp3_end_rua"},
    "Pt3Line2b_Unit": [cb("emp3_end_tipo_unidade", "apt"), cb("emp3_end_tipo_unidade", "ste"), cb("emp3_end_tipo_unidade", "flr")],
    "Pt3Line2b_AptSteFlrNumber":     {"question_id": "emp3_end_num_unidade"},
    "Pt3Line2c_CityOrTown":          {"question_id": "emp3_end_cidade"},
    "Pt3Line2d_State":               {"question_id": "emp3_end_estado"},
    "Pt3Line2e_ZipCode":             {"question_id": "emp3_end_cep"},
    "Pt3Line2f_Province":            {"question_id": "emp3_end_provincia"},
    "Pt3Line2g_PostalCode":          {"question_id": "emp3_end_codigo_postal"},
    "Pt3Line2h_Country":             {"question_id": "emp3_end_pais"},
    "Pt3Line3_Occupation":           {"question_id": "emp3_ocupacao"},
    "Pt3Line4a_DateFrom":            {"question_id": "emp3_desde"},
    "Pt3Line4b_DateTo":              {"question_id": "emp3_ate"},

    # ── Parte 4 — Declaração, contato e assinatura do cônjuge beneficiário ─────
    # Índice [0] do widget = on-value real "B" (leu via intérprete);
    # índice [1] = on-value real "A" (leu inglês). Confirmado via /AP, não posição.
    "Pt4Line1Checkbox": [cb("ass_leu_ingles", "leu_interprete"), cb("ass_leu_ingles", "leu_ingles")],
    "Pt4Line1b_Language":            {"question_id": "ass_idioma"},
    "Pt4_Checkbox":                  {"question_id": "ass_preparador_ajudou", "check_if_answer": "sim"},
    "Pt4Line2_RepresentativeName":   {"question_id": "ass_preparador_nome"},
    "Pt4Line3_DaytimePhoneNumber1":  {"question_id": "sb_telefone"},
    "Pt4Line4_MobileNumber1":        {"question_id": "sb_celular"},
    "Pt4Line5_Email":                {"question_id": "sb_email"},
    "Pt4Line6a_Signature":           {"question_id": "_ignore", "notes": "Assinatura física do beneficiário"},
    "Pt4Line6b_DateofSignature":     {"question_id": "ass_data_assinatura"},

    # ── Parte 5 — Intérprete (se usado) ─────────────────────────────────────────
    "Pt5Line1a_InterpreterFamilyName": {"question_id": "int_sobrenome"},
    "Pt5Line1b_InterpreterGivenName":  {"question_id": "int_nome"},
    "Pt5Line2_InterpreterBusinessorOrg": {"question_id": "int_organizacao"},
    "Pt5Line3a_StreetNumberName":    {"question_id": "int_end_rua"},
    "Pt5Line3b_Unit": [cb("int_end_tipo_unidade", "apt"), cb("int_end_tipo_unidade", "ste"), cb("int_end_tipo_unidade", "flr")],
    "Pt5Line3b_AptSteFlrNumber":     {"question_id": "int_end_num_unidade"},
    "Pt5Line3c_CityOrTown":          {"question_id": "int_end_cidade"},
    "Pt5Line3d_State":               {"question_id": "int_end_estado"},
    "Pt5Line3e_ZipCode":             {"question_id": "int_end_cep"},
    "Pt5Line3f_Province":            {"question_id": "int_end_provincia"},
    "Pt5Line3g_PostalCode":          {"question_id": "int_end_codigo_postal"},
    "Pt5Line3h_Country":             {"question_id": "int_end_pais"},
    # Nome do campo reaproveitado no PDF para dois dados diferentes (sem /AP para
    # desambiguar, por ser texto) — ordem confirmada pela posição vertical (/Rect):
    # índice [0] fica acima (item 4, telefone fixo), [1] fica abaixo (item 5, celular).
    "Pt5Line4_InterpreterDaytimeTelephone": [txt("int_telefone"), txt("int_celular")],
    "Pt5Line5_Email":                {"question_id": "int_email"},
    "Pt5_NameofLanguage":            {"question_id": "int_idioma"},
    "Pt5Line6a_Signature":           {"question_id": "_ignore", "notes": "Assinatura física do intérprete"},
    "Pt5Line6b_DateofSignature":     {"question_id": "int_data_assinatura"},

    # ── Parte 6 — Preparador (se diferente do beneficiário) ────────────────────
    "Pt6Line1a_PreparerFamilyName":  {"question_id": "prep_sobrenome"},
    "Pt6Line1b_PreparerGivenName":   {"question_id": "prep_nome"},
    "Pt6Line2_BusinessName":         {"question_id": "prep_organizacao"},
    "Pt6Line3a_StreetNumberName":    {"question_id": "prep_end_rua"},
    "Pt6Line3b_Unit": [cb("prep_end_tipo_unidade", "apt"), cb("prep_end_tipo_unidade", "ste"), cb("prep_end_tipo_unidade", "flr")],
    "Pt6Line3b_AptSteFlrNumber":     {"question_id": "prep_end_num_unidade"},
    "Pt6Line3c_CityOrTown":          {"question_id": "prep_end_cidade"},
    "Pt6Line3d_State":               {"question_id": "prep_end_estado"},
    "Pt6Line3e_ZipCode":             {"question_id": "prep_end_cep"},
    "Pt6Line3f_Province":            {"question_id": "prep_end_provincia"},
    "Pt6Line3g_PostalCode":          {"question_id": "prep_end_codigo_postal"},
    "Pt6Line3h_Country":             {"question_id": "prep_end_pais"},
    "Pt6Line4_DaytimePhoneNumber":   {"question_id": "prep_telefone"},
    "Pt6Line5_PreparerFaxNumber":    {"question_id": "prep_celular",
        "notes": "tooltip real: 'Enter Preparer's Mobile Telephone Number', apesar do nome interno dizer Fax"},
    "Pt6Line6_Email":                {"question_id": "prep_email"},
    # Declaração do preparador (advogado vs não-advogado) — fora do escopo do
    # questionário do cliente, mesmo tratamento dado ao equivalente no I-130.
    "Pt6Line7_Checkbox":  {"question_id": "_ignore"},
    "Pt6Line7b_Checkbox": {"question_id": "_ignore"},
    "Pt6Line8a_Signature":           {"question_id": "_ignore", "notes": "Assinatura física do preparador"},
    "Pt6Line8b_DateofSignature":     {"question_id": "prep_data_assinatura"},

    # ── Parte 7 — Informações adicionais (espaço extra) — não preenchido por padrão
    "Pt7Line3a_PageNumber": {"question_id": "_ignore"},
    "Pt7Line3b_PartNumber": {"question_id": "_ignore"},
    "Pt7Line3c_ItemNumber": {"question_id": "_ignore"},
    "Pt7Line3d_AdditionalInfo": {"question_id": "_ignore"},
    "Pt7Line4a_PageNumber": {"question_id": "_ignore"},
    "Pt7Line4b_PartNumber": {"question_id": "_ignore"},
    "Pt7Line4c_ItemNumber": {"question_id": "_ignore"},
    "Pt7Line4d_AdditionalInfo": {"question_id": "_ignore"},
    "Pt7Line5a_PageNumber": {"question_id": "_ignore"},
    "Pt7Line5b_PartNumber": {"question_id": "_ignore"},
    "Pt7Line5c_ItemNumber": {"question_id": "_ignore"},
    "Pt7Line5d_AdditionalInfo": {"question_id": "_ignore"},
    "Pt7Line6a_PageNumber": {"question_id": "_ignore"},
    "Pt7Line6b_PartNumber": {"question_id": "_ignore"},
    "Pt7Line6c_ItemNumber": {"question_id": "_ignore"},
    "Pt7Line6d_AdditionalInfo": {"question_id": "_ignore"},
    "Pt7Line7a_PageNumber": {"question_id": "_ignore"},
    "Pt7Line7b_PartNumber": {"question_id": "_ignore"},
    "Pt7Line7c_ItemNumber": {"question_id": "_ignore"},
    "Pt7Line7d_AdditionalInfo": {"question_id": "_ignore"},
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
            continue  # containers e código de barras — não são campos reais

        short = pdf_field.split(".")[-1]
        m = re.match(r"^([^\[]+)", short)
        base = m.group(1) if m else short

        rule = MAPPING_RULES.get(base)

        if isinstance(rule, list):
            # Uma linha por ocorrência, na ordem em que o campo aparece no PDF.
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

    out_data = {"form": "I-130A", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/i-130a.skeleton.json",
                base_dir / "data/mappings/i-130a.json")
