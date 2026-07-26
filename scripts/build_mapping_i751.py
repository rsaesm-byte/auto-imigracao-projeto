"""
build_mapping_i751.py — Aplica os question_id ao esqueleto de mapeamento do I-751.

Uso:
    python scripts/build_mapping_i751.py
    # Sobrescreve data/mappings/i-751.json com question_id preenchidos.

Nomes de campo enganosos confirmados neste formulário:
    - "P3_Line9_HeightInches1/2/3": tooltip não existe, mas o texto da página
      confirma que são os 3 dígitos do PESO (item 4, "Weight"), não altura —
      nome herdado de outro desenho de formulário. Usam a chave "digit_split"
      no mapeamento (ver fill_form.py: _weight_digit_by_position), não o nome
      do campo — o nome aqui é "HeightInches1/2/3", bem diferente do padrão
      "Pound1/2/3" usado no I-130 para o mesmo tipo de campo.
    - "P7_Line5_PreparersFaxNumber": ao contrário de outros formulários (I-130A,
      I-765, I-864) onde um campo "Fax" na real é celular, aqui o toolTip
      CONFIRMA que é mesmo "Fax Number" — não generalize a suposição de um
      formulário para o outro sem checar o toolTip de novo.
    - Vários campos da Parte 8 (declaração do cônjuge) têm prefixo interno
      "P5_"/"P7_" (números de Parte de outro desenho); o toolTip sempre tem 2
      candidatos (Parte 7 petitioner / Parte 8 cônjuge) e a real correspondência
      foi resolvida pela ADJACÊNCIA com campos vizinhos inequívocos (ex.: o
      campo de data de assinatura ao lado da assinatura do peticionário vs. ao
      lado da assinatura do cônjuge) — não pela ordem dos candidatos no toolTip.

Grupos onde o índice NÃO é a ordem lógica (confirmado via /AP, não posição):
    "Part4_Relationship": índice 0 = código B (padrasto), índice 1 = código A
    (cônjuge) — invertido em relação à leitura natural do formulário.
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

    # Campos administrativos / advogado — fora do escopo do questionário do cliente
    "G28":                   {"question_id": "_ignore", "notes": "Checkbox G-28 anexado (advogado)"},
    "AttorneyStateBarNumber":{"question_id": "_ignore", "notes": "OAB/Bar do advogado"},
    "USCISELISAcctNumber":   {"question_id": "_ignore", "notes": "Conta USCIS ELIS do advogado"},

    # ── Parte 1 — Informações sobre você (residente condicional) ───────────────
    "Pt1Line1a_FamilyName": txt("nome_sobrenome"),
    "Pt1Line1b_GivenName":  txt("nome_nome"),
    "Pt1Line1c_MiddleName": txt("nome_meio"),
    "P1_Line2a_FamilyName": txt("outro_nome2_sobrenome"),
    "P1_Line2b_GivenName":  txt("outro_nome2_nome"),
    "P1_Line2c_MiddleName": txt("outro_nome2_meio"),
    "P1_Line3a_FamilyName": txt("outro_nome3_sobrenome"),
    "P1_Line3b_GivenName":  txt("outro_nome3_nome"),
    "P1_Line3c_MiddleName": txt("outro_nome3_meio"),
    "P1_Line4_DateOfBirth": txt("data_nascimento"),
    "P1_Line5_CountryOfBirth": txt("pais_nascimento"),
    "P1_Line6_CountryOfCitizenship": txt("pais_cidadania"),
    "P1_Line7_AlienNumber": txt("alien_number"),
    "P1_Line8_SSN": txt("ssn"),
    "P1_Line9_AcctIdentifier": txt("uscis_online"),
    "Part1_Line10_MaritalStatus": [
        cb("estado_civil", "casado"), cb("estado_civil", "viuvo"),
        cb("estado_civil", "solteiro"), cb("estado_civil", "divorciado"),
    ],
    "P1_Line11_DateOfMarriage": txt("data_casamento"),
    "P1_Line12_PlaceOfMarriage": txt("local_casamento"),
    "P1_Line13_DateMarriageEnded": txt("data_fim_casamento"),
    "P1_Line14_CRExpiresOn": txt("data_expiracao_residencia_condicional"),

    # Endereço de correspondência (item 15)
    "Line17a_InCareofName":       txt("end_correio_cuidados_de"),
    "Line17b_Street_Number_Name": txt("end_correio_rua"),
    "Line17c_Unit": [cb("end_correio_tipo_unidade", "apt"), cb("end_correio_tipo_unidade", "ste"), cb("end_correio_tipo_unidade", "flr")],
    "Line17c_Apt_Ste_Flr_Number": txt("end_correio_num_unidade"),
    "Line17d_City_Town":          txt("end_correio_cidade"),
    "Pt1Line15e_State":           txt("end_correio_estado"),
    "Pt1Line15f_ZipCode":         txt("end_correio_cep"),

    # Item 16 — endereço físico diferente do de correspondência?
    "Line16_Checkbox": [cb("end_fisico_diferente", "nao"), cb("end_fisico_diferente", "sim")],

    # Endereço físico (item 17)
    "Pt1Line17_InCareofName":     txt("end_fisico_cuidados_de"),
    "Pt1Line17_StreetNumberName": txt("end_fisico_rua"),
    "Pt1Line17_Unit": [cb("end_fisico_tipo_unidade", "apt"), cb("end_fisico_tipo_unidade", "ste"), cb("end_fisico_tipo_unidade", "flr")],
    "Pt1Line17_AptSteFlrNumber":  txt("end_fisico_num_unidade"),
    "Pt1Line17_CityOrTown":       txt("end_fisico_cidade"),
    "Pt1Line17_State":            txt("end_fisico_estado"),
    "Pt1Line17_ZipCode":          txt("end_fisico_cep"),

    # Informações adicionais sobre você (itens 18-23)
    "Line17_Checkbox": [cb("em_processo_remocao", "sim"), cb("em_processo_remocao", "nao")],
    "Line18_Checkbox": [cb("taxa_paga_terceiro", "nao"), cb("taxa_paga_terceiro", "sim")],
    "Line19_Checkbox": [cb("ja_foi_preso", "sim"), cb("ja_foi_preso", "nao")],
    "Line20_Checkbox": [cb("casamento_diferente", "nao"), cb("casamento_diferente", "sim")],
    "Line21_Checkbox": [cb("residiu_outro_endereco", "nao"), cb("residiu_outro_endereco", "sim")],
    "Line22_Checkbox": [cb("conjuge_funcionario_governo_exterior", "sim"), cb("conjuge_funcionario_governo_exterior", "nao")],

    # ── Parte 2 — Informações biográficas ───────────────────────────────────────
    "P3_checkbox6": [cb("etnia", "nao_hispanico"), cb("etnia", "hispanico")],
    "P3_checkbox7_Hawaiian": cb("raca_havaiano_pacifico", "sim"),
    "P3_checkbox7_Indian":   cb("raca_indigena_americano", "sim"),
    "P3_checkbox7_White":    cb("raca_branco", "sim"),
    "P3_checkbox7_Asian":    cb("raca_asiatico", "sim"),
    "P3_checkbox7_Black":    cb("raca_negro", "sim"),
    "P3_Line8_HeightFeet":   txt("altura_pes"),
    "P3_Line8_HeightInches": txt("altura_polegadas"),
    # Nome do campo diz "HeightInches" mas é o peso (ver nota no topo do arquivo)
    "P3_Line9_HeightInches1": digit("peso", 1),
    "P3_Line9_HeightInches2": digit("peso", 2),
    "P3_Line9_HeightInches3": digit("peso", 3),
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

    # ── Parte 3 — Base da petição ────────────────────────────────────────────────
    "Pt3Line1": [cb("base_peticao_conjunta", "conjuge"), cb("base_peticao_conjunta", "pai_padrasto")],
    "Pt3Line1c": cb("base_dispensa", "conjuge_falecido"),
    "Pt3Line1d": cb("base_dispensa", "casamento_terminado_divorcio"),
    "Pt3Line1e": cb("base_dispensa", "vitima_violencia_conjuge"),
    "Pt3Line1f": cb("base_dispensa", "vitima_violencia_padrasto"),
    "Pt3Line1g": cb("base_dispensa", "dificuldade_extrema"),

    # ── Parte 4 — Informações sobre o(a) cônjuge cidadão(ã)/residente permanente
    # índice 0 = código B (padrasto), índice 1 = código A (cônjuge) — invertido
    "Part4_Relationship": [cb("relacao_conjuge_americano", "padrasto"), cb("relacao_conjuge_americano", "conjuge")],
    "Pt4Line2a_FamilyName2": txt("conjuge_sobrenome"),
    "Pt4Line2b_GivenName2":  txt("conjuge_nome"),
    "Pt4Line2c_MiddleName2": txt("conjuge_nome_meio"),
    "Line3_DateOfBirth": txt("conjuge_data_nascimento"),
    "Line4_SSN": txt("conjuge_ssn"),
    "Line5_AlienNumber": txt("conjuge_alien_number"),
    "Pt4Line6_StreetNumberName": txt("conjuge_end_rua"),
    "Pt4Line6_Unit": [cb("conjuge_end_tipo_unidade", "apt"), cb("conjuge_end_tipo_unidade", "ste"), cb("conjuge_end_tipo_unidade", "flr")],
    "Pt4Line6_AptSteFlrNumber": txt("conjuge_end_num_unidade"),
    "Pt4Line6_CityOrTown": txt("conjuge_end_cidade"),
    "Pt4Line6_State": txt("conjuge_end_estado"),
    "Pt4Line6_ZipCode": txt("conjuge_end_cep"),
    "Pt4Line6_Province": txt("conjuge_end_provincia"),
    "Pt4Line6_PostalCode": txt("conjuge_end_codigo_postal"),
    "Pt4Line6_Country": txt("conjuge_end_pais"),

    # ── Parte 5 — Informações sobre seus filhos (até 5) ─────────────────────────
    # Filho 1
    "Line1a_FamilyName3": txt("filho1_sobrenome"),
    "Line1b_GivenName3":  txt("filho1_nome"),
    "Line1c_MiddleName3": txt("filho1_nome_meio"),
    "Line2_DateOfBirth2": txt("filho1_data_nascimento"),
    "Line3_AlienNumber":  txt("filho1_alien_number"),
    "Part5Line5": [cb("filho1_mora_com_voce", "nao"), cb("filho1_mora_com_voce", "sim")],
    "Part5Line6": [cb("filho1_aplica_com_voce", "sim"), cb("filho1_aplica_com_voce", "nao")],
    "Pt5Line6_StreetNumberName": txt("filho1_end_rua"),
    "Pt5Line6_Unit": [cb("filho1_end_tipo_unidade", "apt"), cb("filho1_end_tipo_unidade", "ste"), cb("filho1_end_tipo_unidade", "flr")],
    "Pt5Line6_AptSteFlrNumber": txt("filho1_end_num_unidade"),
    "Pt5Line6_CityOrTown": txt("filho1_end_cidade"),
    "Pt5Line6_State": txt("filho1_end_estado"),
    "Pt5Line6_ZipCode": txt("filho1_end_cep"),
    "Pt5Line6_Province": txt("filho1_end_provincia"),
    "Pt5Line6_PostalCode": txt("filho1_end_codigo_postal"),
    "Pt5Line6_Country": txt("filho1_end_pais"),

    # Filhos 2-5 — mesmo nome de campo reaproveitado por índice (0=filho2,
    # 1=filho3, 2=filho4, 3=filho5), confirmado pelo item number no toolTip.
    "Line13a_FamilyName": [txt("filho2_sobrenome"), txt("filho3_sobrenome"), txt("filho4_sobrenome"), txt("filho5_sobrenome")],
    "Line13b_GivenName":  [txt("filho2_nome"), txt("filho3_nome"), txt("filho4_nome"), txt("filho5_nome")],
    "Line13c_MiddleName": [txt("filho2_nome_meio"), txt("filho3_nome_meio"), txt("filho4_nome_meio"), txt("filho5_nome_meio")],
    "Line14_DateOfBirth": [txt("filho2_data_nascimento"), txt("filho3_data_nascimento"), txt("filho4_data_nascimento"), txt("filho5_data_nascimento")],
    "Line15_AlienNumber": [txt("filho2_alien_number"), txt("filho3_alien_number"), txt("filho4_alien_number"), txt("filho5_alien_number")],

    "Part5Line11": [cb("filho2_mora_com_voce", "sim"), cb("filho2_mora_com_voce", "nao")],
    "Part5Line12": [cb("filho2_aplica_com_voce", "nao"), cb("filho2_aplica_com_voce", "sim")],
    "Pt5Line12_StreetNumberName": txt("filho2_end_rua"),
    "Pt5Line12_Unit": [cb("filho2_end_tipo_unidade", "apt"), cb("filho2_end_tipo_unidade", "ste"), cb("filho2_end_tipo_unidade", "flr")],
    "Pt5Line12_AptSteFlrNumber": txt("filho2_end_num_unidade"),
    "Pt5Line12_CityOrTown": txt("filho2_end_cidade"),
    "Pt5Line12_State": txt("filho2_end_estado"),
    "Pt5Line12_ZipCode": txt("filho2_end_cep"),
    "Pt5Line12_Province": txt("filho2_end_provincia"),
    "Pt5Line12_PostalCode": txt("filho2_end_codigo_postal"),
    "Pt5Line12_Country": txt("filho2_end_pais"),

    "Part5Line17": [cb("filho3_mora_com_voce", "sim"), cb("filho3_mora_com_voce", "nao")],
    "Part5Line18": [cb("filho3_aplica_com_voce", "nao"), cb("filho3_aplica_com_voce", "sim")],
    "Pt5Line18_StreetNumberName": txt("filho3_end_rua"),
    "Pt5Line18_Unit": [cb("filho3_end_tipo_unidade", "apt"), cb("filho3_end_tipo_unidade", "ste"), cb("filho3_end_tipo_unidade", "flr")],
    "Pt5Line18_AptSteFlrNumber": txt("filho3_end_num_unidade"),
    "Pt5Line18_CityOrTown": txt("filho3_end_cidade"),
    "Pt5Line18_State": txt("filho3_end_estado"),
    "Pt5Line18_ZipCode": txt("filho3_end_cep"),
    "Pt5Line18_Province": txt("filho3_end_provincia"),
    "Pt5Line18_PostalCode": txt("filho3_end_codigo_postal"),
    "Pt5Line18_Country": txt("filho3_end_pais"),

    "Part5Line23": [cb("filho4_mora_com_voce", "sim"), cb("filho4_mora_com_voce", "nao")],
    "Part5Line24": [cb("filho4_aplica_com_voce", "nao"), cb("filho4_aplica_com_voce", "sim")],
    "Pt5Line24_StreetNumberName": txt("filho4_end_rua"),
    "Pt5Line24_Unit": [cb("filho4_end_tipo_unidade", "apt"), cb("filho4_end_tipo_unidade", "ste"), cb("filho4_end_tipo_unidade", "flr")],
    "Pt5Line24_AptSteFlrNumber": txt("filho4_end_num_unidade"),
    "Pt5Line24_CityOrTown": txt("filho4_end_cidade"),
    "Pt5Line24_State": txt("filho4_end_estado"),
    "Pt5Line24_ZipCode": txt("filho4_end_cep"),
    "Pt5Line24_Province": txt("filho4_end_provincia"),
    "Pt5Line24_PostalCode": txt("filho4_end_codigo_postal"),
    "Pt5Line24_Country": txt("filho4_end_pais"),

    "Part5Line29": [cb("filho5_mora_com_voce", "sim"), cb("filho5_mora_com_voce", "nao")],
    "Part5Line30": [cb("filho5_aplica_com_voce", "nao"), cb("filho5_aplica_com_voce", "sim")],
    "Pt5Line30_StreetNumberName": txt("filho5_end_rua"),
    "Pt5Line30_Unit": [cb("filho5_end_tipo_unidade", "apt"), cb("filho5_end_tipo_unidade", "ste"), cb("filho5_end_tipo_unidade", "flr")],
    "Pt5Line30_AptSteFlrNumber": txt("filho5_end_num_unidade"),
    "Pt5Line30_CityOrTown": txt("filho5_end_cidade"),
    "Pt5Line30_State": txt("filho5_end_estado"),
    "Pt5Line30_ZipCode": txt("filho5_end_cep"),
    "Pt5Line30_Province": txt("filho5_end_provincia"),
    "Pt5Line30_PostalCode": txt("filho5_end_codigo_postal"),
    "Pt5Line30_Country": txt("filho5_end_pais"),

    # ── Parte 6 — Acomodações para pessoas com deficiência ──────────────────────
    "Part6Line1": [cb("acomodacao_propria", "nao"), cb("acomodacao_propria", "sim")],
    "Part6Line2": [cb("acomodacao_conjuge", "sim"), cb("acomodacao_conjuge", "nao")],
    "Part6Line3": [cb("acomodacao_filhos", "nao"), cb("acomodacao_filhos", "sim")],
    "Pt6Line4a_chbx": cb("acomodacao_surdo", "sim"),
    "Pt6Line4_DeafOrHardOfHearing": txt("acomodacao_surdo_detalhe"),
    "Pt6Line4b_chbx": cb("acomodacao_cego", "sim"),
    "Pt6Line4_BlindOrSightImpaired": txt("acomodacao_cego_detalhe"),
    "Pt6Line4c_chbx": cb("acomodacao_outra", "sim"),
    "Pt6Line4_AccomodationRequested": txt("acomodacao_outra_detalhe"),

    # ── Parte 7 — Declaração do(a) peticionário(a) ──────────────────────────────
    "P5_Checkbox1": [cb("leu_ingles", "leu_ingles"), cb("leu_ingles", "leu_interprete")],
    "Pt5Line1b_Language": txt("idioma_interprete"),
    "P5_Line2_NameofRepresentative": txt("preparador_nome"),
    "P5_Checkbox2_Who": [cb("preparador_e_advogado", "sim"), cb("preparador_e_advogado", "nao")],
    "P7_Name": txt("confirmacao_nome_asc"),
    "P5_Line6a_SignatureofPetitioner": {"question_id": "_ignore", "notes": "Assinatura física do peticionário"},
    # P5_Checkbox2, P5_Line3/4/5, P5_Line6b_DateofSignature são compartilhados
    # entre Parte 7 (peticionário) e Parte 8 (cônjuge) — ordem resolvida por
    # adjacência a campos inequívocos (ver nota no topo do arquivo).
    "P5_Checkbox2": [cb("preparador_ajudou", "sim"), cb("conjuge_preparador_ajudou", "sim")],
    "P5_Line3_DaytimePhoneNumber": [txt("telefone"), txt("conjuge_telefone")],
    "P5_Line4_MobilePhoneNumber": [txt("celular"), txt("conjuge_celular")],
    "P5_Line5_EmailAddress": [txt("email"), txt("conjuge_email")],
    "P5_Line6b_DateofSignature": [txt("data_assinatura"), txt("conjuge_data_assinatura")],

    # ── Parte 8 — Declaração do(a) cônjuge/indivíduo da Parte 4 (se aplicável) ──
    "P8_Checkbox1": [cb("conjuge_leu_ingles", "leu_ingles"), cb("conjuge_leu_ingles", "leu_interprete")],
    "Pt7Line1b_Language": txt("conjuge_idioma_interprete"),
    "P7Line2_NameofRepresentative": txt("conjuge_preparador_nome"),
    "P7_Checkbox2_Who": [cb("conjuge_preparador_e_advogado", "sim"), cb("conjuge_preparador_e_advogado", "nao")],
    "Pt8_Name": txt("conjuge_confirmacao_nome_asc"),
    "P5_Line6a_SignatureofSpouse": {"question_id": "_ignore", "notes": "Assinatura física do cônjuge"},

    # ── Parte 9 — Intérprete (se usado) ─────────────────────────────────────────
    "P6_Line1a_InterpretersFamilyName": txt("int_sobrenome"),
    "P6_Line1b_InterpretersGivenName":  txt("int_nome"),
    "P6_Line2_NameofBusinessor": txt("int_organizacao"),
    "P6_Line3a_StreetNumberName": txt("int_end_rua"),
    "Pt9Line3_Unit": [cb("int_end_tipo_unidade", "apt"), cb("int_end_tipo_unidade", "ste"), cb("int_end_tipo_unidade", "flr")],
    "Pt9Line3_AptSteFlrNumber": txt("int_end_num_unidade"),
    "Pt9Line3_CityOrTown": txt("int_end_cidade"),
    "Pt9Line3_State": txt("int_end_estado"),
    "Pt9Line3_ZipCode": txt("int_end_cep"),
    "Pt9Line3_Province": txt("int_end_provincia"),
    "Pt9Line3_PostalCode": txt("int_end_codigo_postal"),
    "Pt9Line3_Country": txt("int_end_pais"),
    "P6_Line4_InterpretersDaytimePhoneNumber": txt("int_telefone"),
    "P6_Line5_InterpretersEmailAddress": txt("int_email"),
    "P6_Language": txt("int_idioma"),
    "P6_Line6a_Signature": {"question_id": "_ignore", "notes": "Assinatura física do intérprete"},
    "P6_Line6b_DateofSignature": txt("int_data_assinatura"),

    # ── Parte 10 — Preparador (se diferente do peticionário) ────────────────────
    "P7_Line1a_FamilyName": txt("prep_sobrenome"),
    "P7_Line1b_PreparersGivenName": txt("prep_nome"),
    "P7_Line2_NameofBusinessor": txt("prep_organizacao"),
    "Pt9Line3_StreetNumberName": txt("prep_end_rua"),
    "Pt10Line3_AptSteFlrNumber": txt("prep_end_num_unidade"),
    "Pt10Line3_Unit": [cb("prep_end_tipo_unidade", "apt"), cb("prep_end_tipo_unidade", "ste"), cb("prep_end_tipo_unidade", "flr")],
    "P7_Line3c_CityTown": txt("prep_end_cidade"),
    "P7_Line3d_State": txt("prep_end_estado"),
    "P7_Line3e_ZipCode": txt("prep_end_cep"),
    "P7_Line3f_Province": txt("prep_end_provincia"),
    "P7_Line3g_PostalCode": txt("prep_end_codigo_postal"),
    "P7_Line3h_Country": txt("prep_end_pais"),
    "P7_Line4_PreparersDaytimePhoneNumber": txt("prep_telefone"),
    # Ao contrário de outros formulários, aqui o toolTip confirma que é
    # mesmo um número de FAX (ver nota no topo do arquivo) — não celular.
    "P7_Line5_PreparersFaxNumber": txt("prep_fax"),
    "P7_Line6_PreparersEmailAddress": txt("prep_email"),
    "P7_checkbox7": {"question_id": "_ignore", "notes": "Declaração advogado vs não-advogado, fora do escopo"},
    "Pt10Item7b_Extends": {"question_id": "_ignore"},
    "Pt10Item7b_NotExtend": {"question_id": "_ignore"},
    "P7_Line8a_SignatureofPreparer": {"question_id": "_ignore", "notes": "Assinatura física do preparador"},
    "P7_Line8b_DateofSignature": txt("prep_data_assinatura"),

    # ── Parte 11 — Informações adicionais (espaço extra) — não preenchido por padrão
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
    "P8_Line6a_PageNumber": {"question_id": "_ignore"},
    "P8_Line6b_PartNumber": {"question_id": "_ignore"},
    "P8_Line6c_ItemNumber": {"question_id": "_ignore"},
    "P8_Line6d_AdditionalInfo": {"question_id": "_ignore"},
    "P8_Line7a_PageNumber": {"question_id": "_ignore"},
    "P8_Line7b_PartNumber": {"question_id": "_ignore"},
    "P8_Line7c_ItemNumber": {"question_id": "_ignore"},
    "P8_Line7d_AdditionalInfo": {"question_id": "_ignore"},
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

    out_data = {"form": "I-751", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/i-751.skeleton.json",
                base_dir / "data/mappings/i-751.json")
