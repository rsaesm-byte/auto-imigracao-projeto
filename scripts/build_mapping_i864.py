"""
build_mapping_i864.py — Aplica os question_id ao esqueleto de mapeamento do I-864.

Uso:
    python scripts/build_mapping_i864.py
    # Sobrescreve data/mappings/i-864.json com question_id preenchidos.

Nomes de campo enganosos confirmados neste formulário (mapeado pelo toolTip real,
não pelo nome interno — não "corrija" achando que é erro de digitação):
    - "P4_Line7_CityofBirth": tooltip confirma que é o item 7 "Country of Birth"
      (país), não cidade.
    - "P6_Line1a_NameofEmployer": tooltip diz "Enter what you are employed as"
      (ocupação/cargo), não nome do empregador.
    - "P8_Line2_Attorney": tooltip diz "Enter Name of Preparer" — não é
      necessariamente um advogado.
    - "P7Line7_EmailAddress", "P7Line9b_DateofSignature", "P8Line2_..." (Parte 9):
      prefixos "P7"/"P8" sobraram de outra revisão do desenho; o toolTip confirma
      a Parte real (8 ou 9).
    - "P10_Line5_PreparersFaxNumber": tooltip diz "Mobile Telephone Number", não fax.

Campo reaproveitado para dados diferentes por posição (sem /AP, é texto):
    "P2_Line5_AlienNumber" aparece 3 vezes com os MESMOS 3 candidatos de toolTip
    (principal / Family Member 1 / Family Member 3) em cada ocorrência — a real
    correspondência foi confirmada pela ORDEM DE APARIÇÃO no documento (índice 0
    fica na Parte 3, antes da Parte 4 começar; índice 1 fica logo após os campos
    do Family Member 1; índice 2 logo após os campos do Family Member 3),
    não pela ordem dos candidatos de toolTip dentro do bloco.

Checkboxes sem toolTip no XFA (confirmados lendo o texto extraído da página,
mesma técnica usada no I-765/I-485):
    - P1_Line3_Checkbox: item 3, "Is your current mailing address the same as
      your physical address?" (página 2)
    - P4_Line14_Checkboxes: item 12, "I am currently on active duty in the
      United States Armed Forces or U.S. Coast Guard." (página 2)
    - P6_Line18a_Checkbox: item 15, "Have you filed a Federal income tax return
      for each of the three most recent tax years?" (página 6)
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
    "G28-CheckBox1":         {"question_id": "_ignore", "notes": "Checkbox G-28 anexado (advogado)"},
    "AttorneyStateBarNumber":{"question_id": "_ignore", "notes": "OAB/Bar do advogado"},
    "USCISOnlineAcctNumber": {"question_id": "_ignore", "notes": "Conta USCIS Online do advogado"},

    # ── Parte 1 — Base para o pedido (Basis For Filing) ─────────────────────────
    # índice segue a ordem lógica (confirmado via /AP: 1A..1F)
    "P1_Line1a-f_CB": [
        cb("motivo_patrocinio", "peticionario"),
        cb("motivo_patrocinio", "peticionario_trabalhador"),
        cb("motivo_patrocinio", "proprietario_5pct"),
        cb("motivo_patrocinio", "unico_patrocinador_conjunto"),
        cb("motivo_patrocinio", "um_dos_dois_patrocinadores_conjuntos"),
        cb("motivo_patrocinio", "patrocinador_substituto"),
    ],
    "P1_Line1b_Relationship": txt("motivo_trabalhador_relacao"),
    "P1_Line1c_InterestIn":   txt("motivo_proprietario_negocio"),
    "P1_Line1c_Relationship": txt("motivo_proprietario_relacao"),
    "P1_Line1e1_Checkbox": [cb("patrocinador_conjunto_ordem", "primeiro"), cb("patrocinador_conjunto_ordem", "segundo")],
    "P1_Line1f_Relationship": txt("motivo_substituto_relacao"),
    "P1_Line3_Checkbox": [cb("sponsor_end_fisico_igual_correio", "sim"), cb("sponsor_end_fisico_igual_correio", "nao")],

    # ── Parte 2 — Informações sobre você (patrocinador) ─────────────────────────
    "P4_Line1a_FamilyName": txt("sponsor_sobrenome"),
    "P4_Line1b_GivenName":  txt("sponsor_nome"),
    "P4_Line1c_MiddleName": txt("sponsor_nome_meio"),

    "P4_Line2a_InCareOf":         txt("sponsor_end_correio_cuidados_de"),
    "P4_Line2b_StreetNumberName": txt("sponsor_end_correio_rua"),
    "P4_Line2c_Unit": [cb("sponsor_end_correio_tipo_unidade", "apt"), cb("sponsor_end_correio_tipo_unidade", "ste"), cb("sponsor_end_correio_tipo_unidade", "flr")],
    "P4_Line2d_AptSteFlrNumber": txt("sponsor_end_correio_num_unidade"),
    "P4_Line2e_CityOrTown":      txt("sponsor_end_correio_cidade"),
    "P4_Line2f_State":           txt("sponsor_end_correio_estado"),
    "P4_Line2g_ZipCode":         txt("sponsor_end_correio_cep"),
    "P4_Line2h_Province":        txt("sponsor_end_correio_provincia"),
    "P4_Line2i_PostalCode":      txt("sponsor_end_correio_codigo_postal"),
    "P4_Line2j_Country":         txt("sponsor_end_correio_pais"),

    "P4_Line4a_StreetNumberName": txt("sponsor_end_fisico_rua"),
    "P4_Line4b_Unit": [cb("sponsor_end_fisico_tipo_unidade", "apt"), cb("sponsor_end_fisico_tipo_unidade", "ste"), cb("sponsor_end_fisico_tipo_unidade", "flr")],
    "P4_Line4c_AptSteFlrNumber": txt("sponsor_end_fisico_num_unidade"),
    "P4_Line4d_CityOrTown":      txt("sponsor_end_fisico_cidade"),
    "P4_Line4e_State":           txt("sponsor_end_fisico_estado"),
    "P4_Line4f_ZipCode":         txt("sponsor_end_fisico_cep"),
    "P4_Line4g_Province":        txt("sponsor_end_fisico_provincia"),
    "P4_Line4h_PostalCode":      txt("sponsor_end_fisico_codigo_postal"),
    "P4_Line4i_Country":         txt("sponsor_end_fisico_pais"),

    "P4_Line5_CountryOfDomicile": txt("sponsor_pais_domicilio"),
    "P4_Line6_DateOfBirth":       txt("sponsor_data_nascimento"),
    "P4_Line7_CityofBirth":       txt("sponsor_pais_nascimento",),
    "P4_Line10_SocialSecurityNumber": txt("sponsor_ssn"),

    "P4_Line11a_Checkbox": cb("sponsor_status_imigracao", "cidadao"),
    "P4_Line11b_Checkbox": cb("sponsor_status_imigracao", "nacional"),
    "P4_Line11c_Checkbox": cb("sponsor_status_imigracao", "residente_permanente"),

    "P4_Line12_AlienNumber":  txt("sponsor_alien_number"),
    "P4_Line13_AcctIdentifier": txt("sponsor_uscis_online"),
    "P4_Line14_Checkboxes": [cb("sponsor_servico_militar_ativo", "sim"), cb("sponsor_servico_militar_ativo", "nao")],

    # ── Parte 3 — Informações sobre o(a) imigrante principal ────────────────────
    "P2_Line1a_FamilyName": txt("imigrante_sobrenome"),
    "P2_Line1b_GivenName":  txt("imigrante_nome"),
    "P2_Line1c_MiddleName": txt("imigrante_nome_meio"),
    "P2_Line2_InCareOf":         txt("imigrante_end_cuidados_de"),
    "P2_Line2_StreetNumberName": txt("imigrante_end_rua"),
    "P2_Line2_Unit": [cb("imigrante_end_tipo_unidade", "apt"), cb("imigrante_end_tipo_unidade", "ste"), cb("imigrante_end_tipo_unidade", "flr")],
    "P2_Line2_AptSteFlrNumber": txt("imigrante_end_num_unidade"),
    "P2_Line2_CityOrTown":      txt("imigrante_end_cidade"),
    "P2_Line2_State":           txt("imigrante_end_estado"),
    "P2_Line2_ZipCode":         txt("imigrante_end_cep"),
    "P2_Line2_Province":        txt("imigrante_end_provincia"),
    "P2_Line2_PostalCode":      txt("imigrante_end_codigo_postal"),
    "P2_Line2_Country":         txt("imigrante_end_pais"),
    "P2_Line3_CountryCitizenship": txt("imigrante_pais_cidadania"),
    "P2_Line4_DateOfBirth":        txt("imigrante_data_nascimento"),
    # Ordem confirmada por posição no documento (ver nota no topo do arquivo):
    # índice 0 = imigrante principal, índice 1 = Family Member 1, índice 2 = Family Member 3.
    "P2_Line5_AlienNumber": [txt("imigrante_alien_number"), txt("familia1_alien_number"), txt("familia3_alien_number")],
    "Pt2_Line6_USCISOnlineAcctNumber": txt("imigrante_uscis_online"),
    "P2_Line7_DaytimePhoneNumber":     txt("imigrante_telefone"),

    # ── Parte 4 — Informações sobre os imigrantes que você está patrocinando ────
    "P3_Line1_Checkbox": [cb("patrocina_principal", "sim"), cb("patrocina_principal", "nao")],
    "P3_Line2_SponsoringFamily": [
        cb("patrocina_familia_mesma_data", "sim"),
        cb("patrocina_familia_mais_tarde", "sim"),
    ],

    "P3_Line3a_FamilyName": txt("familia1_sobrenome"),
    "P3_Line3b_GivenName":  txt("familia1_nome"),
    "P3_Line3c_MiddleName": txt("familia1_nome_meio"),
    "P3_Line4_Relationship": txt("familia1_relacao"),
    "P3_Line_DateOfBirth":   txt("familia1_data_nascimento"),
    "P3_Line7_AcctIdentifier": txt("familia1_uscis_online"),

    "P3_Line8a_FamilyName": txt("familia2_sobrenome"),
    "P3_Line8b_GivenName":  txt("familia2_nome"),
    "P3_Line8c_MiddleName": txt("familia2_nome_meio"),
    "P3_Line9_Relationship": txt("familia2_relacao"),
    "P3_Line10_DateOfBirth": txt("familia2_data_nascimento"),
    "P3_Line11_AlienNumber": txt("familia2_alien_number"),
    "P3_Line12_AcctIdentifier": txt("familia2_uscis_online"),

    "P3_Line13a_FamilyName": txt("familia3_sobrenome"),
    "P3_Line13b_GivenName":  txt("familia3_nome"),
    "P3_Line13c_MiddleName": txt("familia3_nome_meio"),
    "P3_Line14_Relationship": txt("familia3_relacao"),
    "P3_Line15_DateOfBirth": txt("familia3_data_nascimento"),
    "P3_Line17_AcctIdentifier": txt("familia3_uscis_online"),

    "P3_Line18a_FamilyName": txt("familia4_sobrenome"),
    "P3_Line18b_GivenName":  txt("familia4_nome"),
    "P3_Line18c_MiddleName": txt("familia4_nome_meio"),
    "P3_Line19_Relationship": txt("familia4_relacao"),
    "P3_Line20_DateOfBirth": txt("familia4_data_nascimento"),
    "P3_Line21_AlienNumber": txt("familia4_alien_number"),
    "P3_Line22_AcctIdentifier": txt("familia4_uscis_online"),

    # ── Parte 5 — Tamanho do domicílio do patrocinador ──────────────────────────
    "P3_Line28_TotalNumberofImmigrants": txt("total_imigrantes_patrocinados"),
    "P5_Line2_Yourself":          txt("household_voce_mesmo"),
    "P5_Line3_Married":           txt("household_conjuge"),
    "P5_Line4_DependentChildren": txt("household_filhos_dependentes"),
    "P5_Line5_OtherDependents":   txt("household_outros_dependentes"),
    "P5_Line6_Sponsors":          txt("household_outros_patrocinados_antes"),
    "P5_Line7_SameResidence":     txt("household_parentes_mesma_residencia"),
    "Override":                   txt("household_total"),

    # ── Parte 6 — Emprego e renda do patrocinador ───────────────────────────────
    # LIMITAÇÃO CONHECIDA DO PDF: este nome de campo é reaproveitado para 3
    # perguntas totalmente diferentes (Parte 6 "empregado" + Parte 8 "leu
    # inglês"/"usou intérprete"), mas o XFA datasets só tem 1 nó de dado para
    # as 3. O AcroForm sempre fica correto (cada widget tem seu próprio /V),
    # mas se as respostas tornarem 2 delas verdadeiras ao mesmo tempo (ex.:
    # "empregado=sim" E "usou intérprete=sim" — combinação real e plausível,
    # não só de teste), o XFA não tem como representar as duas ao mesmo tempo
    # nesse nó único; fill_form.py detecta a ambiguidade e deixa o nó como
    # está (não adivinha) em vez de sobrescrever com um valor arbitrário. Isso
    # é uma limitação do desenho do PDF, não um bug do preenchedor.
    "P6_Line1_Checkbox": [
        cb("sponsor_empregado", "sim"),
        cb("leu_ingles", "leu_ingles"),
        cb("leu_ingles", "leu_interprete"),
    ],
    "P6_Line1a_NameofEmployer":  txt("sponsor_ocupacao_atual"),
    "P6_Line1a1_NameofEmployer": txt("sponsor_empregador1_nome"),
    "P6_Line1a2_NameofEmployer": txt("sponsor_empregador2_nome"),
    "P6_Line4_Checkbox": cb("sponsor_autonomo", "sim"),
    "P6_Line4a_SelfEmployedAs":  txt("sponsor_autonomo_ocupacao"),
    "P6_Line5_Checkbox": cb("sponsor_aposentado", "sim"),
    "P6_Line5a_DateRetired":     txt("sponsor_aposentado_desde"),
    "P6_Line6_Checkbox": cb("sponsor_desempregado", "sim"),
    "P6_Line6a_DateofUnemployment": txt("sponsor_desempregado_desde"),
    "P6_Line2_TotalIncome":      txt("sponsor_renda_individual_atual"),

    "P6_Line3_Name": txt("pessoa1_nome"),
    "P6_Line4_Relationship": txt("pessoa1_relacao"),
    "P6_Line5_CurrentIncome": txt("pessoa1_renda"),
    "P6_Line6_Name": txt("pessoa2_nome"),
    "P6_Line7_Relationship": txt("pessoa2_relacao"),
    "P6_Line8_CurrentIncome": txt("pessoa2_renda"),
    "P6_Line9_Name": txt("pessoa3_nome"),
    "P6_Line10_Relationship": txt("pessoa3_relacao"),
    "P6_Line11_CurrentIncome": txt("pessoa3_renda"),
    "P6_Line12_Name": txt("pessoa4_nome"),
    "P6_Line13_Relationship": txt("pessoa4_relacao"),
    "P6_Line14_CurrentIncome": txt("pessoa4_renda"),
    "P6_Line15_TotalHouseholdIncome": txt("renda_familiar_total"),

    "P6_Line16_CompletedForm":  cb("pessoas_completaram_i864a", "sim"),
    "P6_Line17_NotNeedComplete": cb("pessoa_nao_precisa_i864a", "sim"),
    "P6_Line17_Name": txt("pessoa_nao_precisa_i864a_nome"),
    "P6_Line18a_Checkbox": [cb("declarou_impostos_3anos", "sim"), cb("declarou_impostos_3anos", "nao")],
    "P6_Line19a_TaxYear": txt("imposto_ano1_ano"),
    "P6_Line19a_TotalIncome": txt("imposto_ano1_renda"),
    "P6_Line19b_TaxYear": txt("imposto_ano2_ano"),
    "P6_Line19b_TotalIncome": txt("imposto_ano2_renda"),
    "P6_Line19c_TaxYear": txt("imposto_ano3_ano"),
    "P6_Line19c_TotalIncome": txt("imposto_ano3_renda"),
    "P6_Line17_IWasNotReq": cb("nao_precisou_declarar_impostos", "sim"),

    # ── Parte 7 — Uso de ativos para complementar a renda ───────────────────────
    "P7_Line1_BalanceofAccounts": txt("ativo_saldo_contas"),
    "P7_Line2_RealEstate":        txt("ativo_imoveis"),
    "P7_Line3_StocksBonds":       txt("ativo_acoes_titulos"),
    "P7_Line4_Total":             txt("ativo_total_patrocinador"),
    "P7_Line5_TotalAssetsHouseholdMembers": txt("ativo_total_membros_familia"),
    "P7_Line6_BalanceofAccounts": txt("ativo_imigrante_saldo_contas"),
    "P7_Line7_RealEstate":        txt("ativo_imigrante_imoveis"),
    "P7_Line8_StocksBonds":       txt("ativo_imigrante_acoes_titulos"),
    "P7_Line9_Total":             txt("ativo_imigrante_total"),
    "P7_Line10_TotalValueAssets": txt("ativo_valor_total_geral"),

    # ── Parte 8 — Declaração, contato e assinatura do patrocinador ──────────────
    "P8_Line1b_language": txt("idioma_interprete"),
    "P8_Line2_Checkbox": cb("preparador_ajudou", "sim"),
    "P8_Line2_Attorney": txt("preparador_nome"),
    "P8_Line3_DaytimeTelephoneNumber": txt("sponsor_telefone"),
    "P8_Line4_MobileTelephoneNumber":  txt("sponsor_celular"),
    "P7Line7_EmailAddress": txt("sponsor_email"),
    "P8_Line9a_ApplicantSignature": {"question_id": "_ignore", "notes": "Assinatura física do patrocinador"},
    "P7Line9b_DateofSignature": txt("sponsor_data_assinatura"),

    # ── Parte 9 — Intérprete (se usado) ─────────────────────────────────────────
    "P9_Line1a_InterpretersFamilyName": txt("int_sobrenome"),
    "P9_Line1b_InterpretersGivenName":  txt("int_nome"),
    "P8Line2_InterpretersBusinessName": txt("int_organizacao"),
    # Mesmo nome reaproveitado para telefone fixo (item3) e celular (item4) —
    # ordem confirmada por padrão já observado em I-130A/I-765 (índice segue a
    # ordem sequencial dos itens quando não há /AP para desambiguar).
    "P9_Line4_InterpretersDaytimePhoneNumber": [txt("int_telefone"), txt("int_celular")],
    "P9_Line5_InterpretersEmailAddress": txt("int_email"),
    "P9_Language": txt("int_idioma"),
    "P9_Line6a_InterpretersSignature": {"question_id": "_ignore", "notes": "Assinatura física do intérprete"},
    "P9_Line6b_DateofSignature": txt("int_data_assinatura"),

    # ── Parte 10 — Preparador (se diferente do patrocinador) ────────────────────
    "P10_Line1a_PreparersFamilyName": txt("prep_sobrenome"),
    "P10_Line1b_PreparersGivenName":  txt("prep_nome"),
    "P10_Line2_PreparersBusinessName": txt("prep_organizacao"),
    "P10_Line4_PreparersDaytimePhoneNumber": txt("prep_telefone"),
    "P10_Line5_PreparersFaxNumber": txt("prep_celular"),
    "P10_Line6_PreparersEmailAddress": txt("prep_email"),
    "P10_Line8a_PreparersSignature": {"question_id": "_ignore", "notes": "Assinatura física do preparador"},
    "P10_Line8b_DateofSignature": txt("prep_data_assinatura"),

    # ── Parte 11 — Informações adicionais (espaço extra) — não preenchido por padrão
    "P11_Line3a_PageNumber": {"question_id": "_ignore"},
    "P11_Line3b_PartNumber": {"question_id": "_ignore"},
    "P11_Line3c_ItemNumber": {"question_id": "_ignore"},
    "P11_Line3d_AdditionalInfo": {"question_id": "_ignore"},
    "P11_Line4a_PageNumber": {"question_id": "_ignore"},
    "P11_Line4b_PartNumber": {"question_id": "_ignore"},
    "P11_Line4c_ItemNumber": {"question_id": "_ignore"},
    "P11_Line4d_AdditionalInfo": {"question_id": "_ignore"},
    "P11_Line5a_PageNumber": {"question_id": "_ignore"},
    "P11_Line5b_PartNumber": {"question_id": "_ignore"},
    "P11_Line5c_ItemNumber": {"question_id": "_ignore"},
    "P11_Line5d_AdditionalInfo": {"question_id": "_ignore"},
    "P11_Line6a_PageNumber": {"question_id": "_ignore"},
    "P11_Line6b_PartNumber": {"question_id": "_ignore"},
    "P11_Line6c_ItemNumber": {"question_id": "_ignore"},
    "P11_Line6d_AdditionalInfo": {"question_id": "_ignore"},
}

# Nota: os campos "read only, pre-filled from page 1" (nome e A-Number do
# patrocinador repetidos na folha de continuação da Parte 11) usam os MESMOS
# nomes-base acima ("P4_Line1a_FamilyName" etc.) — como as regras são simples
# dicts (não listas), toda ocorrência do mesmo nome-base recebe automaticamente
# o mesmo question_id, sem precisar de tratamento especial. Isso vale mesmo
# quando a segunda ocorrência está aninhada num container extra (ex.:
# "Global_ANumber[0].P4_Line12_AlienNumber[1]"), porque o nome-base é extraído
# do ÚLTIMO segmento do path, que já ignora esse container pai.


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

    out_data = {"form": "I-864", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/i-864.skeleton.json",
                base_dir / "data/mappings/i-864.json")
