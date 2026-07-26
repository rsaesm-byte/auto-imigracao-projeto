"""
build_mapping_i90.py — Aplica os question_id ao esqueleto de mapeamento do I-90.

Uso:
    python scripts/build_mapping_i90.py
    # Sobrescreve data/mappings/i-90.json com question_id preenchidos.

Peculiaridades confirmadas neste formulário:
    - "P3_Line9_HeightInches1/2/3": mesmo padrão do I-751 — nome errado (diz
      "Height" mas o texto da página confirma que são os 3 dígitos do PESO,
      item 9 "Weight"). Usa "digit_split", não o nome do campo.
    - "P7_Line5_PreparersFaxNumber": ao contrário do I-751 (onde era mesmo fax),
      aqui o toolTip confirma que é "Mobile Telephone Number" — cada formulário
      precisa ser conferido de novo, não dá pra generalizar de um pro outro.
    - "P2_checkbox2" (motivo da aplicação, Seção A, residente permanente) e
      "P2_checkbox3" (motivo, Seção B, residente condicional) têm índice que
      NÃO é sequencial — ordem real confirmada via /AP: checkbox2 vai
      2e,2f,2g1,2g2,2d,2a,2b,2c,2j,2h2,2i,2h1 (índices 0-11) e checkbox3 vai
      3b,3c,3d,3e,3a (índices 0-4).
    - "P5_Checkbox1a"/"P5_Checkbox1b" (leu inglês / usou intérprete) são DOIS
      CAMPOS SEPARADOS (nomes diferentes), não uma lista por índice de um nome
      só — cada um com seu próprio real_on "Y". Mapeados para o mesmo
      question_id com check_if_answer diferente, sem precisar de lista.
    - "P6_Line4_InterpretersDaytimePhoneNumber" aparece 2x (telefone fixo item
      4, celular item 5) — mesmo campo de texto reaproveitado, sem /AP para
      desambiguar; seguindo o padrão já confirmado por posição em outros
      formulários (I-130A, I-765, I-864), índice 0 = fixo, índice 1 = celular.
"""

import json
import re
from pathlib import Path


def cb(question_id: str, check_if_answer: str) -> dict:
    return {"type": "checkbox", "question_id": question_id, "check_if_answer": check_if_answer}


def txt(question_id: str) -> dict:
    return {"type": "text", "question_id": question_id}


def digit(question_id: str, position: int) -> dict:
    return {"type": "text", "question_id": question_id, "digit_split": position}


MAPPING_RULES: dict[str, object] = {

    # ── Parte 1 — Informações sobre você ─────────────────────────────────────
    "P1_Line1_AlienNumber": txt("alien_number"),
    "P1_Line2_AcctIdentifier": txt("uscis_online"),
    "P1_Line3a_FamilyName": txt("nome_sobrenome"),
    "P1_Line3b_GivenName":  txt("nome_nome"),
    "P1_Line3c_MiddleName": txt("nome_meio"),
    "P1_checkbox4": [cb("nome_mudou", "sim"), cb("nome_mudou", "nao"), cb("nome_mudou", "nao_aplicavel")],
    "P1_Line5a_FamilyName": txt("nome_cartao_anterior_sobrenome"),
    "P1_Line5b_GivenName":  txt("nome_cartao_anterior_nome"),
    "P1_Line5c_MiddleName": txt("nome_cartao_anterior_meio"),

    "P1_Line6a_InCareofName":     txt("end_correio_cuidados_de"),
    "P1_Line6b_StreetNumberName": txt("end_correio_rua"),
    "P1_checkbox6c_Unit": [cb("end_correio_tipo_unidade", "apt"), cb("end_correio_tipo_unidade", "ste"), cb("end_correio_tipo_unidade", "flr")],
    "P1_Line6c_AptSteFlrNumber":  txt("end_correio_num_unidade"),
    "P1_Line6d_CityOrTown":       txt("end_correio_cidade"),
    "P1_Line6e_State":            txt("end_correio_estado"),
    "P1_Line6f_ZipCode":          txt("end_correio_cep"),
    "P1_Line6g_Province":         txt("end_correio_provincia"),
    "P1_Line6h_PostalCode":       txt("end_correio_codigo_postal"),
    "P1_Line6i_Country":          txt("end_correio_pais"),

    "P1_Line7a_StreetNumberName": txt("end_fisico_rua"),
    "P1_checkbox7b_Unit": [cb("end_fisico_tipo_unidade", "apt"), cb("end_fisico_tipo_unidade", "ste"), cb("end_fisico_tipo_unidade", "flr")],
    "P1_Line7b_AptSteFlrNumber":  txt("end_fisico_num_unidade"),
    "P1_Line7c_CityOrTown":       txt("end_fisico_cidade"),
    "P1_Line7d_State":            txt("end_fisico_estado"),
    "P1_Line7e_ZipCode":          txt("end_fisico_cep"),
    "P1_Line7f_Province":         txt("end_fisico_provincia"),
    "P1_Line7g_PostalCode":       txt("end_fisico_codigo_postal"),
    "P1_Line7h_Country":          txt("end_fisico_pais"),

    "P1_Line8_male":   cb("sexo", "masculino"),
    "P1_Line8_female": cb("sexo", "feminino"),
    "P1_Line9_DateOfBirth":      txt("data_nascimento"),
    "P1_Line10_CityTownOfBirth": txt("cidade_nascimento"),
    "P1_Line11_CountryofBirth":  txt("pais_nascimento"),
    "P1_Line12_MotherGivenName": txt("mae_nome"),
    "P1_Line13_FatherGivenName": txt("pai_nome"),
    "P1_Line14_ClassOfAdmission": txt("classe_admissao"),
    "P1_Line15_DateOfAdmission":  txt("data_admissao"),
    "P1_Line16_SSN": txt("ssn"),

    # ── Parte 2 — Tipo de aplicação ──────────────────────────────────────────
    "P2_checkbox1": [cb("meu_status", "residente_permanente"), cb("meu_status", "residente_comutante"), cb("meu_status", "residente_condicional")],
    # Seção A (residente permanente/comutante) — ordem real via /AP, não sequencial
    "P2_checkbox2": [
        cb("motivo_secao_a", "biografia_mudou"), cb("motivo_secao_a", "cartao_expirado"),
        cb("motivo_secao_a", "14anos_expira_apos_16"), cb("motivo_secao_a", "14anos_expira_antes_16"),
        cb("motivo_secao_a", "erro_dhs"), cb("motivo_secao_a", "perdido_roubado_destruido"),
        cb("motivo_secao_a", "emitido_nao_recebido"), cb("motivo_secao_a", "mutilado"),
        cb("motivo_secao_a", "outro_edicao_anterior"), cb("motivo_secao_a", "comutante_tomando_residencia"),
        cb("motivo_secao_a", "convertido_automaticamente"), cb("motivo_secao_a", "residente_tomando_status_comutante"),
    ],
    "P2_Line2h1_CityandState": txt("motivo_comutante_local_poe"),
    # Seção B (residente condicional) — ordem real via /AP, não sequencial
    "P2_checkbox3": [
        cb("motivo_secao_b", "emitido_nao_recebido"), cb("motivo_secao_b", "mutilado"),
        cb("motivo_secao_b", "erro_dhs"), cb("motivo_secao_b", "biografia_mudou"),
        cb("motivo_secao_b", "perdido_roubado_destruido"),
    ],

    # ── Parte 3 — Informações de processamento ──────────────────────────────
    "P3_Line1_LocationAppliedVisa": txt("local_aplicou_visto"),
    "P3_Line2_LocationIssuedVisa":  txt("local_emitido_visto"),
    "P3_checkbox4": [cb("ja_esteve_processo_remocao", "nao"), cb("ja_esteve_processo_remocao", "sim")],
    "P3_checkbox5": [cb("abandonou_status", "nao"), cb("abandonou_status", "sim")],
    "P3_Line3a1_CityandState": txt("porto_entrada"),
    "P3_Line3a_Destination":   txt("destino_eua_admissao"),

    # Informações biográficas
    "P3_Line8_HeightFeet":   txt("altura_pes"),
    "P3_Line8_HeightInches": txt("altura_polegadas"),
    "P3_Line9_HeightInches1": digit("peso", 1),
    "P3_Line9_HeightInches2": digit("peso", 2),
    "P3_Line9_HeightInches3": digit("peso", 3),
    "P3_checkbox6": [cb("etnia", "nao_hispanico"), cb("etnia", "hispanico")],
    "P3_checkbox7_Hawaiian": cb("raca_havaiano_pacifico", "sim"),
    "P3_checkbox7_Indian":   cb("raca_indigena_americano", "sim"),
    "P3_checkbox7_White":    cb("raca_branco", "sim"),
    "P3_checkbox7_Asian":    cb("raca_asiatico", "sim"),
    "P3_checkbox7_Black":    cb("raca_negro", "sim"),
    "P3_checkbox10": [
        cb("cor_olhos", "azul"), cb("cor_olhos", "verde"), cb("cor_olhos", "avela"),
        cb("cor_olhos", "rosa"), cb("cor_olhos", "marrom_avermelhado"), cb("cor_olhos", "castanho"),
        cb("cor_olhos", "preto"), cb("cor_olhos", "outro"), cb("cor_olhos", "cinza"),
    ],
    "P3_checkbox11": [
        cb("cor_cabelo", "careca"), cb("cor_cabelo", "loiro"), cb("cor_cabelo", "grisalho"),
        cb("cor_cabelo", "arenoso"), cb("cor_cabelo", "outro"), cb("cor_cabelo", "branco"),
        cb("cor_cabelo", "ruivo"), cb("cor_cabelo", "castanho"), cb("cor_cabelo", "preto"),
    ],

    # ── Parte 4 — Acomodações para pessoas com deficiência ──────────────────
    "P4_checkbox1": [cb("acomodacao_solicitada", "nao"), cb("acomodacao_solicitada", "sim")],
    "P4_checkbox1a": cb("acomodacao_surdo", "sim"),
    "P4_Line1a_AccomodationRequested": txt("acomodacao_surdo_detalhe"),
    "P4_checkbox1b": cb("acomodacao_cego", "sim"),
    "P4_Line1b_AccomodationRequested": txt("acomodacao_cego_detalhe"),
    "P4_checkbox1c": cb("acomodacao_outra", "sim"),
    "P4_Line1c_AccomodationRequested": txt("acomodacao_outra_detalhe"),

    # ── Parte 5 — Declaração do(a) requerente ────────────────────────────────
    "P5_Checkbox1a": cb("leu_ingles", "leu_ingles"),
    "P5_Checkbox1b": cb("leu_ingles", "leu_interprete"),
    "P5_Line1b_Language": txt("idioma_interprete"),
    "P5_Checkbox2": cb("preparador_ajudou", "sim"),
    "P5_Line2_NameofRepresentative": txt("preparador_nome"),
    "P5_Line3_DaytimePhoneNumber": txt("telefone"),
    "P5_Line4_MobilePhoneNumber":  txt("celular"),
    "P5_Line5_EmailAddress": txt("email"),
    "P5_Line6a_SignatureofApplicant": {"question_id": "_ignore", "notes": "Assinatura física do requerente"},
    "P5_Line6b_DateofSignature": txt("data_assinatura"),

    # ── Parte 6 — Intérprete (se usado) ─────────────────────────────────────
    "P6_Line1a_InterpretersFamilyName": txt("int_sobrenome"),
    "P6_Line1b_InterpretersGivenName":  txt("int_nome"),
    "P6_Line2_NameofBusinessor": txt("int_organizacao"),
    "P6_Line3a_StreetNumberName": txt("int_end_rua"),
    "P6_checkbox3b_Unit": [cb("int_end_tipo_unidade", "apt"), cb("int_end_tipo_unidade", "ste"), cb("int_end_tipo_unidade", "flr")],
    "P6_Line3b_AptSteFlrNumber": txt("int_end_num_unidade"),
    "P6_Line3c_CityTown": txt("int_end_cidade"),
    "P6_Line3d_State": txt("int_end_estado"),
    "P6_Line3e_ZipCode": txt("int_end_cep"),
    "P6_Line3f_Province": txt("int_end_provincia"),
    "P6_Line3g_PostalCode": txt("int_end_codigo_postal"),
    "P6_Line3h_Country": txt("int_end_pais"),
    "P6_Line4_InterpretersDaytimePhoneNumber": [txt("int_telefone"), txt("int_celular")],
    "P6_Line5_InterpretersEmailAddress": txt("int_email"),
    "P6_Language": txt("int_idioma"),
    "P6_Line6a_Signature": {"question_id": "_ignore", "notes": "Assinatura física do intérprete"},
    "P6_Line6b_DateofSignature": txt("int_data_assinatura"),

    # ── Parte 7 — Preparador (se diferente do requerente) ───────────────────
    "P7_Line1a_FamilyName": txt("prep_sobrenome"),
    "P7_Line1b_PreparersGivenName": txt("prep_nome"),
    "P7_Line2_NameofBusinessor": txt("prep_organizacao"),
    "P7_Line3a_StreetNumberName": txt("prep_end_rua"),
    "P7_checkbox3b_Unit": [cb("prep_end_tipo_unidade", "apt"), cb("prep_end_tipo_unidade", "ste"), cb("prep_end_tipo_unidade", "flr")],
    "P7_Line3b_AptSteFlrNumber": txt("prep_end_num_unidade"),
    "P7_Line3c_CityTown": txt("prep_end_cidade"),
    "P7_Line3d_State": txt("prep_end_estado"),
    "P7_Line3e_ZipCode": txt("prep_end_cep"),
    "P7_Line3f_Province": txt("prep_end_provincia"),
    "P7_Line3g_PostalCode": txt("prep_end_codigo_postal"),
    "P7_Line3h_Country": txt("prep_end_pais"),
    "P7_Line4_PreparersDaytimePhoneNumber": txt("prep_telefone"),
    # Nome interno diz "Fax" mas o toolTip confirma "Mobile Telephone Number"
    "P7_Line5_PreparersFaxNumber": txt("prep_celular"),
    "P7_Line6_PreparersEmailAddress": txt("prep_email"),
    "P7_checkbox7": {"question_id": "_ignore", "notes": "Declaração advogado vs não-advogado, fora do escopo"},
    "P7_checkbox7Extend": {"question_id": "_ignore"},
    "P7_Line8a_SignatureofPreparer": {"question_id": "_ignore", "notes": "Assinatura física do preparador"},
    "P7_Line8b_DateofSignature": txt("prep_data_assinatura"),

    # ── Parte 8 — Informações adicionais (espaço extra) — não preenchido por padrão
    "P8_Line3a_PageNumber": {"question_id": "_ignore"},
    "P8_Line3b_PartNumber": {"question_id": "_ignore"},
    "P8_Line3c_ItemNumber": {"question_id": "_ignore"},
    "P8_Line3d_AdditionalInfo": {"question_id": "_ignore"},
    "P8_Line4a_PageNumber": {"question_id": "_ignore"},
    "P8_Line4b_PartNumber": {"question_id": "_ignore"},
    "P8_Line4c_ItemNumber": {"question_id": "_ignore"},
    "P8_Line4d_AdditionalInfo": {"question_id": "_ignore"},
    "P8_Line5a_PageNumber": {"question_id": "_ignore"},
    "P8_Line5b_PartNumber": {"question_id": "_ignore"},
    "P8_Line5c_ItemNumber": {"question_id": "_ignore"},
    "P8_Line5d_AdditionalInfo": {"question_id": "_ignore"},
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
            if "digit_split" in item:
                entry["digit_split"] = item["digit_split"]
            result_fields.append(entry)
            continue

        if rule is None:
            unmapped.append(pdf_field)
            continue

        entry = {"pdf_field": pdf_field, "type": ftype, "question_id": rule["question_id"]}
        if "check_if_answer" in rule:
            entry["check_if_answer"] = rule["check_if_answer"]
        if "digit_split" in rule:
            entry["digit_split"] = rule["digit_split"]
        result_fields.append(entry)

    if unmapped:
        print(f"AVISO: {len(unmapped)} campo(s) sem regra de mapeamento:")
        for u in unmapped:
            print(f"  - {u}")
    else:
        print("Todos os campos cobertos.")

    out_data = {"form": "I-90", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/i-90.skeleton.json",
                base_dir / "data/mappings/i-90.json")
