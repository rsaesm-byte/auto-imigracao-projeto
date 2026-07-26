"""
build_mapping_n400.py — Aplica os question_id ao esqueleto de mapeamento do N-400.

Uso:
    python scripts/build_mapping_n400.py
    # Sobrescreve data/mappings/n-400.json com question_id preenchidos.

Peculiaridades confirmadas neste formulário (via /AP + toolTips XFA + texto das páginas):
    - Nomes internos de campo são amplamente enganosos neste formulário — MUITO mais
      que nos formulários anteriores. Exemplos confirmados via toolTip/texto da página:
        - "P2_Line10_CountryOfBirth" é na verdade o Item 8 (País de Nascimento);
          "P2_Line11_CountryOfNationality" é o Item 9 (País de Nacionalidade);
          "P2_Line8_DateOfBirth" é o Item 6; "P2_Line6_USCISELISAcctNumber" é o Item 4;
          "P2_Line9_DateBecamePermanentResident" é o Item 7. Os números nos nomes
          não batem com os números reais dos itens — só o toolTip resolve.
        - "P10_Line5_Citizen" (Y/N) não é sobre cidadania — é o Item 4.d (endereço do
          cônjuge é igual ao seu?). "P10_Line1_Citizen" (outro campo, Parte 10 de
          redução de taxa) também usa o nome genérico "Citizen" para renda familiar
          ≤400% do nível de pobreza — mesmo nome interno reusado para DUAS perguntas
          Y/N completamente diferentes em partes diferentes do formulário.
        - "P10_Line4g_Employer" é texto, mas o toolTip confirma Item 7 (quantas vezes
          o cônjuge atual já se casou) — não é nome de empregador.
        - "TextField1" é o Item 8 (nome do empregador atual do cônjuge).
        - "P9_NobilityTitles" é campo de texto livre do Item 30.b (listar títulos de
          nobreza a renunciar), não tem relação com o nome do campo.
        - "P12_6a/6b/6c" são na verdade os Itens 6.a/6.b/6.c (armas/sequestro/ameaça),
          não "Parte 12". "P11_Line17A/B/C", "P11_7d", "P11_Line26d" são Itens
          17.a/17.b/17.c/7.d/26.d — o prefixo "P11"/"P12" no nome interno NÃO
          corresponde à parte real onde o campo aparece; a Parte real (Parte 9.
          Informações Adicionais) foi confirmada via texto da página.
    - Bug de extração NOVO (não visto em formulários anteriores): alguns nomes de
      campo têm um PONTO LITERAL escapado com barra invertida (ex.:
      "P9_Line7\\.b\\.[0]", "Line12\\.c_Checkbox[0]") porque o nome real do campo
      no PDF contém um ponto (referente à numeração "7.b", "12.c"). O algoritmo
      genérico `short = pdf_field.split(".")[-1]` quebra essas strings no ponto
      escapado, perdendo o prefixo. Corrigido aqui com regex que só quebra em "."
      NÃO precedido por "\\" (veja `_split_qualified_name`).
    - Grupo de checkbox "P7_Line2_Race" (Parte 4, Item 2): dois widgets DIFERENTES
      (índice 1 = Native Hawaiian/Pacific Islander, índice 3 = Asian) usam o MESMO
      valor real "/A" no /AP — colisão de on-value nunca vista em formulário
      anterior. Resolvido por posição/ordem de leitura da página (Indian, Hawaiian,
      Black, Asian, White), não pelo valor real (que é ambíguo entre os dois).
      Isso não corrompe o preenchimento porque cada widget é endereçado pelo seu
      próprio pdf_field (índice), não pelo valor "on" em si.
    - "P7_EmployerName1/2/3", "P7_City1/2/3", "P7_State1/2/3", "P7_ZipCode1/2/3",
      "P7_Country1/2/3" (Parte 7, Emprego/Escola, 3 linhas) aparecem 1x cada (bem
      comportado). Mas "P7_OccupationFieldStudy1" aparece 3x (índices 0,1,2) e
      "P7_From1/2/3" aparecem 2x cada (índices 0,1) — nomes de campo duplicados
      entre linhas da tabela por erro de autoria do PDF (não usaram sufixo único
      por linha como fizeram nas outras colunas). Mapeado por ordem de aparição
      (índice 0,1,2 = linha 1,2,3) como melhor esforço; o "P5_EmployerName1/2/3"
      (nome interno de outra "Parte" mas nas mesmas 3 linhas) foi mapeado para o
      MESMO question_id de "P7_EmployerName1/2/3" (mesma hipótese de widget
      duplicado do alien_number). ÁREA SINALIZADA PARA REVISÃO HUMANA — não foi
      possível confirmar visualmente no PDF renderizado.
    - Todos os grupos Y/N deste formulário usam valores reais autoexplicativos
      ("Y"/"N"), ao contrário do I-90/I-751 que usavam "1"/"2" genéricos — então o
      risco de ordem trocada é baixo aqui; o desafio real foi identificar A QUE
      PERGUNTA cada campo pertence (nomes enganosos), não decifrar o valor certo.
    - O grande banco de perguntas Sim/Não da Parte 9 (Informações Adicionais,
      itens 1-37, ~55 checkboxes) não tem toolTip XFA para NENHUM item — todos
      resolvidos por leitura cuidadosa do texto das páginas 6-11 do PDF.
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


def ignore(notes: str = "") -> dict:
    d = {"question_id": "_ignore"}
    if notes:
        d["notes"] = notes
    return d


MAPPING_RULES: dict[str, object] = {

    # ── Parte 1 — Elegibilidade ──────────────────────────────────────────────
    # Ordem real de aparição no documento (via /AP) é C,B,A,E,F,G,D — NÃO
    # alfabética. Confirmado por toolTip de cada índice individualmente.
    "Part1_Eligibility": [
        cb("base_elegibilidade", "vawa"),                  # índice 0 = C
        cb("base_elegibilidade", "conjuge_usc"),           # índice 1 = B
        cb("base_elegibilidade", "geral"),                 # índice 2 = A
        cb("base_elegibilidade", "militar_hostilidades"),  # índice 3 = E
        cb("base_elegibilidade", "militar_1ano"),          # índice 4 = F
        cb("base_elegibilidade", "outro"),                 # índice 5 = G
        cb("base_elegibilidade", "conjuge_usc_exterior"),  # índice 6 = D
    ],
    "Line1_AlienNumber": txt("alien_number"),  # repetido em quase toda página, mesmo question_id
    "Part1Line5_OtherExplain": txt("base_elegibilidade_outro_explicacao"),
    "DropDownList1": txt("base_elegibilidade_escritorio_campo"),  # escritório USCIS p/ residentes no exterior (item 1.d)

    # ── Parte 2 — Informações Sobre Você ────────────────────────────────────
    "P2_Line1_FamilyName": [txt("nome_sobrenome"), txt("nome_sobrenome")],  # 2ª ocorrência = Parte 14 (pré-preenchido)
    "P2_Line1_GivenName": [txt("nome_nome"), txt("nome_nome")],
    "P2_Line1_MiddleName": [txt("nome_meio"), txt("nome_meio")],
    "Line2_FamilyName1": txt("nome_outro_usado_sobrenome"),
    "Line3_GivenName1": txt("nome_outro_usado_nome"),
    "Line3_MiddleName1": txt("nome_outro_usado_meio"),
    "Line2_FamilyName2": txt("nome_outro_usado2_sobrenome"),
    "Line3_GivenName2": txt("nome_outro_usado2_nome"),
    "Line3_MiddleName2": txt("nome_outro_usado2_meio"),

    "P2_Line34_NameChange": [cb("nome_mudou", "nao"), cb("nome_mudou", "sim")],
    "Part2Line3_FamilyName": txt("nome_novo_sobrenome"),
    "Part2Line4a_GivenName": txt("nome_novo_nome"),
    "Part2Line4a_MiddleName": txt("nome_novo_meio"),

    "P2_Line6_USCISELISAcctNumber": txt("uscis_online"),        # item 4 (nome interno diz "Line6")
    "P2_Line7_Gender": [cb("sexo", "masculino"), cb("sexo", "feminino")],  # item 5
    "P2_Line8_DateOfBirth": txt("data_nascimento"),              # item 6 (nome interno diz "Line8")
    "P2_Line9_DateBecamePermanentResident": txt("data_tornou_residente"),  # item 7
    "P2_Line10_CountryOfBirth": txt("pais_nascimento"),          # item 8 (nome interno diz "Line10")
    "P2_Line11_CountryOfNationality": txt("pais_nacionalidade"), # item 9 (nome interno diz "Line11")
    "P2_Line10_claimdisability": [cb("pais_cidadao_antes_18", "nao"), cb("pais_cidadao_antes_18", "sim")],  # item 10
    "P2_Line11_claimdisability": [cb("tem_deficiencia", "nao"), cb("tem_deficiencia", "sim")],  # item 11

    "Line12a_Checkbox": [cb("ssa_quer_cartao", "nao"), cb("ssa_quer_cartao", "sim")],   # item 12.a
    "Line12b_SSN": txt("ssn"),                                    # item 12.b
    "Line12\\.c_Checkbox": [cb("ssa_consentimento_divulgacao", "nao"), cb("ssa_consentimento_divulgacao", "sim")],  # item 12.c

    # ── Parte 3 — Informações Biográficas ───────────────────────────────────
    "P7_Line1_Ethnicity": [cb("etnia", "nao_hispanico"), cb("etnia", "hispanico")],
    "P7_Line2_Race": [
        cb("raca_indigena_americano", "sim"),   # I - American Indian/Alaska Native
        cb("raca_havaiano_pacifico", "sim"),    # A (colide com Asian) - Native Hawaiian/Pacific Islander, por posição
        cb("raca_negro", "sim"),                # B - Black/African American
        cb("raca_asiatico", "sim"),             # A (colide com Hawaiian) - Asian, por posição
        cb("raca_branco", "sim"),               # W - White
    ],
    "P7_Line3_HeightFeet": txt("altura_pes"),
    "P7_Line3_HeightInches": txt("altura_polegadas"),
    "P7_Line4_Pounds1": digit("peso", 1),
    "P7_Line4_Pounds2": digit("peso", 2),
    "P7_Line4_Pounds3": digit("peso", 3),
    "P7_Line5_Eye": [
        cb("cor_olhos", "castanho"), cb("cor_olhos", "azul"), cb("cor_olhos", "verde"),
        cb("cor_olhos", "avela"), cb("cor_olhos", "cinza"), cb("cor_olhos", "preto"),
        cb("cor_olhos", "rosa"), cb("cor_olhos", "marrom_avermelhado"), cb("cor_olhos", "outro"),
    ],
    "P7_Line6_Hair": [
        cb("cor_cabelo", "careca"), cb("cor_cabelo", "arenoso"), cb("cor_cabelo", "ruivo"),
        cb("cor_cabelo", "branco"), cb("cor_cabelo", "cinza"), cb("cor_cabelo", "loiro"),
        cb("cor_cabelo", "castanho"), cb("cor_cabelo", "preto"), cb("cor_cabelo", "outro"),
    ],

    # ── Parte 4 — Informações Sobre Sua Residência ──────────────────────────
    # Endereço físico atual (item 1)
    "P4_Line1_InCareOfName": txt("end_fisico_cuidados_de"),
    "P4_Line1_StreetName": txt("end_fisico_rua"),
    "P4_Line1_Number": txt("end_fisico_numero"),
    "P4_Line1_Unit": [cb("end_fisico_tipo_unidade", "flr"), cb("end_fisico_tipo_unidade", "ste"), cb("end_fisico_tipo_unidade", "apt")],
    "P4_Line1_City": txt("end_fisico_cidade"),
    "P4_Line1_State": [txt("end_fisico_estado"), txt("end_correio_estado")],  # [0]=físico atual, [1]=correio (por posição)
    "P4_Line1_ZipCode": txt("end_fisico_cep"),
    "P4_Line1_Province": txt("end_fisico_provincia"),
    "P4_Line1_PostalCode": txt("end_fisico_codigo_postal"),
    "P4_Line1_Country": txt("end_fisico_pais"),
    "P4_Line1_DatesofResidence": [txt("end_fisico_data_inicio"), txt("end_fisico_data_fim")],
    "Pt3_Line2a_Checkbox": [cb("end_fisico_igual_correio", "nao"), cb("end_fisico_igual_correio", "sim")],  # item 2

    # Endereço de correspondência (item 3) — "Safe Mailing Address"
    "P5_Line1b_InCareOfName": txt("end_correio_cuidados_de"),
    "P5_Line1b_StreetName": txt("end_correio_rua"),
    "P5_Line1b_Number": txt("end_correio_numero"),
    "P5_Line1b_Unit": [cb("end_correio_tipo_unidade", "flr"), cb("end_correio_tipo_unidade", "ste"), cb("end_correio_tipo_unidade", "apt")],
    "P5_Line1b_City": txt("end_correio_cidade"),
    "P5_Line1b_ZipCode": txt("end_correio_cep"),
    "P5_Line1b_Province": txt("end_correio_provincia"),
    "P5_Line1b_PostalCode": txt("end_correio_codigo_postal"),
    "P5_Line1b_Country": txt("end_correio_pais"),

    # Histórico de endereços - últimos 5 anos (3 linhas)
    "P4_Line3_PhysicalAddress1": txt("residencia1_rua"),
    "P4_Line3_PhysicalAddress2": txt("residencia2_rua"),
    "P4_Line3_PhysicalAddress3": txt("residencia3_rua"),
    "P4_Line3_CityTown1": txt("residencia1_cidade"),
    "P4_Line3_CityTown2": txt("residencia2_cidade"),
    "P4_Line3_CityTown3": txt("residencia3_cidade"),
    "P4_Line3_State1": txt("residencia1_estado"),
    "P4_Line3_State2": txt("residencia2_estado"),
    "P4_Line3_State3": txt("residencia3_estado"),
    "P4_Line3_ZipCode1": txt("residencia1_cep"),
    "P4_Line3_ZipCode2": txt("residencia2_cep"),
    "P4_Line3_ZipCode3": txt("residencia3_cep"),
    "P4_Line3_Country1": txt("residencia1_pais"),
    "P4_Line3_Country2": txt("residencia2_pais"),
    "P4_Line3_Country3": txt("residencia3_pais"),
    "P4_Line3_From1": [txt("residencia1_data_inicio"), txt("residencia1_data_inicio")],
    "P4_Line3_From2": txt("residencia2_data_inicio"),
    "P4_Line3_From3": txt("residencia3_data_inicio"),
    "P4_Line3_To2": txt("residencia2_data_fim"),
    "P4_Line3_To3": txt("residencia3_data_fim"),

    # ── Parte 5 — Histórico Marital ─────────────────────────────────────────
    "P10_Line1_MaritalStatus": [
        cb("estado_civil", "divorciado"), cb("estado_civil", "solteiro"), cb("estado_civil", "viuvo"),
        cb("estado_civil", "casado"), cb("estado_civil", "anulado"), cb("estado_civil", "separado"),
    ],
    "Part9Line3_TimesMarried": txt("vezes_casado"),  # item 3
    "P7_Line2_Forces": [cb("conjuge_militar", "nao"), cb("conjuge_militar", "sim")],  # item 2

    "P10_Line4a_FamilyName": txt("conjuge_sobrenome"),
    "P10_Line4a_GivenName": txt("conjuge_nome"),
    "P10_Line4a_MiddleName": txt("conjuge_meio"),
    "P10_Line4d_DateofBirth": txt("conjuge_data_nascimento"),
    "P10_Line4e_DateEnterMarriage": txt("data_casamento"),
    "P10_Line5_Citizen": [cb("conjuge_endereco_igual", "nao"), cb("conjuge_endereco_igual", "sim")],  # item 4.d (nome interno enganoso)
    "P10_Line5a_When": [cb("conjuge_quando_ficou_cidadao", "nascimento"), cb("conjuge_quando_ficou_cidadao", "outro")],  # item 5.a
    "P10_Line5b_DateBecame": txt("conjuge_data_naturalizacao"),  # item 5.b
    "P7_Line6_ANumber": txt("conjuge_alien_number"),  # item 6
    "P10_Line4g_Employer": txt("conjuge_vezes_casado"),  # item 7 (nome interno diz "Employer", é texto numérico)
    "TextField1": txt("conjuge_empregador_atual"),  # item 8

    # ── Parte 6 — Informações Sobre Seus Filhos ─────────────────────────────
    "P11_Line1_TotalChildren": [txt("total_filhos_menores"), txt("total_membros_familia_com_renda")],  # [0]=Parte6 item1, [1]=Parte10 item4
    "P5_EmployerName1": txt("filho1_nome"),
    "P5_EmployerName2": txt("filho2_nome"),
    "P5_EmployerName3": txt("filho3_nome"),
    "P9_Line5a": [cb("filho1_prestando_suporte", "sim"), cb("filho1_prestando_suporte", "nao")],
    "P6_ChildTwo": [cb("filho2_prestando_suporte", "nao"), cb("filho2_prestando_suporte", "sim")],
    "P6_ChildThree": [cb("filho3_prestando_suporte", "nao"), cb("filho3_prestando_suporte", "sim")],

    # ── Parte 7 — Emprego e Escolas (3 linhas, últimos 5 anos) ─────────────
    # NOTA: colunas Occupation e From têm nome de campo duplicado entre linhas
    # (erro de autoria do PDF) — mapeado por ordem de aparição (best-effort).
    "P7_EmployerName1": txt("emprego1_nome"),
    "P7_EmployerName2": txt("emprego2_nome"),
    "P7_EmployerName3": txt("emprego3_nome"),
    "P7_City1": txt("emprego1_cidade"),
    "P7_City2": txt("emprego2_cidade"),
    "P7_City3": txt("emprego3_cidade"),
    "P7_State1": txt("emprego1_estado"),
    "P7_State2": txt("emprego2_estado"),
    "P7_State3": txt("emprego3_estado"),
    "P7_ZipCode1": txt("emprego1_cep"),
    "P7_ZipCode2": txt("emprego2_cep"),
    "P7_ZipCode3": txt("emprego3_cep"),
    "P7_Country1": txt("emprego1_pais"),
    "P7_Country2": txt("emprego2_pais"),
    "P7_Country3": txt("emprego3_pais"),
    "P7_OccupationFieldStudy1": [txt("emprego1_ocupacao"), txt("emprego2_ocupacao"), txt("emprego3_ocupacao")],
    "P7_OccupationFieldStudy2": {"question_id": "_ignore", "notes": "Nome de campo duplicado (bug de autoria do PDF) — ver P7_OccupationFieldStudy1"},
    "P7_OccupationFieldStudy3": {"question_id": "_ignore", "notes": "Nome de campo duplicado (bug de autoria do PDF) — ver P7_OccupationFieldStudy1"},
    "P7_From1": [txt("emprego1_data_inicio"), txt("emprego1_data_inicio")],
    "P7_From2": [txt("emprego2_data_inicio"), txt("emprego2_data_inicio")],
    "P7_From3": [txt("emprego3_data_inicio"), txt("emprego3_data_inicio")],
    "P7_To2": txt("emprego2_data_fim"),
    "P7_To3": txt("emprego3_data_fim"),

    # ── Parte 8 — Tempo Fora dos Estados Unidos (6 viagens) ─────────────────
    "P9_Line1_Countries1": txt("viagem1_paises"),  # nome interno enganoso (diz "P9_Line1")
    "P8_Line1_DateLeft1": txt("viagem1_data_saida"),
    "P8_Line1_DateReturn1": txt("viagem1_data_retorno"),
    "P8_Line1_Countries2": txt("viagem2_paises"),
    "P8_Line1_DateLeft2": txt("viagem2_data_saida"),
    "P8_Line1_DateReturn2": txt("viagem2_data_retorno"),
    "P8_Line1_Countries3": txt("viagem3_paises"),
    "P8_Line1_DateLeft3": txt("viagem3_data_saida"),
    "P8_Line1_DateReturn3": txt("viagem3_data_retorno"),
    "P8_Line1_Countries4": txt("viagem4_paises"),
    "P8_Line1_DateLeft4": txt("viagem4_data_saida"),
    "P8_Line1_DateReturn4": txt("viagem4_data_retorno"),
    "P8_Line1_Countries5": txt("viagem5_paises"),
    "P8_Line1_DateLeft5": txt("viagem5_data_saida"),
    "P8_Line1_DateReturn5": txt("viagem5_data_retorno"),
    "P8_Line1_Countries6": txt("viagem6_paises"),
    "P8_Line1_DateLeft6": txt("viagem6_data_saida"),
    "P8_Line1_DateReturn6": txt("viagem6_data_retorno"),

    # ── Parte 9 — Informações Adicionais (itens 1-37) ───────────────────────
    # Nenhum destes tem toolTip XFA — todos resolvidos via texto das páginas 6-11.
    "P9_Line1": [cb("reivindicou_cidadania_falsamente", "nao"), cb("reivindicou_cidadania_falsamente", "sim")],  # item1
    "P9_Line2": [cb("registrou_votou_eleicao", "nao"), cb("registrou_votou_eleicao", "sim")],  # item2
    "P9_Line3": [cb("deve_impostos_atrasados", "sim"), cb("deve_impostos_atrasados", "nao")],  # item3
    "P9_Line4": [cb("declarou_nao_residente_fiscal", "sim"), cb("declarou_nao_residente_fiscal", "nao")],  # item4
    "P9_5a": [cb("membro_partido_comunista", "sim"), cb("membro_partido_comunista", "nao")],  # item5.a
    "P9_5b": [cb("advogou_derrubar_governo", "sim"), cb("advogou_derrubar_governo", "nao")],  # item5.b
    "P12_6a": [cb("usou_arma_explosivo_dano", "nao"), cb("usou_arma_explosivo_dano", "sim")],  # item6.a (nome interno enganoso)
    "P12_6b": [cb("participou_sequestro_assassinato_sabotagem", "sim"), cb("participou_sequestro_assassinato_sabotagem", "nao")],  # item6.b
    "P12_6c": [cb("ameacou_conspirou_atos_6a_6b", "nao"), cb("ameacou_conspirou_atos_6a_6b", "sim")],  # item6.c
    "P9_Line7a": [cb("ordenou_tortura", "nao"), cb("ordenou_tortura", "sim")],  # item7.a
    "P9_Line7\\.b\\.": [cb("ordenou_genocidio", "nao"), cb("ordenou_genocidio", "sim")],  # item7.b
    "P9_Line7\\.c": [cb("tentou_matar_pessoa", "nao"), cb("tentou_matar_pessoa", "sim")],  # item7.c
    "P11_7d": [cb("contato_sexual_sem_consentimento", "nao"), cb("contato_sexual_sem_consentimento", "sim")],  # item7.d
    "P9_Line7\\.e": [cb("feriu_intencionalmente_pessoa", "nao"), cb("feriu_intencionalmente_pessoa", "sim")],  # item7.e
    "P9_Line7\\.f": [cb("impediu_pratica_religiosa", "nao"), cb("impediu_pratica_religiosa", "sim")],  # item7.f
    "P9_Line7\\.g": [cb("causou_dano_discriminacao", "nao"), cb("causou_dano_discriminacao", "sim")],  # item7.g
    "P9_Line8a": [cb("serviu_unidade_militar_policial", "nao"), cb("serviu_unidade_militar_policial", "sim")],  # item8.a
    "P9_Line8b": [cb("serviu_grupo_armado", "nao"), cb("serviu_grupo_armado", "sim")],  # item8.b
    "P9_Line9": [cb("trabalhou_local_detencao", "nao"), cb("trabalhou_local_detencao", "sim")],  # item9
    "P9_Line10a": [cb("parte_grupo_arma_ameaca", "nao"), cb("parte_grupo_arma_ameaca", "sim")],  # item10.a
    "P9_Line10b": [cb("grupo_usou_arma_pessoa", "nao"), cb("grupo_usou_arma_pessoa", "sim")],  # item10.b
    "P9_Line10c": [cb("grupo_ameacou_arma_pessoa", "sim"), cb("grupo_ameacou_arma_pessoa", "nao")],  # item10.c
    "P9_Line11": [cb("recebeu_treinamento_armas", "nao"), cb("recebeu_treinamento_armas", "sim")],  # item11
    "P9_Line12": [cb("vendeu_transportou_armas", "nao"), cb("vendeu_transportou_armas", "sim")],  # item12
    "P9_Line13": [cb("recrutou_menor15_grupo_armado", "nao"), cb("recrutou_menor15_grupo_armado", "sim")],  # item13
    "P9_Line14": [cb("usou_menor15_hostilidades", "nao"), cb("usou_menor15_hostilidades", "sim")],  # item14
    "P9_Line15a": [cb("cometeu_crime_nao_preso", "nao"), cb("cometeu_crime_nao_preso", "sim")],  # item15.a
    "P9_Line15b": [cb("foi_preso_citado_detido_acusado", "nao"), cb("foi_preso_citado_detido_acusado", "sim")],  # item15.b
    # Tabela de crimes/infrações (item 15.b) — 5 linhas x 6 colunas
    "P12_Line29_why1": txt("crime1_local"),
    "P12_Line29_why2": txt("crime2_local"),
    "P12_Line29_why3": txt("crime3_local"),
    "P12_Line29_why4": txt("crime4_local"),
    "P12_Line29_why5": txt("crime5_local"),
    "P12_Line29_Date1": txt("crime1_data"),
    "P12_Line29_Date2": txt("crime2_data"),
    "P12_Line29_Date3": txt("crime3_data"),
    "P12_Line29_Date4": txt("crime4_data"),
    "P12_Line29_Date5": txt("crime5_data"),
    "P12_Line29_Outcome1": [txt("crime1_disposicao"), txt("crime1_crime"), txt("crime1_sentenca")],
    "P12_Line29_Outcome2": [txt("crime2_disposicao"), txt("crime2_crime"), txt("crime2_sentenca")],
    "P12_Line29_Outcome3": [txt("crime3_disposicao"), txt("crime3_crime"), txt("crime3_sentenca")],
    "P12_Line29_Outcome4": [txt("crime4_disposicao"), txt("crime4_crime"), txt("crime4_sentenca")],
    "P12_Line29_Outcome5": [txt("crime5_disposicao"), txt("crime5_crime"), txt("crime5_sentenca")],
    "P12_Line29_DateOfConv1": txt("crime1_data_condenacao"),
    "P12_Line29_DateOfConv2": txt("crime2_data_condenacao"),
    "P12_Line29_DateOfConv3": txt("crime3_data_condenacao"),
    "P12_Line29_DateOfConv4": txt("crime4_data_condenacao"),
    "P12_Line29_DateOfConv5": txt("crime5_data_condenacao"),
    "P12_Line16": [cb("cumpriu_pena_condicional_liberdade", "nao"), cb("cumpriu_pena_condicional_liberdade", "sim")],  # item16
    "P11_Line17A": [cb("envolvido_prostituicao", "nao"), cb("envolvido_prostituicao", "sim")],  # item17.a
    "P11_Line17B": [cb("trafico_drogas", "nao"), cb("trafico_drogas", "sim")],  # item17.b
    "P11_Line17C": [cb("casou_para_beneficio_imigratorio", "nao"), cb("casou_para_beneficio_imigratorio", "sim")],  # item17.c
    "P12_Line17d": [cb("casado_mais_de_uma_pessoa", "nao"), cb("casado_mais_de_uma_pessoa", "sim")],  # item17.d
    "P12_Line17e": [cb("ajudou_entrada_ilegal", "nao"), cb("ajudou_entrada_ilegal", "sim")],  # item17.e
    "P12_Line17f": [cb("jogo_ilegal", "sim"), cb("jogo_ilegal", "nao")],  # item17.f
    "P12_Line17g": [cb("deixou_pagar_pensao", "nao"), cb("deixou_pagar_pensao", "sim")],  # item17.g
    "P12_Line17h": [cb("falsa_declaracao_beneficio_publico", "nao"), cb("falsa_declaracao_beneficio_publico", "sim")],  # item17.h
    "P12_Line18": [cb("forneceu_info_falsa_governo", "sim"), cb("forneceu_info_falsa_governo", "nao")],  # item18
    "P12_Line19": [cb("mentiu_para_entrar_eua", "sim"), cb("mentiu_para_entrar_eua", "nao")],  # item19
    "P12_Line20": [cb("foi_removido_deportado", "nao"), cb("foi_removido_deportado", "sim")],  # item20
    "P12_Line21": [cb("processo_remocao_rescisao", "nao"), cb("processo_remocao_rescisao", "sim")],  # item21
    "P9_Line22a": [cb("homem_residiu_18_26", "nao"), cb("homem_residiu_18_26", "sim")],  # item22.a
    "Pt9_Line22b": [cb("registrou_selective_service", "nao"), cb("registrou_selective_service", "sim")],  # item22.b
    "P9_Line22c_Date": txt("selective_service_data"),  # item22.c
    "P9_Line22c_SSNumber": txt("selective_service_numero"),  # item22.c
    "P12_Line23": [cb("saiu_eua_evitar_recrutamento", "nao"), cb("saiu_eua_evitar_recrutamento", "sim")],  # item23
    "P12_Line24": [cb("pediu_isencao_servico_militar", "nao"), cb("pediu_isencao_servico_militar", "sim")],  # item24
    "P12_Line25": [cb("serviu_forcas_armadas_eua", "nao"), cb("serviu_forcas_armadas_eua", "sim")],  # item25
    "P12_Line26a": [cb("membro_atual_forcas_armadas", "nao"), cb("membro_atual_forcas_armadas", "sim")],  # item26.a
    "P12_Line26b": [cb("destacamento_exterior_3meses", "nao"), cb("destacamento_exterior_3meses", "sim")],  # item26.b
    "P12_Line26c": [cb("estacionado_fora_eua", "nao"), cb("estacionado_fora_eua", "sim")],  # item26.c
    "P11_Line26d": [cb("ex_militar_reside_exterior", "nao"), cb("ex_militar_reside_exterior", "sim")],  # item26.d
    "P12_Line27": [cb("dispensado_por_ser_estrangeiro", "sim"), cb("dispensado_por_ser_estrangeiro", "nao")],  # item27
    "P12_Line28": [cb("corte_marcial_dispensa_desonrosa", "sim"), cb("corte_marcial_dispensa_desonrosa", "nao")],  # item28
    "P9_Line29": [cb("desertou_forcas_armadas", "nao"), cb("desertou_forcas_armadas", "sim")],  # item29
    "P12_Line30a": [cb("possui_titulo_nobreza", "sim"), cb("possui_titulo_nobreza", "nao")],  # item30.a
    "P12_Line30b": [cb("disposto_renunciar_titulo", "sim"), cb("disposto_renunciar_titulo", "nao")],  # item30.b
    "P9_NobilityTitles": txt("titulo_nobreza_lista"),  # item30.b (texto livre com os títulos)
    "P12_Line31": [cb("apoia_constituicao_governo", "nao"), cb("apoia_constituicao_governo", "sim")],  # item31
    "P12_Line32": [cb("entende_juramento_fidelidade", "sim"), cb("entende_juramento_fidelidade", "nao")],  # item32
    "P12_Line33": [cb("incapaz_juramento_deficiencia", "sim"), cb("incapaz_juramento_deficiencia", "nao")],  # item33
    "P12_Line34": [cb("disposto_juramento_completo", "nao"), cb("disposto_juramento_completo", "sim")],  # item34
    "P12_Line35": [cb("disposto_portar_armas", "sim"), cb("disposto_portar_armas", "nao")],  # item35
    "P12_Line36": [cb("disposto_servico_nao_combatente", "nao"), cb("disposto_servico_nao_combatente", "sim")],  # item36
    "P12_Line37": [cb("disposto_trabalho_nacional_importante", "sim"), cb("disposto_trabalho_nacional_importante", "nao")],  # item37

    # ── Parte 10 — Pedido de Redução de Taxa ────────────────────────────────
    "P10_Line1_Citizen": [cb("renda_ate_400_pobreza", "nao"), cb("renda_ate_400_pobreza", "sim")],  # item1 (nome interno enganoso)
    "P10_Line2_TotalHouseholdIn": txt("renda_familiar_total"),  # item2
    "P10_Line3_HouseHoldSize": txt("tamanho_familia"),  # item3
    "P10_Line5a": [cb("sou_chefe_familia", "nao"), cb("sou_chefe_familia", "sim")],  # item5.a
    "P10_Line5b_NameOfHousehold": txt("nome_chefe_familia"),  # item5.b

    # ── Parte 11 — Contato, Certificação e Assinatura do Requerente ────────
    "P12_Line3_Telephone": txt("telefone"),
    "P12_Line3_Mobile": txt("celular"),
    "P12_Line5_Email": txt("email"),
    "P12_SignatureApplicant": [ignore("Assinatura física do requerente"), ignore("Assinatura física do requerente (repetida)"), ignore("Assinatura física do requerente (repetida)")],
    "P13_DateofSignature": txt("data_assinatura"),

    # ── Parte 12 — Intérprete ────────────────────────────────────────────────
    "P14_Line1_nterpreterFamilyName": txt("int_sobrenome"),
    "P14_Line1_nterpreterGivenName": txt("int_nome"),
    "P14_Line2_NameofBusinessorOrgName": txt("int_organizacao"),
    "P14_Line4_Telephone": txt("int_telefone"),
    "P14_Line5_Mobile": txt("int_celular"),
    "P14_Line5_EmailAddress": txt("int_email"),
    "P14_NameOfLanguage": txt("int_idioma"),
    "P14_DateofSignature": txt("int_data_assinatura"),

    # ── Parte 13 — Preparador (se aplicável) ────────────────────────────────
    "P15_Line1_PreparerFamilyName": txt("prep_sobrenome"),
    "P15_Line1_PreparerGivenName": txt("prep_nome"),
    "P15_Line2_NameofBusinessorOrgName": txt("prep_organizacao"),
    "P15_Line4_Telephone": txt("prep_telefone"),
    "P15_Line5_Mobile": txt("prep_celular"),
    "P15_Line6_Email": txt("prep_email"),
    "P15_DateofSignature": txt("prep_data_assinatura"),

    # ── Parte 14 — Informações Adicionais (grade em branco, 4 linhas) ──────
    "P11_Line3A": txt("info_adicional1_pagina"),
    "P11_Line3B": txt("info_adicional1_parte"),
    "P11_Line3C": txt("info_adicional1_item"),
    "P11_Line3D": txt("info_adicional1_texto"),
    "P11_Line4A": txt("info_adicional2_pagina"),
    "P11_Line4B": txt("info_adicional2_parte"),
    "P11_Line4C": txt("info_adicional2_item"),
    "P11_Line4D": txt("info_adicional2_texto"),
    "P11_Line5A": txt("info_adicional3_pagina"),
    "P11_Line5B": txt("info_adicional3_parte"),
    "P11_Line5C": txt("info_adicional3_item"),
    "P11_Line5D": txt("info_adicional3_texto"),
    "P11_Line6A": txt("info_adicional4_pagina"),
    "P11_Line6B": txt("info_adicional4_parte"),
    "P11_Line6C": txt("info_adicional4_item"),
    "P11_Line6D": txt("info_adicional4_texto"),

    # ── Partes 15 e 16 — Assinatura na Entrevista / Juramento (uso do USCIS) ─
    "Part15ApplicantsSignature": ignore("Assinatura física do requerente na entrevista (preenchida pelo USCIS)"),
    "Part15USCISSignature": ignore("Assinatura do oficial do USCIS"),
    "Part15USCISName": ignore("Nome do oficial do USCIS"),
    "Part15DateofSignature": [ignore("Data de assinatura na entrevista (uso do USCIS)"), ignore("Data de assinatura do Juramento (uso do USCIS)")],
    "ApplicantsSignature": ignore("Assinatura física do requerente no Juramento de Fidelidade"),
}


def _split_qualified_name(pdf_field: str) -> list[str]:
    """Divide o nome completo do campo em segmentos, respeitando pontos
    escapados com barra invertida (nomes de campo como "Line7\\.b\\." contêm
    um ponto literal que faz parte do nome, não um separador de hierarquia).
    """
    return re.split(r"(?<!\\)\.", pdf_field)


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

        segments = _split_qualified_name(pdf_field)
        short = segments[-1]
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
            if "notes" in item:
                entry["notes"] = item["notes"]
            result_fields.append(entry)
            continue

        if rule is None:
            unmapped.append(pdf_field)
            continue

        entry = {"pdf_field": pdf_field, "type": rule.get("type", ftype), "question_id": rule["question_id"]}
        if "check_if_answer" in rule:
            entry["check_if_answer"] = rule["check_if_answer"]
        if "digit_split" in rule:
            entry["digit_split"] = rule["digit_split"]
        if "notes" in rule:
            entry["notes"] = rule["notes"]
        result_fields.append(entry)

    if unmapped:
        print(f"AVISO: {len(unmapped)} campo(s) sem regra de mapeamento:")
        for u in unmapped:
            print(f"  - {u}")
    else:
        print("Todos os campos cobertos.")

    out_data = {"form": "N-400", "fields": result_fields}
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mapeados: {len(result_fields)} campos")
    print(f"Salvo em: {out_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    apply_rules(base_dir / "data/mappings/n-400.skeleton.json",
                base_dir / "data/mappings/n-400.json")
