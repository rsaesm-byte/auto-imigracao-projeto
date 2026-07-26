"""
build_mapping_i485.py — Aplica os question_id ao esqueleto de mapeamento do I-485.

Uso:
    python scripts/build_mapping_i485.py

Notas importantes (achadas construindo este mapa — não repita a investigação):

1. Os números de "Part" nos toolTips do XFA estão FURADOS/desatualizados em vários
   campos (ex.: biográfico/elegibilidade aparecem como "Part 7"/"Part 8" no nome
   interno do campo, mas o texto real da página confirma que são Parte 8
   "Biographic Information" e Parte 9 "General Eligibility and Inadmissibility
   Grounds"). NÃO confie no prefixo "PtN" do nome do campo para decidir a Parte —
   use o texto extraído da página (output/_i485_pagetext.txt, já removido ao final
   do build, mas o conteúdo relevante foi transcrito nos comentários abaixo).

2. Nos pares Sim/Não de elegibilidade (Parte 9), o SUFIXO numérico do nome do campo
   (ex.: "Pt9Line23_YesNo", "Pt8Line24a_YesNo") bate de forma confiável com o
   número do item impresso do lado da pergunta na página — isso foi verificado
   item a item contra o texto da página. O que NÃO é confiável é o prefixo "Pt8"
   vs "Pt9" (aparecem misturados para itens consecutivos).

3. Diferente dos formulários anteriores, aqui usamos o PRÓPRIO CÓDIGO real (lido
   do /AP) para decidir o check_if_answer em vez de depender de ordem/índice:
   quando o grupo é literalmente Sim/Não, os on-values são as strings "Y"/"N"
   (às vezes na ordem [Y,N], às vezes [N,Y] — sem padrão fixo, confirmado campo a
   campo antes de escrever cada linha abaixo). Mapeamos check_if_answer="sim" para
   o candidato cujo on-value real é "Y" e "nao" para "N", index por index, nunca
   assumindo a ordem.

4. `Pt9Line56_CB` código '1' tem um toolTip claramente errado/corrompido no XFA
   (fala de "Lautenberg Parolees" do item 1.F, sem relação com a lista de 24
   categorias isentas do item 56). Por eliminação contra a lista completa de
   categorias isentas no texto da página, o código '1' só pode ser "Refugee
   Status (INA section 207), Form I-590 or Form I-730" — é a única categoria da
   lista da página que não apareceu em nenhum outro código. Mapeado como tal,
   com esta nota para quem revisar depois.

5. Alguns nomes de campo têm o número da Parte MUITO errado por causa de reuso de
   template (ex.: "a_YesNo"/"b_YesNo" sem prefixo nenhum — são os itens 42.a e
   42.b de "Security and Related", confirmados por posição entre os itens 41 e
   42.c/42.d no esqueleto e pela ausência de qualquer outro candidato razoável).
"""

import json
import re
from pathlib import Path


def cb(question_id: str, check_if_answer: str) -> dict:
    return {"type": "checkbox", "question_id": question_id, "check_if_answer": check_if_answer}


def txt(question_id: str) -> dict:
    return {"type": "text", "question_id": question_id}


def ignore() -> dict:
    return {"question_id": "_ignore"}


MAPPING_RULES: dict[str, object] = {}

# ── Administrativo / advogado ───────────────────────────────────────────────
MAPPING_RULES.update({
    "AttorneyStateBarNumber": ignore(),
    "CheckBox1": ignore(),
    "VolagNumber": ignore(),
    "USCISOnlineAcctNumber": ignore(),
})

# ── Parte 1 — Informações sobre você ────────────────────────────────────────
MAPPING_RULES.update({
    "AlienNumber": txt("alien_number"),  # repetido em várias páginas — mesmo question_id (pré-populado)
    "Pt1Line1_FamilyName": txt("nome_sobrenome"),
    "Pt1Line1_GivenName": txt("nome_nome"),
    "Pt1Line1_MiddleName": txt("nome_meio"),
    "Pt1Line2_FamilyName": txt("outro_nome1_sobrenome"),
    "Pt1Line2_GivenName": txt("outro_nome1_nome"),
    "Pt1Line2_MiddleName": txt("outro_nome1_meio"),
    "Pt1Line2a_FamilyName": txt("outro_nome2_sobrenome"),
    "Pt1Line2a_GivenName": txt("outro_nome2_nome"),
    "Pt1Line2a_MiddleName": txt("outro_nome2_meio"),
    "Pt1Line3_DOB": txt("data_nascimento"),
    "Pt1Line3_YN": [cb("outra_data_nascimento", "sim"), cb("outra_data_nascimento", "nao")],  # real_on Y,N
    "Pt1Line3A_OtherDOB": txt("outra_data_nascimento_1"),
    "Pt1Line3B_OtherDOB": txt("outra_data_nascimento_2"),
    "Pt1Line4_AlienNumber": txt("alien_number"),  # "se sim, informe o A-Number" -> mesmo dado
    "Pt1Line4_YN": [cb("tem_alien_number", "sim"), cb("tem_alien_number", "nao")],  # real_on Y,N
    "Pt1Line5_YN": [cb("outro_alien_number_usado", "sim"), cb("outro_alien_number_usado", "nao")],  # real_on Y,N
    "Pt1Line5A_ANumber": txt("outro_alien_number_1"),
    "Pt1Line5B_ANumber": txt("outro_alien_number_2"),
    "Pt1Line6_CB_Sex": [cb("sexo", "feminino"), cb("sexo", "masculino")],  # real_on F,M
    "Pt1Line7_CityTownOfBirth": txt("nascimento_cidade"),
    "Pt1Line7_CountryOfBirth": txt("nascimento_pais"),
    "Pt1Line8_CountryofCitizenshipNationality": txt("cidadania_pais"),
    "Pt1Line9_USCISAccountNumber": txt("uscis_online"),
    # item 10 — último ingresso com passaporte/doc de viagem
    "Pt1Line10_PassportNum": txt("passaporte_numero"),
    "Pt1Line10_ExpDate": txt("passaporte_data_expiracao"),
    "Pt1Line10_Passport": txt("passaporte_pais_emissao"),
    "Pt1Line10_VisaNum": txt("visto_numero"),
    "Pt1Line10_NonImmDate": txt("visto_data_emissao"),
    "Pt1Line10_CityTown": txt("ultima_entrada_cidade"),
    "Pt1Line10_State": txt("ultima_entrada_estado"),
    "Pt1Line10_DateofArrival": txt("ultima_entrada_data"),
    # item 11 — histórico recente de imigração (inspecionado/admitido, ou paroled, ou sem inspeção)
    "Pt1Line11_Admitted": txt("ultima_entrada_admitido_como"),
    "Pt1Line11_Paroled": txt("ultima_entrada_paroled_como"),
    "Pt1Line11_Other": txt("ultima_entrada_outro"),
    # Pt2Line11_CB: os 4 toolTips no XFA para este campo estão TODOS corrompidos
    # (repetem, idênticos, um texto sobre "Cuban Adjustment Act" sem relação com
    # o item 11). Reconstruído por posição (4 checkboxes empilhados na margem
    # esquerda da página 2, ao lado dos 3 textos "admitted as / paroled as /
    # sem admissão" já mapeados acima + uma 4a opção "Other") e pelo contexto de
    # "Recent Immigration History" — NÃO confirmado por toolTip; revisar
    # manualmente contra o PDF renderizado antes de usar em produção.
    "Pt2Line11_CB": [
        cb("ultima_entrada_tipo", "admitido"), cb("ultima_entrada_tipo", "paroled"),
        cb("ultima_entrada_tipo", "sem_admissao_parole"), cb("ultima_entrada_tipo", "outro"),
    ],
    # item 12 (I-94)
    "P1Line12_FamilyName": txt("i94_sobrenome"),
    "P1Line13_GivenName": txt("i94_nome"),
    "Pt1Line12_Date": txt("i94_data_expiracao_estadia"),
    "Pt1Line12_Status": txt("i94_status_imigracao"),
    "P1Line12_I94": txt("i94_numero"),
    "Pt1Line13_YN": [cb("primeira_vez_presente_eua", "sim"), cb("primeira_vez_presente_eua", "nao")],  # item12 Y/N; real_on Y,N
    "Pt1Line14_Status": txt("status_atual_imigracao"),
    "Pt1Line15_Date": txt("status_atual_data_expiracao"),
    "Pt1Line16_YN": [cb("visto_crewman", "sim"), cb("visto_crewman", "nao")],  # item16; real_on Y,N
    "Pt1Line17_YN": [cb("chegou_como_tripulante", "nao"), cb("chegou_como_tripulante", "sim")],  # item17; real_on N,Y
    # item 18 — Current U.S. Physical Address
    "Pt1Line18_StreetNumberName": txt("end_fisico_rua"),
    "Pt1Line18US_Unit": [cb("end_fisico_tipo_unidade", "ste"), cb("end_fisico_tipo_unidade", "flr"), cb("end_fisico_tipo_unidade", "apt")],  # real_on STE,FLR,APT
    "Pt1Line18US_AptSteFlrNumber": txt("end_fisico_num_unidade"),
    "Pt1Line18_CityOrTown": txt("end_fisico_cidade"),
    "Pt1Line18_State": txt("end_fisico_estado"),
    "Pt1Line18_ZipCode": txt("end_fisico_cep"),
    "Part1_Item18_InCareOfName": txt("end_fisico_cuidados_de"),
    "Pt1Line18_Date": txt("end_fisico_desde"),
    "Pt1Line18_YN": [cb("end_correio_igual_fisico", "sim"), cb("end_correio_igual_fisico", "nao")],  # item13; real_on Y,N
    # Current Mailing Address (se diferente)
    "Pt1Line18_CurrentStreetNumberName": txt("end_correio_rua"),
    "Pt1Line18_CurrentUnit": [cb("end_correio_tipo_unidade", "apt"), cb("end_correio_tipo_unidade", "ste"), cb("end_correio_tipo_unidade", "flr")],  # real_on APT,STE,FLR
    "Pt1Line18_CurrentAptSteFlrNumber": txt("end_correio_num_unidade"),
    "Pt1Line18_CurrentCityOrTown": txt("end_correio_cidade"),
    "Pt1Line18_CurrentState": txt("end_correio_estado"),
    "Pt1Line18_CurrentZipCode": txt("end_correio_cep"),
    "Pt1Line18_CurrentInCareOfName": txt("end_correio_cuidados_de"),
    "Pt1Line18_last5yrs_YN": [cb("mora_atual_5anos", "sim"), cb("mora_atual_5anos", "nao")],  # real_on Y,N
    # Prior Address (se < 5 anos no atual)
    "Pt1Line18_PriorInCareOfName": txt("end_ant_cuidados_de"),
    "Pt1Line18_PriorStreetName": txt("end_ant_rua"),
    "Pt1Line18_PriorAddress_Unit": [cb("end_ant_tipo_unidade", "apt"), cb("end_ant_tipo_unidade", "ste"), cb("end_ant_tipo_unidade", "flr")],  # real_on APT,STE,FLR
    "Pt1Line18_PriorAddress_Number": txt("end_ant_num_unidade"),
    "Pt1Line18_PriorCity": txt("end_ant_cidade"),
    "Pt1Line18_PriorState": txt("end_ant_estado"),
    "Pt1Line18_PriorZipCode": txt("end_ant_cep"),
    "Pt1Line18_PriorProvince": txt("end_ant_provincia"),
    "Pt1Line18_PriorPostalCode": txt("end_ant_codigo_postal"),
    "Pt1Line18_PriorCountry": txt("end_ant_pais"),
    "Pt1Line18_PriorDateFrom": txt("end_ant_desde"),
    "Pt1Line18PriorDateTo": txt("end_ant_ate"),
    # Most Recent Address Outside the US (>1 ano, se nao listado acima)
    "Pt1Line18_RecentStreetName": txt("end_ext_rua"),
    "Pt1Line18_RecentUnit": [cb("end_ext_tipo_unidade", "apt"), cb("end_ext_tipo_unidade", "ste"), cb("end_ext_tipo_unidade", "flr")],  # real_on APT,STE,FLR
    "Pt1Line18_RecentNumber": txt("end_ext_num_unidade"),
    "Pt1Line18_RecentCity": txt("end_ext_cidade"),
    "Pt1Line18_RecentState": txt("end_ext_estado"),
    "Pt1Line18_RecentZipCode": txt("end_ext_cep"),
    "Pt1Line18_RecentProvince": txt("end_ext_provincia"),
    "Pt1Line18_RecentPostalCode": txt("end_ext_codigo_postal"),
    "Pt1Line18_RecentCountry": txt("end_ext_pais"),
    "Pt1Line18_RecentDateFrom": txt("end_ext_desde"),
    "Pt1Line18_RecentDateTo": txt("end_ext_ate"),
    # item 19 — Social Security Card
    "Pt1Line19_YN": [cb("ssa_quer_cartao", "nao"), cb("ssa_quer_cartao", "sim")],  # real_on N,Y
    "Pt1Line19_SSN": txt("ssn"),
    "Pt1Line19_SSA_YN": [cb("ssa_ja_emitiu_cartao", "sim"), cb("ssa_ja_emitiu_cartao", "nao")],  # real_on Y,N
    "Pt1Line19_Consent_YN": [cb("ssa_consentimento_divulgacao", "sim"), cb("ssa_consentimento_divulgacao", "nao")],  # real_on Y,N
})

# ── Parte 2 — Tipo de Aplicação / Categoria de Arquivamento ────────────────
MAPPING_RULES.update({
    "Pt2Line1_YN": [cb("eoir_remocao", "sim"), cb("eoir_remocao", "nao")],  # real_on Y,N
    "Pt2Line2_Receipt": txt("peticao_subjacente_recibo"),
    "Pt2Line2_Date": txt("peticao_subjacente_data_prioridade"),
    "Pt2Line2_FamilyName": txt("aplicante_principal_sobrenome"),
    "Pt2Line2_GivenName": txt("aplicante_principal_nome"),
    "Pt2Line2_MiddleName": txt("aplicante_principal_meio"),
    "Pt1Line2_DOB": txt("aplicante_principal_data_nascimento"),
    "Pt2Line2_AlienNumber": txt("aplicante_principal_alien_number"),
    "Pt2Line2_CB": [cb("tipo_aplicante", "principal"), cb("tipo_aplicante", "derivativo")],  # real_on 1fA,1fB
    # 3.a-3.g — categoria de imigrante (grupo grande, uma linha por opção)
    "Pt2Line3a_CB": [
        cb("categoria_imigrante", "familia_conjuge_cidadao"),           # 3a0
        cb("categoria_imigrante", "familia_filho_menor21_cidadao"),      # 3a1
        cb("categoria_imigrante", "familia_pai_mae_cidadao"),            # 3a2
        cb("categoria_imigrante", "familia_noivo_k1k2"),                 # 3a3
        cb("categoria_imigrante", "familia_viuvo_cidadao"),              # 3a4
        cb("categoria_imigrante", "familia_conjuge_filho_pai_militar_ndaa"),  # 3a5
        cb("categoria_imigrante", "familia_filho_maior21_cidadao"),      # 3a6
        cb("categoria_imigrante", "familia_filho_casado_cidadao"),       # 3a7
        cb("categoria_imigrante", "familia_irmao_irma_cidadao"),         # 3a8
        cb("categoria_imigrante", "familia_conjuge_lpr"),                # 3a9
        cb("categoria_imigrante", "familia_filho_menor21_lpr"),          # 3a10
        cb("categoria_imigrante", "familia_filho_maior21_lpr"),          # 3a11
        cb("categoria_imigrante", "vawa_conjuge"),                       # 3a12
        cb("categoria_imigrante", "vawa_filho"),                         # 3a13
        cb("categoria_imigrante", "vawa_pai_mae"),                       # 3a14
    ],
    "Pt2Line3b_CB526": [cb("categoria_imigrante", "investidor_i526")],  # 3b0 (I-526/I-526E, fora da lista de 8 do I-140)
    "Pt2Line3b_CB140": [
        cb("categoria_imigrante", "emp_habilidade_extraordinaria"),      # 3b1
        cb("categoria_imigrante", "emp_professor_pesquisador"),          # 3b2
        cb("categoria_imigrante", "emp_executivo_multinacional"),        # 3b3
        cb("categoria_imigrante", "emp_profissional_grau_avancado"),     # 3b4
        cb("categoria_imigrante", "emp_profissional_bacharel"),          # 3b5
        cb("categoria_imigrante", "emp_trabalhador_qualificado"),        # 3b6
        cb("categoria_imigrante", "emp_outro_trabalhador"),              # 3b7
        cb("categoria_imigrante", "emp_national_interest_waiver"),       # 3b8
    ],
    "Pt2Line3b_CB140Assoc": [cb("emp_140_parente_envolvido", "na"), cb("emp_140_parente_envolvido", "nao"), cb("emp_140_parente_envolvido", "sim")],  # real_on NA,N,Y
    "Pt2Relative_CB": [
        cb("emp_140_parente_tipo", "pai"), cb("emp_140_parente_tipo", "mae"),
        cb("emp_140_parente_tipo", "filho"), cb("emp_140_parente_tipo", "filho_adulto"),
        cb("emp_140_parente_tipo", "filha_adulta"), cb("emp_140_parente_tipo", "irmao"),
        cb("emp_140_parente_tipo", "irma"), cb("emp_140_parente_tipo", "nenhum_destes"),
    ],
    "Pt2RelativeType_CB": [
        cb("emp_140_parente_status", "cidadao"), cb("emp_140_parente_status", "nacional"),
        cb("emp_140_parente_status", "lpr"), cb("emp_140_parente_status", "nenhum_destes"),
    ],
    # ATENÇÃO: a ordem real dos widgets para este campo NÃO é sequencial (3c0,3c1,
    # 3c2...) — o /AP confirma a ordem real como 3c1,3c0,3c3,3c2,3c5,3c4,3c6,3c7,
    # 3c9,3c8 (pares trocados). A lista abaixo segue essa ordem REAL, não a ordem
    # numérica dos códigos — não "arrume" isso reordenando por número sem antes
    # reconferir o /AP de cada índice.
    "Pt2Line3c_CB": [
        cb("categoria_imigrante", "esp_afegao_iraquiano"),        # 3c1 (índice 0)
        cb("categoria_imigrante", "esp_imigrante_juvenil"),       # 3c0 (índice 1)
        cb("categoria_imigrante", "esp_g4_nato6"),                # 3c3 (índice 2)
        cb("categoria_imigrante", "esp_locutor_internacional"),   # 3c2 (índice 3)
        cb("categoria_imigrante", "esp_canal_panama"),            # 3c5 (índice 4)
        cb("categoria_imigrante", "esp_forcas_armadas_seis_seis"),# 3c4 (índice 5)
        cb("categoria_imigrante", "esp_medico"),                  # 3c6 (índice 6)
        cb("categoria_imigrante", "esp_empregado_governo_exterior"), # 3c7 (índice 7)
        cb("categoria_imigrante", "esp_trabalhador_religioso_outro"), # 3c9 (índice 8)
        cb("categoria_imigrante", "esp_ministro_religioso"),      # 3c8 (índice 9)
    ],
    "Pt2Line3d_AsyleeRefugeeCB": [cb("categoria_imigrante", "asilo"), cb("categoria_imigrante", "refugiado")],  # 3d0,3d1
    "Pt2Line3d_Asylum": txt("asilo_data_concessao"),
    "Pt2Line3d_Refugee": txt("refugiado_data_admissao"),
    "Pt2Line3e_CB": [cb("categoria_imigrante", "vitima_trafico_t"), cb("categoria_imigrante", "vitima_crime_u")],  # 3e0,3e1
    "Pt2Line3f_CB": [
        cb("categoria_imigrante", "cuban_adjustment_act"),         # 3f0
        cb("categoria_imigrante", "cuban_adjustment_vitima_violencia"),  # 3f2
        cb("categoria_imigrante", "haitian_fairness_dependente"),  # 3f3
        cb("categoria_imigrante", "haitian_fairness_vitima_violencia"),  # 3f4
        cb("categoria_imigrante", "lautenberg_parolee"),           # 3f5
        cb("categoria_imigrante", "diplomata_secao13"),            # 3f6
        cb("categoria_imigrante", "vietnam_camboja_laos_pl106_429"),  # 3f7
        cb("categoria_imigrante", "amerasian_act"),                # 3f8
    ],
    "Pt2Line1g_OtherEligibility": txt("categoria_imigrante_outro_texto"),
    "Pt2Line1g_DV": txt("diversity_visa_numero"),
    "Pt2Line3g_CB": [
        cb("categoria_imigrante", "diversity_visa"),               # 3g0
        cb("categoria_imigrante", "registry_1972"),                # 3g1
        cb("categoria_imigrante", "nascido_status_diplomatico"),   # 3g2
        cb("categoria_imigrante", "s_nonimmigrant"),                # 3g3
        cb("categoria_imigrante", "outra_elegibilidade"),           # 3g4
    ],
    "Pt2Line4_CB": [cb("aplicando_245i", "nao"), cb("aplicando_245i", "sim")],  # item4; real_on N,Y
    "Pt2Line5_CB": [cb("aplicando_cspa", "nao"), cb("aplicando_cspa", "sim")],  # item5; real_on N,Y
})

# ── Parte 3 — Isenção de Affidavit of Support (213A) ────────────────────────
MAPPING_RULES.update({
    "Pt3Line1_CB": [
        cb("isencao_affidavit_motivo", "40_trimestres"),    # 0 (1.a)
        cb("isencao_affidavit_motivo", "menor18_filho_cidadao"),  # 1 (1.b)
        cb("isencao_affidavit_motivo", "viuvo_cidadao"),    # 2 (1.c)
        cb("isencao_affidavit_motivo", "vawa"),             # 3 (1.d)
        cb("isencao_affidavit_motivo", "nao_precisa"),      # 4 (1.e)
        cb("isencao_affidavit_motivo", "precisa_apresentar"),  # 5 (1.f) - na pratica indica que NAO se isenta
    ],
    "Pt3Line2_CityTown": txt("embaixada_cidade"),
    "Pt4Line2_CityTown": txt("embaixada_cidade"),
    "Pt4Line2_CityTownOfBirth": txt("embaixada_pais"),
})

# ── Parte 4 — Informações Adicionais Sobre Você ─────────────────────────────
MAPPING_RULES.update({
    "Pt4Line1_YN": [cb("ja_pediu_visto_imigrante", "nao"), cb("ja_pediu_visto_imigrante", "sim")],  # real_on N,Y
    "Pt4Line3_Decision": txt("visto_imigrante_decisao"),
    "Pt4Line4_Date": txt("visto_imigrante_data_decisao"),
    "Pt4Line5_YN": [cb("pediu_residencia_antes", "nao"), cb("pediu_residencia_antes", "sim")],  # real_on N,Y
    "Pt4Line6_YN": [cb("lpr_status_rescindido", "nao"), cb("lpr_status_rescindido", "sim")],  # real_on N,Y
    # Emprego/educacao atual (item 7)
    "Pt4Line7_EmployerName": txt("emp1_nome"),
    "Pt4Line8_Occupation": txt("emp1_ocupacao"),
    "Part4Line7_StreetName": txt("emp1_end_rua"),
    "P4Line7_Unit": [cb("emp1_end_tipo_unidade", "apt"), cb("emp1_end_tipo_unidade", "ste"), cb("emp1_end_tipo_unidade", "flr")],
    "P4Line7_Number": txt("emp1_end_num_unidade"),
    "P4Line7_City": txt("emp1_end_cidade"),
    "P4Line7_State": txt("emp1_end_estado"),
    "P4Line7_ZipCode": txt("emp1_end_cep"),
    "P4Line7_PostalCode": txt("emp1_end_codigo_postal"),
    "P4Line7_Province": txt("emp1_end_provincia"),
    "P4Line7_Country": txt("emp1_end_pais"),
    "Pt4Line7_DateFrom": txt("emp1_desde"),
    "Pt4Line7_DateTo": txt("emp1_ate"),
    # Emprego/educacao anterior fora dos EUA (item 8)
    "Pt4Line8_EmployerName": txt("emp2_nome"),
    "Pt4Line7_Occupation": txt("emp2_ocupacao"),
    "Part4Line8_StreetName": txt("emp2_end_rua"),
    "P4Line8_StreetName": txt("emp2_end_rua"),  # nome inconsistente (falta "Part") p/ o mesmo campo
    "P4Line8_Unit": [cb("emp2_end_tipo_unidade", "apt"), cb("emp2_end_tipo_unidade", "ste"), cb("emp2_end_tipo_unidade", "flr")],
    "P4Line8_Number": txt("emp2_end_num_unidade"),
    "P4Line8_City": txt("emp2_end_cidade"),
    "P4Line8_State": txt("emp2_end_estado"),
    "P4Line8_ZipCode": txt("emp2_end_cep"),
    "P4Line8_PostalCode": txt("emp2_end_codigo_postal"),
    "P4Line8_Province": txt("emp2_end_provincia"),
    "P4Line8_Country": txt("emp2_end_pais"),
    "Pt4Line8_DateFrom": txt("emp2_desde"),
    "Pt4Line8_DateTo": txt("emp2_ate"),
})

# ── Parte 5 — Informações Sobre Seus Pais ───────────────────────────────────
MAPPING_RULES.update({
    "Pt5Line1_FamilyName": txt("pai1_sobrenome"),
    "Pt5Line1_GivenName": txt("pai1_nome"),
    "Pt5Line1_MiddleName": txt("pai1_nome_meio"),
    "Pt5Line2_FamilyName": txt("pai1_nascimento_sobrenome"),
    "Pt5Line2_GivenName": txt("pai1_nascimento_nome"),
    "Pt5Line2_MiddleName": txt("pai1_nascimento_meio"),
    "Pt5Line3_DateofBirth": txt("pai1_data_nascimento"),
    "Pt5Line5_CityTownOfBirth": txt("pai1_pais_nascimento"),
    "Pt5Line6_FamilyName": txt("pai2_sobrenome"),
    "Pt5Line6_GivenName": txt("pai2_nome"),
    "Pt5Line6_MiddleName": txt("pai2_nome_meio"),
    "Pt5Line7_FamilyName": txt("pai2_nascimento_sobrenome"),
    "Pt5Line7_GivenName": txt("pai2_nascimento_nome"),
    "Pt5Line7_MiddleName": txt("pai2_nascimento_meio"),
    "Pt5Line8_DateofBirth": txt("pai2_data_nascimento"),
    "Pt5Line10_CityTownOfBirth": txt("pai2_pais_nascimento"),
})

# ── Parte 6 — Informações Sobre Seu Histórico Matrimonial ───────────────────
MAPPING_RULES.update({
    # ATENÇÃO: ordem real dos widgets é 3,1,4,2,5,7 (NÃO sequencial) — confirmado
    # via /AP. Não reordene por número sem reconferir.
    "Pt6Line1_MaritalStatus": [
        cb("estado_civil", "divorciado"),  # código 3 (índice 0)
        cb("estado_civil", "solteiro"),    # código 1 (índice 1)
        cb("estado_civil", "viuvo"),       # código 4 (índice 2)
        cb("estado_civil", "casado"),      # código 2 (índice 3)
        cb("estado_civil", "anulado"),     # código 5 (índice 4)
        cb("estado_civil", "separado_legalmente"),  # código 7 (índice 5)
    ],
    "Pt5Line2_YNNA": [cb("conjuge_militar", "nao"), cb("conjuge_militar", "sim"), cb("conjuge_militar", "na")],  # real_on N,Y,A
    "Pt6Line3_TimesMarried": txt("numero_casamentos"),
    "Pt6Line4_FamilyName": txt("conjuge_sobrenome"),
    "Pt6Line4_GivenName": txt("conjuge_nome"),
    "Pt6Line4_MiddleName": txt("conjuge_meio"),
    "Pt6Line5_AlienNumber": txt("conjuge_alien_number"),
    "Pt1Line2_DOB": txt("conjuge_data_nascimento"),
    "Pt6Line7_Country": txt("conjuge_pais_nascimento"),
    "Part6Line8_StreetName": txt("conjuge_end_rua"),
    "P6Line8_Unit": [cb("conjuge_end_tipo_unidade", "apt"), cb("conjuge_end_tipo_unidade", "ste"), cb("conjuge_end_tipo_unidade", "flr")],
    "P6Line8_Number": txt("conjuge_end_num_unidade"),
    "P6Line8_City": txt("conjuge_end_cidade"),
    "P6Line8_State": txt("conjuge_end_estado"),
    "P6Line8_ZipCode": txt("conjuge_end_cep"),
    "P6Line8_PostalCode": txt("conjuge_end_codigo_postal"),
    "P6Line8_Province": txt("conjuge_end_provincia"),
    "P6Line8_Country": txt("conjuge_end_pais"),
    "Pt6Line10_CityTownOfBirth": txt("casamento_cidade"),
    "Pt6Line10_State": txt("casamento_estado_provincia"),
    "Pt6Line10_Country": txt("casamento_pais"),
    "Pt6Line11_YN": [cb("conjuge_aplicando_junto", "nao"), cb("conjuge_aplicando_junto", "sim")],  # real_on N,Y
    "Pt6Line12_FamilyName": txt("ex_conjuge_sobrenome"),
    "Pt6Line12_GivenName": txt("ex_conjuge_nome"),
    "Pt6Line12_MiddleName": txt("ex_conjuge_meio"),
    "Pt6Line16_DateofBirth": txt("ex_conjuge_data_nascimento"),
    "Pt6Line15_Country": txt("ex_conjuge_pais_nascimento"),
    "Pt6Line14_Country": txt("ex_conjuge_pais_cidadania"),
    "Pt6Line18_CityTownOfBirth": txt("ex_casamento_cidade"),
    "Pt6Line18_State": txt("ex_casamento_estado_provincia"),
    "Pt6Line18_Country": txt("ex_casamento_pais"),
    # ATENÇÃO: ordem real dos widgets é 3,1,4,2 (NÃO sequencial) — confirmado via /AP.
    "Pt6Line19_MaritalStatus": [
        cb("ex_casamento_como_terminou", "conjuge_falecido"),  # código 3 (índice 0)
        cb("ex_casamento_como_terminou", "anulado"),           # código 1 (índice 1)
        cb("ex_casamento_como_terminou", "outro"),             # código 4 (índice 2)
        cb("ex_casamento_como_terminou", "divorciado"),        # código 2 (índice 3)
    ],
    "Pt6Line19_HowMarriageEndedOther": txt("ex_casamento_outro_explicacao"),
})

# ── Parte 7 — Informações Sobre Seus Filhos ─────────────────────────────────
MAPPING_RULES.update({
    "Pt6Line1_TotalChildren": txt("total_filhos"),
    "Pt7Line2_FamilyName": txt("filho1_sobrenome"),
    "Pt7Line2_GivenName": txt("filho1_nome"),
    "Pt7Line2_MiddleName": txt("filho1_meio"),
    "Pt7Line2_AlienNumber": txt("filho1_alien_number"),
    "Pt7Line2_DateofBirth": txt("filho1_data_nascimento"),
    "Pt7Line2_Country": txt("filho1_pais_nascimento"),
    "Pt7Line2_YN": [cb("filho1_aplicando_separado", "nao"), cb("filho1_aplicando_separado", "sim")],  # real_on N,Y
    "Pt7Line2_Relationship": txt("filho1_relacao"),
    "Pt7Line3_FamilyName": txt("filho2_sobrenome"),
    "Pt7Line3_GivenName": txt("filho2_nome"),
    "Pt7Line3_MiddleName": txt("filho2_meio"),
    "Pt7Line3_AlienNumber": txt("filho2_alien_number"),
    "Pt7Line3_DateofBirth": txt("filho2_data_nascimento"),
    "Pt7Line3_Country": txt("filho2_pais_nascimento"),
    "Pt7Line3_YN": [cb("filho2_aplicando_separado", "nao"), cb("filho2_aplicando_separado", "sim")],  # real_on N,Y
    "Pt7Line3_Relationship": txt("filho2_relacao"),
})

# ── Parte 8 — Informações Biográficas (nome interno diz "Pt7") ─────────────
MAPPING_RULES.update({
    "Pt7Line1_Ethnicity": [cb("etnia", "hispanico"), cb("etnia", "nao_hispanico")],  # real_on H,N
    "Pt7Line2_Race": [cb("raca_asiatico", "sim"), cb("raca_branco", "sim"), cb("raca_negro", "sim"),
                       cb("raca_indigena_americano", "sim"), cb("raca_havaiano_pacifico", "sim")],  # multi-select, AS/WH/BL/AI/HW
    "Pt7Line3_HeightFeet": txt("altura_pes"),
    "Pt7Line3_HeightInches": txt("altura_polegadas"),
    "Pt7Line4_Weight1": txt("peso_centena"),
    "Pt7Line4_Weight2": txt("peso_dezena"),
    "Pt7Line4_Weight3": txt("peso_unidade"),
    "Pt7Line5_Eyecolor": [
        cb("cor_olhos", "azul"), cb("cor_olhos", "preto"), cb("cor_olhos", "castanho"),
        cb("cor_olhos", "cinza"), cb("cor_olhos", "verde"), cb("cor_olhos", "avela"),
        cb("cor_olhos", "marrom_avermelhado"), cb("cor_olhos", "rosa"), cb("cor_olhos", "outro"),
    ],  # real_on BU,BL,BN,GR,GN,HA,MA,PN,UN
    "Pt7Line6_Haircolor": [
        cb("cor_cabelo", "careca"), cb("cor_cabelo", "preto"), cb("cor_cabelo", "loiro"),
        cb("cor_cabelo", "castanho"), cb("cor_cabelo", "grisalho"), cb("cor_cabelo", "ruivo"),
        cb("cor_cabelo", "arenoso"), cb("cor_cabelo", "branco"), cb("cor_cabelo", "outro"),
    ],  # real_on NH,BL,BN,BR,GR,RD,SA,WH,OT
})

# ── Parte 9 — Elegibilidade Geral e Motivos de Inadmissibilidade ───────────
# (nomes internos "Pt8"/"Pt9" misturados — o sufixo Line<N> bate com o item real)
MAPPING_RULES.update({
    # NOTA CRÍTICA sobre esta seção inteira (itens 1-55): o sufixo numérico do nome
    # do campo NÃO é confiável aqui — descobrimos, comparando com a posição real
    # (/Rect, página+Y) de cada widget, que a página 14 (itens 10-22) tem campos
    # cujo nome não bate com o item real (ex.: "Pt8Line18_YesNo" É o item 14, não
    # o item 18). Cada linha abaixo foi verificada por posição visual (topo->baixo
    # da página), não pelo nome do campo — não "corrija" achando que o nome bate
    # com o número do item sem antes conferir a posição de novo.
    "Pt8Line1_YesNo": [cb("membro_organizacao", "nao"), cb("membro_organizacao", "sim")],  # item1; real_on N,Y
    "Pt9Line2_Organization1": txt("org1_nome"),
    "Pt9Line3_CityTownOfBirth": txt("org1_cidade"),
    "Pt9Line3_State": txt("org1_estado_provincia"),
    "Pt9Line3_Country": txt("org1_pais"),
    "Pt9Line4_FamilyName": txt("org1_natureza"),
    "Pt9Line4_Involvement": txt("org1_envolvimento"),
    "Pt9Line5_DateFrom": txt("org1_desde"),
    "Pt9Line5_DateTo": txt("org1_ate"),
    "Pt9Line6_Organization2": txt("org2_nome"),
    "Pt9Line7_CityTownOfBirth": txt("org2_cidade"),
    "Pt9Line7_State": txt("org2_estado_provincia"),
    "Pt9Line7_Country": txt("org2_pais"),
    "Pt9Line8_FamilyName": txt("org2_natureza"),
    "Pt9Line8_Involvement": txt("org2_envolvimento"),
    "Pt9Line9_DateFrom": txt("org2_desde"),
    "Pt9Line9_DateTo": txt("org2_ate"),
    # Página 14 (y descendente = ordem real dos itens 10-22; nome do campo NÃO
    # corresponde ao item aqui, confirmado por posição):
    "Pt9Line10_YesNo": [cb("negado_admissao", "nao"), cb("negado_admissao", "sim")],  # item10 (y499); real_on N,Y
    "Pt9Line11_YesNo": [cb("negado_visto", "sim"), cb("negado_visto", "nao")],  # item11 (y481); real_on Y,N
    "Pt9Line12_YesNo": [cb("trabalhou_sem_autorizacao", "sim"), cb("trabalhou_sem_autorizacao", "nao")],  # item12 (y463); real_on Y,N
    "Pt8Line13_YesNo": [cb("violou_status_nao_imigrante", "nao"), cb("violou_status_nao_imigrante", "sim")],  # item13 (y445); real_on N,Y
    "Pt8Line18_YesNo": [cb("em_processo_remocao", "sim"), cb("em_processo_remocao", "nao")],  # item14 (y427, nome diz 18!); real_on Y,N
    "Pt8Line19_YesNo": [cb("ordem_final_exclusao_remocao", "nao"), cb("ordem_final_exclusao_remocao", "sim")],  # item15 (y397, nome diz 19!); real_on N,Y
    "Pt8Line20_YesNo": [cb("ordem_remocao_reinstada", "sim"), cb("ordem_remocao_reinstada", "nao")],  # item16 (y379, nome diz 20!); real_on Y,N
    "Pt8Line17_YesNo": [cb("recebeu_partida_voluntaria_nao_cumpriu", "sim"), cb("recebeu_partida_voluntaria_nao_cumpriu", "nao")],  # item17 (y361); real_on Y,N
    "Pt8Line23_YesNo": [cb("pediu_alivio_remocao", "nao"), cb("pediu_alivio_remocao", "sim")],  # item18 (y331, nome diz 23!); real_on N,Y
    "Pt8Line24a_YesNo": [cb("j_visitante_intercambio_2anos", "sim"), cb("j_visitante_intercambio_2anos", "nao")],  # item19 (y313, nome diz 24a!); real_on Y,N
    "Pt8Line24b_YesNo": [cb("cumpriu_residencia_estrangeira", "nao"), cb("cumpriu_residencia_estrangeira", "sim")],  # item20 (y283, nome diz 24b!); real_on N,Y
    "Pt8Line24c_YesNo": [cb("obteve_waiver_residencia_estrangeira", "sim"), cb("obteve_waiver_residencia_estrangeira", "nao")],  # item21 (y265, nome diz 24c!); real_on Y,N
    "Pt8Line22_YesNo": [cb("preso_citado_detido", "sim"), cb("preso_citado_detido", "nao")],  # item22 (y91, isolado — início de "Criminal Acts"); real_on Y,N
    # Página 15 (itens 23-37 — aqui o sufixo do nome bate com o item, confirmado por posição):
    "Pt9Line23_YesNo": [cb("cometeu_crime", "nao"), cb("cometeu_crime", "sim")],  # item23 (y685); real_on N,Y
    "Pt9Line24_YesNo": [cb("condenado_crime", "sim"), cb("condenado_crime", "nao")],  # item24 (y655); real_on Y,N
    "Pt8Line25_YesNo": [cb("condicoes_restritas_liberdade", "nao"), cb("condicoes_restritas_liberdade", "sim")],  # item25; real_on N,Y
    "Pt8Line26_YesNo": [cb("violou_lei_substancia_controlada", "nao"), cb("violou_lei_substancia_controlada", "sim")],  # item26; real_on N,Y
    "Pt8Line27_YesNo": [cb("traficou_substancia_controlada", "nao"), cb("traficou_substancia_controlada", "sim")],  # item27; real_on N,Y
    "Pt8Line28_YesNo": [cb("conjuge_filho_traficante", "nao"), cb("conjuge_filho_traficante", "sim")],  # item28; real_on N,Y
    "Pt8Line29_YesNo": [cb("sabia_beneficio_trafico", "nao"), cb("sabia_beneficio_trafico", "sim")],  # item29; real_on N,Y
    "Pt8Line30_YesNo": [cb("prostituicao", "nao"), cb("prostituicao", "sim")],  # item30; real_on N,Y
    "Pt8Line31_YesNo": [cb("procurou_prostitutas", "sim"), cb("procurou_prostitutas", "nao")],  # item31; real_on Y,N
    "Pt8Line32_YesNo": [cb("recebeu_proventos_prostituicao", "sim"), cb("recebeu_proventos_prostituicao", "nao")],  # item32; real_on Y,N
    "Pt8Line33_YesNo": [cb("intencao_vicio_comercializado", "sim"), cb("intencao_vicio_comercializado", "nao")],  # item33; real_on Y,N
    "Pt8Line34_YesNo": [cb("exerceu_imunidade_diplomatica", "nao"), cb("exerceu_imunidade_diplomatica", "sim")],  # item34; real_on N,Y
    "Pt8Line35a_YesNo": [cb("funcionario_governo_estrangeiro", "sim"), cb("funcionario_governo_estrangeiro", "nao")],  # item35a; real_on Y,N
    "Pt8Line35b_YesNo": [cb("violou_liberdade_religiosa", "nao"), cb("violou_liberdade_religiosa", "sim")],  # item35b; real_on N,Y
    "Pt8Line36_YesNo": [cb("trafico_sexual_forca_coercao", "nao"), cb("trafico_sexual_forca_coercao", "sim")],  # item36; real_on N,Y
    "Pt8Line37_YesNo": [cb("trafico_servidao_involuntaria", "nao"), cb("trafico_servidao_involuntaria", "sim")],  # item37 (y79, isolado); real_on N,Y
    # Página 16 (itens 38-45 — sufixo bate com o item):
    "Pt8Line38_YesNo": [cb("ajudou_trafico_pessoas", "sim"), cb("ajudou_trafico_pessoas", "nao")],  # item38; real_on Y,N
    "Pt9Line39_YesNo": [cb("conjuge_filho_trafico_pessoas", "nao"), cb("conjuge_filho_trafico_pessoas", "sim")],  # item39; real_on N,Y
    "Pt8Line40_YesNo": [cb("sabia_beneficio_trafico_pessoas", "nao"), cb("sabia_beneficio_trafico_pessoas", "sim")],  # item40; real_on N,Y
    "Pt8Line41_YesNo": [cb("lavagem_dinheiro", "sim"), cb("lavagem_dinheiro", "nao")],  # item41; real_on Y,N
    "a_YesNo": [cb("espionagem_sabotagem", "sim"), cb("espionagem_sabotagem", "nao")],  # item 42.a; real_on Y,N
    "b_YesNo": [cb("violar_lei_exportacao", "nao"), cb("violar_lei_exportacao", "sim")],  # item 42.b; real_on N,Y
    "Pt8Line42c_YesNo": [cb("derrubar_governo_eua", "nao"), cb("derrubar_governo_eua", "sim")],  # item42c; real_on N,Y
    "Pt8Line42d_YesNo": [cb("outra_atividade_ilegal", "sim"), cb("outra_atividade_ilegal", "nao")],  # item42d; real_on Y,N
    "Pt8Line43a_YesNo": [cb("treinamento_armas", "nao"), cb("treinamento_armas", "sim")],  # item43a; real_on N,Y
    "Pt8Line43b_YesNo": [cb("sequestro_assassinato_sabotagem", "sim"), cb("sequestro_assassinato_sabotagem", "nao")],  # item43b; real_on Y,N
    "Pt8Line43c_YesNo": [cb("usou_arma_explosivo", "sim"), cb("usou_arma_explosivo", "nao")],  # item43c; real_on Y,N
    "Pt8Line43d_YesNo": [cb("ameacou_conspirou_planejou", "sim"), cb("ameacou_conspirou_planejou", "nao")],  # item43d; real_on Y,N
    "Pt8Line43e_YesNo": [cb("incitou_causar_morte", "sim"), cb("incitou_causar_morte", "nao")],  # item43e; real_on Y,N
    "Pt8Line43fYesNo": [cb("apoio_individuo_grupo", "sim"), cb("apoio_individuo_grupo", "nao")],  # item43f; real_on Y,N
    "Pt8Line43g_YesNo": [cb("participou_grupo_armado", "sim"), cb("participou_grupo_armado", "nao")],  # item43g; real_on Y,N
    "Pt8Line43h_YesNo": [cb("recrutou_membros_grupo", "nao"), cb("recrutou_membros_grupo", "sim")],  # item43h; real_on N,Y
    "Pt8Line43i_YesNo": [cb("apoio_atividades_grupo", "nao"), cb("apoio_atividades_grupo", "sim")],  # item43i; real_on N,Y
    "Pt8Line44_YesNo": [cb("intencao_atividades_43b_43e", "sim"), cb("intencao_atividades_43b_43e", "nao")],  # item44; real_on Y,N
    "Pt8Line45_YesNo": [cb("intencao_atividade_perigo_seguranca", "nao"), cb("intencao_atividade_perigo_seguranca", "sim")],  # item45; real_on N,Y
    "Pt8Line46_YesNo": [cb("conjuge_filho_43b_43i", "sim"), cb("conjuge_filho_43b_43i", "nao")],  # item46; real_on Y,N
    "Pt8Line47_YesNo": [cb("vendeu_armas", "nao"), cb("vendeu_armas", "sim")],  # item47; real_on N,Y
    "Pt8Line48_YesNo": [cb("trabalhou_prisao_detencao", "nao"), cb("trabalhou_prisao_detencao", "sim")],  # item48; real_on N,Y
    "Pt8Line49_YesNo": [cb("servico_militar_policial", "sim"), cb("servico_militar_policial", "nao")],  # item49; real_on Y,N
    "Pt8Line50_YesNo": [cb("grupo_arma_contra_pessoa", "nao"), cb("grupo_arma_contra_pessoa", "sim")],  # item50; real_on N,Y
    "Pt8Line51_YesNo": [cb("grupo_armado_paramilitar", "sim"), cb("grupo_armado_paramilitar", "nao")],  # item51; real_on Y,N
    "Pt8Line52_YesNo": [cb("partido_comunista_totalitario", "nao"), cb("partido_comunista_totalitario", "sim")],  # item52; real_on N,Y
    "Pt8Line53a_YesNo": [cb("tortura", "sim"), cb("tortura", "nao")],  # item53a; real_on Y,N
    "Pt8Line53b_YesNo": [cb("genocidio", "sim"), cb("genocidio", "nao")],  # item53b; real_on Y,N
    "Pt8Line53c_YesNo": [cb("matar_tentar_matar", "sim"), cb("matar_tentar_matar", "nao")],  # item53c; real_on Y,N
    "Pt8Line53d_YesNo": [cb("ferir_gravemente", "nao"), cb("ferir_gravemente", "sim")],  # item53d; real_on N,Y
    "Pt8Line54_YesNo": [cb("recrutou_menor15_hostilidades", "nao"), cb("recrutou_menor15_hostilidades", "sim")],  # item54; real_on N,Y
    "Pt8Line55_YesNo": [cb("usou_menor15_hostilidades", "sim"), cb("usou_menor15_hostilidades", "nao")],  # item55; real_on Y,N
    # Public Charge (56-66)
    "Pt9Line56_CB": [
        cb("public_charge_isento_categoria", "afegao_iraquiano"),      # 0
        cb("public_charge_isento_categoria", "refugiado"),             # 1 (tooltip corrompido no XFA — inferido por eliminacao, ver nota no topo do arquivo)
        cb("public_charge_isento_categoria", "vitima_crime_u"),        # 2
        cb("public_charge_isento_categoria", "asilado"),               # 3
        cb("public_charge_isento_categoria", "u_status_valido"),       # 4
        cb("public_charge_isento_categoria", "vawa"),                  # 5
        cb("public_charge_isento_categoria", "imigrante_juvenil"),     # 6
        cb("public_charge_isento_categoria", "cuban_adjustment"),      # 7
        cb("public_charge_isento_categoria", "haitian_fairness_vitima"),  # 8
        cb("public_charge_isento_categoria", "trafico_t"),             # 9
        cb("public_charge_isento_categoria", "cuban_adjustment_vitima"),  # 10
        cb("public_charge_isento_categoria", "haitian_fairness"),      # 11
        cb("public_charge_isento_categoria", "t_status_pendente_valido"),  # 12
        cb("public_charge_isento_categoria", "registry_1972"),         # 13
        cb("public_charge_isento_categoria", "nacara"),                # 14
        cb("public_charge_isento_categoria", "amerasian"),             # 15
        cb("public_charge_isento_categoria", "polaco_hungaro_parolee"),# 16
        cb("public_charge_isento_categoria", "cuban_haitian_entrant"), # 17
        cb("public_charge_isento_categoria", "lautenberg_parolee"),    # 18
        cb("public_charge_isento_categoria", "vietnam_camboja_laos"),  # 19
        cb("public_charge_isento_categoria", "indigena_americano_canada"),  # 20
        cb("public_charge_isento_categoria", "liberian_ndaa"),         # 21
        cb("public_charge_isento_categoria", "ndaa_militar"),          # 22
        cb("public_charge_isento_categoria", "nenhuma_completar_57_66"),  # 23
        cb("public_charge_isento_categoria", "sirio"),                 # 24
    ],
    "Pt9Line57_HouseholdSize": txt("public_charge_tamanho_domicilio"),
    "Pt9Line53_CB": [cb("public_charge_renda_anual", "0_27000"), cb("public_charge_renda_anual", "27001_52000"),
                       cb("public_charge_renda_anual", "52001_85000"), cb("public_charge_renda_anual", "85001_141000"),
                       cb("public_charge_renda_anual", "acima_141000")],  # A-E
    "Pt9Line59_CB": [cb("public_charge_ativos", "0_18400"), cb("public_charge_ativos", "18401_136000"),
                       cb("public_charge_ativos", "136001_321400"), cb("public_charge_ativos", "321401_707100"),
                       cb("public_charge_ativos", "acima_707100")],  # A-E
    "Pt9Line60_CB": [cb("public_charge_passivos", "0"), cb("public_charge_passivos", "1_10100"),
                       cb("public_charge_passivos", "10101_57700"), cb("public_charge_passivos", "57701_186800"),
                       cb("public_charge_passivos", "acima_186800")],  # A-E
    "Pt9Line61_diploma": txt("public_charge_grau_escolar_detalhe"),
    "Pt9Line61_CB": [
        cb("public_charge_escolaridade", "menos_ensino_medio"),      # C
        cb("public_charge_escolaridade", "college_sem_grau"),         # 1
        cb("public_charge_escolaridade", "ensino_medio_ged"),         # 2
        cb("public_charge_escolaridade", "associate"),                # 3
        cb("public_charge_escolaridade", "mestrado"),                 # 4
        cb("public_charge_escolaridade", "profissional"),             # 5
        cb("public_charge_escolaridade", "doutorado"),                # 6
        cb("public_charge_escolaridade", "bacharelado"),              # 7
    ],
    "Pt9Line63_YesNo": [cb("recebeu_beneficio_assistencia", "sim"), cb("recebeu_beneficio_assistencia", "nao")],  # real_on Y,N
    "Pt9Line64_YesNo": [cb("recebeu_institucionalizacao", "sim"), cb("recebeu_institucionalizacao", "nao")],  # real_on Y,N
    "TextField1": txt("beneficio_1_nome"), "TextField2": txt("beneficio_1_data_inicio"),
    "TextField3": txt("beneficio_1_data_fim"), "TextField4": txt("beneficio_1_valor"),
    "TextField5": txt("beneficio_2_nome"), "TextField6": txt("beneficio_2_data_inicio"),
    "TextField7": txt("beneficio_2_data_fim"), "TextField8": txt("beneficio_2_valor"),
    "Pt9Line65_Row1_YesNo": [cb("beneficio_1_categoria_isenta", "sim"), cb("beneficio_1_categoria_isenta", "nao")],
    "Pt9Line65_Row2_YesNo": [cb("beneficio_2_categoria_isenta", "sim"), cb("beneficio_2_categoria_isenta", "nao")],
    "Pt9Line65_Row3_YesNo": [cb("beneficio_3_categoria_isenta", "sim"), cb("beneficio_3_categoria_isenta", "nao")],
    "Pt9Line65_Row4_YesNo": [cb("beneficio_4_categoria_isenta", "sim"), cb("beneficio_4_categoria_isenta", "nao")],
    "Pt8Line68c_Column1Row1": txt("institucionalizacao_1_nome"), "Pt8Line68c_Column2Row1": txt("institucionalizacao_1_data_inicio"),
    "Pt8Line68c_Column3Row1": txt("institucionalizacao_1_data_fim"), "Pt8Line68c_Column4Row1": txt("institucionalizacao_1_motivo"),
    "Pt8Line68c_Column1Row2": txt("institucionalizacao_2_nome"), "Pt8Line68c_Column2Row2": txt("institucionalizacao_2_data_inicio"),
    "Pt8Line68c_Column3Row2": txt("institucionalizacao_2_data_fim"), "Pt8Line68c_Column4Row2": txt("institucionalizacao_2_motivo"),
    "Pt8Line68c_Column1Row3": txt("institucionalizacao_3_nome"), "Pt8Line68c_Column2Row3": txt("institucionalizacao_3_data_inicio"),
    "Pt8Line68c_Column3Row3": txt("institucionalizacao_3_data_fim"), "Pt8Line68c_Column4Row3": txt("institucionalizacao_3_motivo"),
    "Pt8Line68c_Column1Row4": txt("institucionalizacao_4_nome"), "Pt8Line68c_Column2Row4": txt("institucionalizacao_4_data_inicio"),
    "Pt8Line68c_Column3Row4": txt("institucionalizacao_4_data_fim"), "Pt8Line68c_Column4Row4": txt("institucionalizacao_4_motivo"),
    "Pt8Line68d_Column1Row1": ignore(), "Pt8Line68d_Column2Row1": ignore(),
    "Pt8Line68d_Column3Row1": ignore(), "Pt8Line68d_Column4Row1": ignore(),
    "Pt8Line68d_Column1Row2": ignore(), "Pt8Line68d_Column2Row2": ignore(),
    "Pt8Line68d_Column3Row2": ignore(), "Pt8Line68d_Column4Row2": ignore(),
    "Pt8Line68d_Column1Row3": ignore(), "Pt8Line68d_Column2Row3": ignore(),
    "Pt8Line68d_Column3Row3": ignore(), "Pt8Line68d_Column4Row3": ignore(),
    "Pt8Line68d_Column1Row4": ignore(), "Pt8Line68d_Column2Row4": ignore(),
    "Pt8Line68d_Column3Row4": ignore(), "Pt8Line68d_Column4Row4": ignore(),
    "Pt9Line66_Row1_YesNo": [cb("institucionalizacao_1_categoria_isenta", "sim"), cb("institucionalizacao_1_categoria_isenta", "nao")],
    "Pt9Line66_Row2_YesNo": [cb("institucionalizacao_2_categoria_isenta", "sim"), cb("institucionalizacao_2_categoria_isenta", "nao")],
    "Pt9Line66_Row3_YesNo": [cb("institucionalizacao_3_categoria_isenta", "sim"), cb("institucionalizacao_3_categoria_isenta", "nao")],
    "Pt9Line66_Row4_YesNo": [cb("institucionalizacao_4_categoria_isenta", "sim"), cb("institucionalizacao_4_categoria_isenta", "nao")],
    "Pt9Line67_YesNo": [cb("faltou_processo_remocao", "nao"), cb("faltou_processo_remocao", "sim")],  # real_on N,Y
    "Pt9Line68_YesNo": [cb("documento_fraudulento_imigracao", "sim"), cb("documento_fraudulento_imigracao", "nao")],  # real_on Y,N
    "Pt9Line69_YesNo": [cb("mentiu_documentacao_visto", "nao"), cb("mentiu_documentacao_visto", "sim")],  # real_on N,Y
    "Pt9Line70_YesNo": [cb("ordem_civil_penalidade_274c", "sim"), cb("ordem_civil_penalidade_274c", "nao")],  # real_on Y,N
    "Pt9Line71_YesNo": [cb("alegou_cidadania_falsa", "nao"), cb("alegou_cidadania_falsa", "sim")],  # real_on N,Y
    "Pt9Line72_YesNo": [cb("polizao_navio_aeronave", "sim"), cb("polizao_navio_aeronave", "nao")],  # real_on Y,N
    "Pt9Line73_YesNo": [cb("ajudou_contrabando_estrangeiro", "nao"), cb("ajudou_contrabando_estrangeiro", "sim")],  # real_on N,Y
    "Pt9Line74_YesNo": [cb("excluido_deportado_removido", "nao"), cb("excluido_deportado_removido", "sim")],  # real_on N,Y
    "Pt9Line75_YesNo": [cb("entrou_sem_inspecao", "sim"), cb("entrou_sem_inspecao", "nao")],  # real_on Y,N
    "Pt9Line76_YesNo": [cb("presenca_ilegal_desde_1997", "nao"), cb("presenca_ilegal_desde_1997", "sim")],  # real_on N,Y
    "Pt9Line77_YesNo": [cb("trafico_severo_razao_presenca_ilegal", "sim"), cb("trafico_severo_razao_presenca_ilegal", "nao")],  # real_on Y,N
    "Pt9Line78a_YesNo": [cb("reentrada_apos_presenca_ilegal_1ano", "nao"), cb("reentrada_apos_presenca_ilegal_1ano", "sim")],  # real_on N,Y
    "Pt9Line78b_YesNo": [cb("reentrada_apos_deportacao", "sim"), cb("reentrada_apos_deportacao", "nao")],  # real_on Y,N
    "Pt9Line79_YesNo": [cb("acompanha_inadmissivel_medico", "sim"), cb("acompanha_inadmissivel_medico", "nao")],  # real_on Y,N
    "Pt9Line80_YesNo": [cb("planeja_poligamia", "nao"), cb("planeja_poligamia", "sim")],  # real_on N,Y
    "Pt9Line81_YesNo": [cb("reteve_custodia_filho_cidadao", "sim"), cb("reteve_custodia_filho_cidadao", "nao")],  # real_on Y,N
    "Pt9Line82_YesNo": [cb("votou_ilegalmente", "nao"), cb("votou_ilegalmente", "sim")],  # real_on N,Y
    "Pt9Line83_YesNo": [cb("renunciou_cidadania_evitar_impostos", "sim"), cb("renunciou_cidadania_evitar_impostos", "nao")],  # real_on Y,N
    "Pt9Line84a_YesNo": [cb("pediu_isencao_treinamento_militar", "nao"), cb("pediu_isencao_treinamento_militar", "sim")],  # real_on N,Y
    "Pt9Line84b_YesNo": [cb("dispensado_treinamento_militar", "nao"), cb("dispensado_treinamento_militar", "sim")],  # real_on N,Y
    "Pt9Line84c_YesNo": [cb("condenado_desercao_forcas_armadas", "nao"), cb("condenado_desercao_forcas_armadas", "sim")],  # real_on N,Y
    "Pt9Line85_YesNo": [cb("deixou_eua_evitar_servico_militar", "nao"), cb("deixou_eua_evitar_servico_militar", "sim")],  # real_on N,Y
    "Pt9Line86_Nationality": txt("nacionalidade_status_antes_de_sair"),
})

# ── Parte 10 — Contato, Certificação e Assinatura do Requerente ────────────
MAPPING_RULES.update({
    "Pt3Line3_DaytimePhoneNumber1": txt("telefone"),
    "Pt3Line4_MobileNumber1": txt("celular"),
    "Pt3Line5_Email": txt("email"),
    "Pt3Line7a_Signature": ignore(),
    "Pt3Line7b_DateofSignature": txt("data_assinatura"),
})

# ── Parte 11 — Intérprete ───────────────────────────────────────────────────
MAPPING_RULES.update({
    "Pt11Line1a_FamilyName": txt("int_sobrenome"),
    "Pt11Line1b_GivenName": txt("int_nome"),
    "Pt11Line2_OrgName": txt("int_organizacao"),
    "P3_Line4_DaytimeTelePhoneNumber": txt("int_telefone"),
    "P3_Line5_MobileTelePhoneNumber": txt("int_celular"),
    "P3_Line6_Email": txt("int_email"),
    "Part11_NameofLanguage": txt("int_idioma"),
    "P12_SignatureApplicant": ignore(),
    "P13_DateofSignature": txt("int_data_assinatura"),
})

# ── Parte 12 — Preparador(a) ─────────────────────────────────────────────
MAPPING_RULES.update({
    "Pt12Line1_PreparerFamilyName": txt("prep_sobrenome"),
    "Pt12Line1a_PreparerGivenName": txt("prep_nome"),
    "Pt12Line2_BusinessName": txt("prep_organizacao"),
    "Pt12Line3_PreparerDaytimePhoneNumber1": txt("prep_telefone"),
    "Pt12Line4_PreparerMobileNumber": txt("prep_celular"),
    "Pt12Line5_PreparerEmail": txt("prep_email"),
    "P12Line6_SignaturePreparer": ignore(),
    "P12Line6a_DateofSignature": txt("prep_data_assinatura"),
})

# ── Parte 13 — Assinatura na Entrevista (uso do Oficial USCIS) — ignorado ──
MAPPING_RULES.update({
    "Pt13_USCISSignature": ignore(),
    "Pt13_USCISOfficer": ignore(),
    "Pt13_ApplicantSignature": ignore(),
    "Pt13_DateofSignature": ignore(),
    "Pt13_Corrections1": ignore(),
    "Pt13_Corrections2": ignore(),
    "Pt13_Pages1": ignore(),
    "Pt13_Pages2": ignore(),
})

# ── Parte 14 — Informações Adicionais (espaço extra) — ignorado ────────────
MAPPING_RULES.update({
    "Pt9Line3a_PageNumber": ignore(),
    "Pt9Line3b_PartNumber": ignore(),
    "Pt9Line3c_ItemNumber": ignore(),
    "P14_Line2_AdditionalInfo": ignore(),
    "P14_Line3_AdditionalInfo": ignore(),
    "P14_Line4_AdditionalInfo": ignore(),
    "P14_Line5_AdditionalInfo": ignore(),
})


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
                # sobrou instancia sem regra (ex.: duplicata inesperada) -> ignora
                result_fields.append({"pdf_field": pdf_field, "type": ftype, "question_id": "_ignore"})
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

        entry = {"pdf_field": pdf_field, "type": rule.get("type", ftype), "question_id": rule["question_id"]}
        if "check_if_answer" in rule:
            entry["check_if_answer"] = rule["check_if_answer"]
        result_fields.append(entry)

    if unmapped:
        print(f"AVISO: {len(unmapped)} campo(s) sem regra de mapeamento:")
        for u in unmapped:
            print(f"  - {u}")
    else:
        print("Todos os campos cobertos.")

    out_data = {"form": "I-485", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/i-485.skeleton.json",
                base_dir / "data/mappings/i-485.json")
