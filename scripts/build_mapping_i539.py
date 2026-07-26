"""
build_mapping_i539.py — Aplica os question_id ao esqueleto de mapeamento do I-539.

Uso:
    python scripts/build_mapping_i539.py
    # Sobrescreve data/mappings/i-539.json com question_id preenchidos.

Peculiaridades confirmadas neste formulário (via toolTip do XFA "template",
extraído campo a campo — nomes internos dos campos NÃO são confiáveis, vários
mentem sobre o que realmente preenchem):
    - "Pt1Line15a_NewStatus" (Parte 1, Item 12): apesar do nome dizer
      "NewStatus", o toolTip confirma que é o status atual ("Current
      Nonimmigrant Status") — dropdown /Ch NÃO editável (Ff sem bit Edit) com
      303 opções oficiais. Sem infraestrutura de select genérico no motor do
      questionário (só há suporte especializado a UF americana), então vira
      pergunta de texto livre com aviso explícito para digitar o código exato
      (ex.: F1, B2, H1B) — mesmo padrão já usado para "classe_admissao" no
      I-90.
    - "Pt2Line2a_NewStatus" (Parte 2, Item 2): dropdown real de "novo status"
      (140 opções), mas o produto só oferece 3 status de destino (B2/F1/F2) —
      pergunta vira rádio com exatamente esses 3 valores, que devem bater
      EXATAMENTE com o /Opt real do PDF (confirmado via pypdf: 'B2', 'F1',
      'F2', sem hífen).
    - "SupA_Line1k_Passport" é o MESMO nome de campo reaproveitado 3x para
      coisas diferentes (confirmado por toolTip, não pelo nome): índice 0 =
      Número do Passaporte (Parte 1, Item 11); índice 1 = Nome da Escola
      (Parte 2, Item 5); índice 2 = SEVIS ID (Parte 2, Item 6).
    - "P3_Line4_NameofPetitioner" reaproveitado 2x: índice 0 = primeiro nome
      do beneficiário/requerente da petição relacionada; índice 1 = sobrenome
      (toolTip diz literalmente "End Last Name...").
    - "P4_Line1a_CountryOfIssuance" reaproveitado 2x: índice 0 = país de
      emissão do passaporte ATUAL (se diferente da Parte 1); índice 1 = NÚMERO
      do passaporte atual (nome do campo mente sobre isso).
    - "P6_Line4_DaytimePhoneNumber" reaproveitado 2x (mesmo padrão já visto no
      I-90/I-751): índice 0 = telefone fixo do intérprete, índice 1 = celular.
    - "P6_Line7_SignatureApplicant" / "P6_Line7_DateofSignature" reaproveitados
      2x cada: índice 0 = assinatura/data do REQUERENTE (Parte 5), índice 1 =
      assinatura/data do INTÉRPRETE (Parte 6) — mesmo par de nomes de campo
      serve para duas seções completamente diferentes.
    - "P7_Line1_PreparerFamilyName"/"GivenName"/"NameofBusinessorOrgName"
      (subform 4): apesar do nome dizer "Preparer", o toolTip confirma que são
      os campos de nome do INTÉRPRETE (Parte 6) — os campos do preparador de
      fato ficam em "P7_Line1a_Preparer*"/"P7_Line1b_Preparer*" (subform 5,
      Parte 7). Formulário reaproveita o texto "Preparer" em dois blocos
      distintos.
    - "P7_Line5_FaxPhoneNumber": nome diz "Fax", toolTip confirma "Mobile
      Telephone Number" — mesma classe de erro de nome já documentada no I-90.
    - Nome/sobrenome/nome do meio/A-Number reaparecem sem sufixo de índice
      diferenciado (mesmo "base" de nome, MAS via regra não-lista, aplicada a
      TODAS as ocorrências) na página de Informação Adicional (Parte 8,
      cabeçalho "No Entry... prepopulated from page 1") — mapeados para os
      MESMOS question_id da Parte 1, preenchendo a folha de continuação
      automaticamente.
    - Blocos "Parte 8. Informação Adicional" (itens 3-6, campos
      PageNumber/PartNumber/ItemNumber/AdditionalInfo) deixados como
      "_ignore", mesmo padrão já usado no I-90/N-400 (não há como amarrar 1:1
      a explicação de qual das ~18 perguntas Sim/Não da Parte 4 sem inventar
      lógica condicional que o motor do questionário não suporta hoje —
      ver questionnaire-engine.md sobre show_if só suportar igualdade simples
      com UMA pergunta anterior, sem AND/OR).
    - Pelo mesmo motivo (sem AND/OR em show_if), os campos "nome da escola" /
      "SEVIS ID" (relevantes só para quem muda para F-1 ou F-2) e o bloco de
      "petição/pedido relacionado de cônjuge/filho(a)/pai/mãe" (Parte 3, itens
      4-7) ficam SEMPRE visíveis no questionário, porém opcionais, com texto
      de ajuda explicando quando se aplicam — em vez de tentar simular um OR
      com dois question_id duplicados.
    - Seção do Formulário G-28 / advogado (CheckBox1, AttorneyStateBarNumber,
      USCISOnlineAcctNumber do advogado) fora do escopo desta ferramenta
      (autopreenchimento para o próprio requerente) — mesmo padrão dos outros
      8 formulários. "_ignore".
"""

import json
from pathlib import Path


def cb(question_id: str, check_if_answer) -> dict:
    return {"type": "checkbox", "question_id": question_id, "check_if_answer": check_if_answer}


def txt(question_id: str) -> dict:
    return {"type": "text", "question_id": question_id}


def choice_mapped(question_id: str, value_map: dict) -> dict:
    return {"type": "choice", "question_id": question_id, "value_map": value_map}


def ignore() -> dict:
    return {"question_id": "_ignore"}


MAPPING_RULES: dict[str, object] = {

    # ── Advogado / G-28 — fora do escopo ─────────────────────────────────────
    "CheckBox1": ignore(),
    "AttorneyStateBarNumber": ignore(),
    "USCISOnlineAcctNumber": ignore(),

    # ── Parte 1 — Informações sobre Você ─────────────────────────────────────
    "Pt1Line2_AlienNumber": txt("alien_number"),
    "Pt1Line2_USCISOnlineAcctNumber": txt("uscis_online"),
    "P1Line1a_FamilyName": txt("nome_sobrenome"),
    "P1_Line1b_GivenName": txt("nome_nome"),
    "P1_Line1c_MiddleName": txt("nome_meio"),

    # Item 4 — endereço de correspondência (campos "Part2_Item11_*" apesar do
    # nome — toolTip confirma que são a Parte 1, Item 4)
    "Part2_Item11_InCareOfName": txt("end_correio_cuidados_de"),
    "Part2_Item11_StreetName":   txt("end_correio_rua"),
    "Part1_Item4_Unit": [cb("end_correio_tipo_unidade", "apt"), cb("end_correio_tipo_unidade", "ste"), cb("end_correio_tipo_unidade", "flr")],
    "Part1_Item4_Number": txt("end_correio_num_unidade"),
    "Part2_Item11_City":    txt("end_correio_cidade"),
    "Part2_Item11_State":   txt("end_correio_estado"),
    "Part2_Item11_ZipCode": txt("end_correio_cep"),

    # Item 5 — endereço de correspondência é igual ao físico?
    "P1_checkbox5": [cb("end_mesmo_que_correio", "nao"), cb("end_mesmo_que_correio", "sim")],

    # Item 6 — endereço físico atual (se diferente do de correspondência)
    "Part1_Item6_StreetName": txt("end_fisico_rua"),
    "Part1_Item6_Unit": [cb("end_fisico_tipo_unidade", "apt"), cb("end_fisico_tipo_unidade", "ste"), cb("end_fisico_tipo_unidade", "flr")],
    "Part1_Item6_Number": txt("end_fisico_num_unidade"),
    "Part1_Item6_City":   txt("end_fisico_cidade"),
    "Part1_Item6_State":  txt("end_fisico_estado"),
    "Part1_Item6_ZipCode": txt("end_fisico_cep"),

    # Itens 7-10 — nascimento, cidadania, SSN
    "P1_Line6_CountryOfBirth":      txt("pais_nascimento"),
    "P1_Line7_CountryOfCitizenship": txt("pais_cidadania"),
    "P1_Line8_DateOfBirth": txt("data_nascimento"),
    "P1_Line9_SSN": txt("ssn"),

    # Item 11 — entrada mais recente nos EUA
    "SupA_Line1i_DateOfArrival":    txt("data_ultima_entrada"),
    "SupA_Line1j_ArrivalDeparture": txt("numero_i94"),
    "SupA_Line1l_TravelDoc":          txt("numero_documento_viagem"),
    "SupA_Line1m_CountryOfIssuance":  txt("pais_emissao_passaporte"),
    "SupA_Line1n_ExpDate":            txt("data_expiracao_passaporte"),
    # "SupA_Line1k_Passport" é reaproveitado 3x — precisa de regra por índice (lista)
    "SupA_Line1k_Passport": [txt("numero_passaporte"), txt("escola_nome"), txt("sevis_id")],

    # Item 12 — status atual
    "Pt1Line15a_NewStatus":     txt("status_atual_codigo"),
    "SupA_Line1p_DateExpires":  txt("status_atual_expira"),
    "P1_Checkbox12c": cb("status_atual_duracao_status", "sim"),

    # ── Parte 2 — Tipo de Aplicação ───────────────────────────────────────────
    # Uma única pergunta de negócio ("servico") representa os 4 serviços que a
    # empresa vende: EOS (extensão), COS B2/F1/F2 (mudança de status para um
    # dos 3 destinos suportados). Ela alimenta DOIS campos distintos do PDF:
    #   - Item 1 (P2_checkbox): "eos" ativa a caixa de extensão (B); os outros
    #     3 valores ("cos_b2"/"cos_f1"/"cos_f2") ativam a caixa de mudança de
    #     status (C) — daí o check_if_answer em LISTA (OR), suportado por
    #     resolve_value em fill_form.py especificamente para este caso de uso.
    #   - Item 2 (Pt2Line2a_NewStatus, dropdown "novo status"): só se aplica a
    #     quem pediu mudança — "value_map" traduz "cos_b2"/"cos_f1"/"cos_f2"
    #     para o código oficial exigido pelo PDF ("B2"/"F1"/"F2"); "eos" (e
    #     "restabelecimento_na", opção A do PDF fora do escopo dos 4 serviços)
    #     não estão no mapa, então o campo simplesmente fica em branco.
    "P2_checkbox": [cb("servico", "eos"), cb("servico", ["cos_b2", "cos_f1", "cos_f2"]), cb("servico", "restabelecimento_na")],
    "Pt2Line2a_NewStatus": choice_mapped("servico", {"cos_b2": "B2", "cos_f1": "F1", "cos_f2": "F2"}),
    "Pt2Line2b_EffectiveDate": txt("data_efetiva_mudanca"),
    # Item 3 — quantidade de pessoas incluídas
    "P2_checkbox4": [cb("numero_pessoas", "sozinho"), cb("numero_pessoas", "com_familia")],
    # Item 4 — total de pessoas
    "P2_Line5b_TotalNumber": txt("total_pessoas"),

    # ── Parte 3 — Informações de Processamento ───────────────────────────────
    "P3_Line1a_DateExtended": txt("data_solicitada_ate"),
    # Item 2 — baseado em extensão/mudança já concedida a cônjuge/filho(a)/pai/mãe?
    "P3_checkbox2a": [cb("pedido_baseado_status_familiar", "nao"), cb("pedido_baseado_status_familiar", "sim")],
    # Item 3 — baseado em petição/pedido separado para dar extensão/mudança a cônjuge/filho(a)/pai/mãe?
    "P3_checkbox1": [cb("pedido_baseado_peticao_separada", "nao"), cb("pedido_baseado_peticao_separada", "sim_com_este_i539"), cb("pedido_baseado_peticao_separada", "sim_previamente_pendente")],
    # Item 4 — tipo do formulário relacionado (I-539 ou I-129)
    "P3_checkbox4": [cb("tipo_formulario_relacionado", "i539"), cb("tipo_formulario_relacionado", "i129")],
    # Item 5 — número de recibo USCIS
    "P3_Line5_ReceiptNumber": txt("numero_recibo_uscis"),
    # Item 6 — nome do beneficiário/requerente da petição relacionada (reaproveitado 2x: 0=primeiro nome, 1=sobrenome)
    "P3_Line4_NameofPetitioner": [txt("nome_peticao_relacionada_primeiro"), txt("nome_peticao_relacionada_ultimo")],
    # Item 7 — data de protocolo
    "P3_Line5_DateFiled": txt("data_protocolo_peticao_relacionada"),

    # ── Parte 4 — Informações Adicionais Sobre o Requerente ──────────────────
    # Item 1 — passaporte atual, se diferente da Parte 1
    "P4_Line1b_ExpirationDate": txt("passaporte_atual_expiracao"),
    # "P4_Line1a_CountryOfIssuance" reaproveitado 2x: 0=país de emissão, 1=número do passaporte
    "P4_Line1a_CountryOfIssuance": [txt("passaporte_atual_pais_emissao"), txt("passaporte_atual_numero")],

    # Item 2 — endereço físico no exterior
    "P2_Line10_StreetName": txt("end_exterior_rua"),
    "P2_Line10_Unit": [cb("end_exterior_tipo_unidade", "apt"), cb("end_exterior_tipo_unidade", "ste"), cb("end_exterior_tipo_unidade", "flr")],
    "P2_Line10_Number":     txt("end_exterior_num_unidade"),
    "P2_Line10_City":       txt("end_exterior_cidade"),
    "P2_Line10_Province":   txt("end_exterior_provincia"),
    "P2_Line10_PostalCode": txt("end_exterior_cep"),
    "P2_Line10_Country":    txt("end_exterior_pais"),

    # Itens 3-15 — perguntas de antecedentes (Sim/Não), campos Yes/No nomeados separadamente
    "P4_checkbox3_No":  cb("imigrante_visa_pendente", "nao"),
    "P4_checkbox3_Yes": cb("imigrante_visa_pendente", "sim"),
    "P4_checkbox4_No":  cb("peticao_imigrante_ja_apresentada", "nao"),
    "P4_checkbox4_Yes": cb("peticao_imigrante_ja_apresentada", "sim"),
    "P4_checkbox5_No":  cb("ja_apresentou_i485", "nao"),
    "P4_checkbox5_Yes": cb("ja_apresentou_i485", "sim"),
    "P4_checkbox6_No":  cb("preso_condenado_desde_entrada", "nao"),
    "P4_checkbox6_Yes": cb("preso_condenado_desde_entrada", "sim"),
    "P4_checkbox7_No":  cb("ato_tortura_genocidio", "nao"),
    "P4_checkbox7_Yes": cb("ato_tortura_genocidio", "sim"),
    "P4_checkbox8_No":  cb("matou_pessoa", "nao"),
    "P4_checkbox8_Yes": cb("matou_pessoa", "sim"),
    "P4_checkbox9_No":  cb("feriu_gravemente_pessoa", "nao"),
    "P4_checkbox9_Yes": cb("feriu_gravemente_pessoa", "sim"),
    "P4_checkbox10_No":  cb("contato_sexual_sem_consentimento", "nao"),
    "P4_checkbox10_Yes": cb("contato_sexual_sem_consentimento", "sim"),
    "P4_checkbox11_No":  cb("limitou_liberdade_religiosa", "nao"),
    "P4_checkbox11_Yes": cb("limitou_liberdade_religiosa", "sim"),
    "P4_checkbox12_No":  cb("servico_militar_paramilitar", "nao"),
    "P4_checkbox12_Yes": cb("servico_militar_paramilitar", "sim"),
    "P4_checkbox13_No":  cb("trabalhou_prisao_detencao", "nao"),
    "P4_checkbox13_Yes": cb("trabalhou_prisao_detencao", "sim"),
    "P4_checkbox14_No":  cb("membro_grupo_armas_ameaca", "nao"),
    "P4_checkbox14_Yes": cb("membro_grupo_armas_ameaca", "sim"),
    "P4_checkbox15_No":  cb("vendeu_transportou_armas", "nao"),
    "P4_checkbox15_Yes": cb("vendeu_transportou_armas", "sim"),
    "P4_checkbox16_No":  cb("treinamento_militar_armas", "nao"),
    "P4_checkbox16_Yes": cb("treinamento_militar_armas", "sim"),
    "P4_checkbox17_No":  cb("violou_termos_status", "nao"),
    "P4_checkbox17_Yes": cb("violou_termos_status", "sim"),
    "P4_checkbox18_No":  cb("em_processo_remocao", "nao"),
    "P4_checkbox18_Yes": cb("em_processo_remocao", "sim"),
    "P4_checkbox19_No":  cb("empregado_eua_desde_ultima_entrada", "nao"),
    "P4_checkbox19_Yes": cb("empregado_eua_desde_ultima_entrada", "sim"),
    "P4_checkbox20_No":  cb("j1_j2_exchange_visitor", "nao"),
    "P4_checkbox20_Yes": cb("j1_j2_exchange_visitor", "sim"),

    # ── Parte 5 — Contato, Certificação e Assinatura do Requerente ──────────
    "P5_Line3_DaytimePhoneNumber": txt("telefone"),
    "P5_Line4_MobilePhoneNumber":  txt("celular"),
    "P5_Line5_EmailAddress": txt("email"),
    # "P6_Line7_SignatureApplicant"/"DateofSignature" reaproveitados 2x:
    # índice 0 = requerente (Parte 5), índice 1 = intérprete (Parte 6)
    "P6_Line7_SignatureApplicant": [ignore(), ignore()],
    "P6_Line7_DateofSignature":    [txt("data_assinatura"), txt("int_data_assinatura")],

    # ── Parte 6 — Contato, Certificação e Assinatura do Intérprete ──────────
    # Nomes de campo dizem "Preparer" mas o toolTip confirma: são do intérprete
    "P7_Line1_PreparerFamilyName": txt("int_sobrenome"),
    "P7_Line1_PreparerGivenName":  txt("int_nome"),
    "P7_Line2_PreparerNameofBusinessorOrgName": txt("int_organizacao"),
    "P6_Line5_EmailAddress": txt("int_email"),
    # Reaproveitado 2x: 0 = fixo, 1 = celular
    "P6_Line4_DaytimePhoneNumber": [txt("int_telefone"), txt("int_celular")],
    "P7_Line6_Language": txt("int_idioma"),

    # ── Parte 7 — Contato, Declaração e Assinatura do Preparador ────────────
    "P7_Line1a_PreparerFamilyName": txt("prep_sobrenome"),
    "P7_Line1b_PreparerGivenName":  txt("prep_nome"),
    "P7_Line2_BusinessName": txt("prep_organizacao"),
    "P7_Line6_EmailAddress": txt("prep_email"),
    "P7_Line4_PreparerDaytimePhoneNumber": txt("prep_telefone"),
    # Nome do campo diz "Fax" mas o toolTip confirma "Mobile Telephone Number"
    "P7_Line5_FaxPhoneNumber": txt("prep_celular"),
    "P7_Line8a_SignatureofPreparer": ignore(),
    "P7_Line8b_DateofSignature": txt("prep_data_assinatura"),

    # ── Parte 8 — Informação Adicional ───────────────────────────────────────
    # Cabeçalho repetido (nome/A-Number "prepopulated from page 1") — mesmos
    # question_id da Parte 1, regra NÃO-lista aplica a todas as ocorrências
    "Pt1Line2_AlienNumber_p8_alias": None,  # placeholder não usado (ver nota abaixo)
    "P8_Line4_A_PageNumber": ignore(), "P8_Line4_B_PartNumber": ignore(),
    "P8_Line4_C_ItemNumber": ignore(), "P8_Line4_D_AdditionalInfo": ignore(),
    "P8_Line5_A_PageNumber": ignore(), "P8_Line5_B_PartNumber": ignore(),
    "P8_Line5_C_ItemNumber": ignore(), "P8_Line5_D_AdditionalInfo": ignore(),
    "P8_Line3_A_PageNumber": ignore(), "P8_Line3_B_PartNumber": ignore(),
    "P8_Line3_C_ItemNumber": ignore(), "P8_Line3_D_AdditionalInfo": ignore(),
    "P8_Line6_A_PageNumber": ignore(), "P8_Line6_B_PartNumber": ignore(),
    "P8_Line6_C_ItemNumber": ignore(), "P8_Line6_D_AdditionalInfo": ignore(),
}

del MAPPING_RULES["Pt1Line2_AlienNumber_p8_alias"]


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

        # Último segmento do caminho, sem o índice "[n]"
        import re
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
            if "value_map" in item:
                entry["value_map"] = item["value_map"]
            result_fields.append(entry)
            continue

        if rule is None:
            unmapped.append(pdf_field)
            continue

        entry = {"pdf_field": pdf_field, "type": rule.get("type", ftype), "question_id": rule["question_id"]}
        if "check_if_answer" in rule:
            entry["check_if_answer"] = rule["check_if_answer"]
        if "value_map" in rule:
            entry["value_map"] = rule["value_map"]
        result_fields.append(entry)

    if unmapped:
        print(f"AVISO: {len(unmapped)} campo(s) sem regra de mapeamento:")
        for u in unmapped:
            print(f"  - {u}")
    else:
        print("Todos os campos cobertos.")

    out_data = {"form": "I-539", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/i-539.skeleton.json",
                base_dir / "data/mappings/i-539.json")
