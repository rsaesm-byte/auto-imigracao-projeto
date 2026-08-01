"""
build_questionnaire_ds160.py — Gera data/questionnaires/ds160.json.

Formulário SEPARADO do DS-160 oficial: o DS-160 de verdade só existe no
site do Departamento de Estado (CEAC), preenchido diretamente lá, nunca
via PDF/AcroForm. Este questionário coleta o "rascunho" que a Saes já usa
hoje em 3 versões de referência (planilha Excel interna, formulário
numerado com a marca Saes, e uma versão detalhada que segue a ordem real
do DS-160) -- todas fornecidas pelo usuário e mescladas aqui numa versão
só, sem perder nenhuma pergunta das três. A equipe usa as respostas pra
preencher o DS-160 de verdade no CEAC (scripts/generate_ds160_draft.py
gera o PDF que a equipe consulta lado a lado).

Cobre os dois serviços que a Saes vende (uma pergunta inicial ramifica o
resto via show_if, ao custo de repetir só a seção "Propósito da viagem",
que é a única que difere de verdade entre os dois):
- B1/B2: turismo/negócios.
- F1/F2: estudante/dependente de estudante.

Respondido em português (mesma exigência das 3 referências originais).
"""
import json
from pathlib import Path

SECTIONS = [
    {"id": "tipo_visto", "title": "Tipo de Visto"},
    {"id": "pessoal", "title": "Informações Pessoais"},
    {"id": "endereco_contato", "title": "Endereço e Contato"},
    {"id": "passaporte", "title": "Passaporte"},
    {"id": "viagem", "title": "Informações sobre a Viagem aos EUA"},
    {"id": "acompanhantes", "title": "Companheiros de Viagem"},
    {"id": "viagens_anteriores", "title": "Viagens e Vistos Anteriores aos EUA"},
    {"id": "contato_eua", "title": "Contato nos EUA"},
    {"id": "familia", "title": "Informações Familiares"},
    {"id": "trabalho_atual", "title": "Trabalho ou Escola Atual"},
    {"id": "trabalho_anterior", "title": "Trabalho ou Escola Anteriores"},
    {"id": "educacao", "title": "Formação Educacional"},
    {"id": "info_adicional", "title": "Informações Adicionais"},
    {"id": "seguranca", "title": "Segurança e Antecedentes"},
]


def text(qid, section, label, hint="", required=True, show_if=None):
    d = {"id": qid, "section": section, "label": label, "type": "text", "required": required}
    if hint:
        d["hint"] = hint
    if show_if:
        d["show_if"] = show_if
    return d


def date_q(qid, section, label, hint="", required=True, show_if=None):
    d = text(qid, section, label, hint, required, show_if)
    d["type"] = "date"
    return d


def radio(qid, section, label, options, required=True, show_if=None, hint=None):
    d = {"id": qid, "section": section, "label": label, "type": "radio", "required": required,
         "options": [{"value": v, "label": l} for v, l in options]}
    if show_if:
        d["show_if"] = show_if
    if hint:
        d["hint"] = hint
    return d


def checkbox_group(qid, section, label, options, required=False, show_if=None, hint=None):
    d = {"id": qid, "section": section, "label": label, "type": "checkbox_group", "required": required,
         "options": [{"value": v, "label": l} for v, l in options]}
    if show_if:
        d["show_if"] = show_if
    if hint:
        d["hint"] = hint
    return d


SIM_NAO = [("sim", "Sim"), ("nao", "Não")]


def yesno(qid, section, label, hint=None, show_if=None):
    return radio(qid, section, label, SIM_NAO, required=True, show_if=show_if, hint=hint)


def yesno_explain(qid_base, section, label, explain_label="Explique / informe os detalhes",
                   hint=None, show_if=None, explain_required=True):
    """Par padrão do DS-160 real: um Sim/Não seguido de um campo de texto
    que só aparece (e só é obrigatório) quando a resposta é "sim" -- é o
    padrão mais comum nas 3 referências (viagens anteriores, segurança,
    vistos cancelados, etc.)."""
    q1 = yesno(qid_base, section, label, hint=hint, show_if=show_if)
    q2 = text(f"{qid_base}_detalhes", section, explain_label, required=explain_required,
              show_if={"question": qid_base, "equals": "sim"})
    return [q1, q2]


SI_B1B2 = {"question": "tipo_visto", "equals": "b1_b2"}
SI_F1F2 = {"question": "tipo_visto", "equals": "f1_f2"}
SI_JA_ESTEVE_EUA = {"question": "ja_esteve_eua", "equals": "sim"}
SI_JA_TEVE_VISTO = {"question": "ja_teve_visto_eua", "equals": "sim"}
SI_OUTRA_NACIONALIDADE = {"question": "outra_nacionalidade", "equals": "sim"}
SI_OUTROS_NOMES = {"question": "outros_nomes", "equals": "sim"}
SI_TEM_HABILITACAO_EUA = {"question": "tem_habilitacao_eua", "equals": "sim"}
SI_VIAJA_ACOMPANHADO = {"question": "viaja_acompanhado", "equals": "sim"}
SI_TEM_PLANO_VIAGEM = {"question": "tem_plano_viagem", "equals": "sim"}
SI_QUEM_PAGA_OUTRO = {"question": "quem_paga_viagem", "equals": "outra_pessoa"}
SI_QUEM_PAGA_EMPRESA = {"question": "quem_paga_viagem", "equals": "empresa"}
SI_ENDERECO_CORRESP_DIFERENTE = {"question": "endereco_correspondencia_igual", "equals": "nao"}
SI_APLICANTE_PRINCIPAL = {"question": "aplicante_principal", "equals": "sim"}
SI_NAO_APLICANTE_PRINCIPAL = {"question": "aplicante_principal", "equals": "nao"}
SI_TEM_PARENTE_EUA = {"question": "tem_parente_imediato_eua", "equals": "sim"}
SI_TEM_CONTATO_EUA = {"question": "tem_contato_eua", "equals": "sim"}
SI_PAI_NOS_EUA = {"question": "pai_nos_eua", "equals": "sim"}
SI_MAE_NOS_EUA = {"question": "mae_nos_eua", "equals": "sim"}
SI_TEM_CONJUGE = {"question": "estado_civil_ds160", "equals": ["casado", "uniao_estavel", "divorciado", "separado", "viuvo"]}
SI_DIVORCIADO_SEPARADO = {"question": "estado_civil_ds160", "equals": ["divorciado", "separado"]}
SI_MENOS_5_ANOS_ATUAL = {"question": "menos_5_anos_trabalho_atual", "equals": "sim"}
SI_TRABALHOU_ANTES = {"question": "teve_emprego_anterior", "equals": "sim"}
SI_TEM_FORMACAO_SUPERIOR = {"question": "tem_formacao_superior", "equals": "sim"}
SI_VIAJOU_OUTROS_PAISES = {"question": "viajou_outros_paises_5anos", "equals": "sim"}
SI_PARTICIPA_CARIDADE = {"question": "participa_caridade", "equals": "sim"}
SI_SERVICO_MILITAR = {"question": "servico_militar", "equals": "sim"}
SI_REDE_SOCIAL_OUTRAS = {"question": "usa_redes_sociais", "equals": "sim"}
SI_OUTROS_TELEFONES = {"question": "outros_telefones_5anos", "equals": "sim"}
SI_OUTROS_EMAILS = {"question": "outros_emails_5anos", "equals": "sim"}
SI_OUTRA_PRESENCA_ONLINE = {"question": "outra_presenca_online", "equals": "sim"}
SI_PASSAPORTE_PERDIDO = {"question": "passaporte_perdido", "equals": "sim"}


def build_questions():
    qs = []

    # ---------------------------------------------------------------
    # 0. Tipo de visto e consulado
    # ---------------------------------------------------------------
    qs.append(radio(
        "tipo_visto", "tipo_visto", "Qual visto você está solicitando?",
        [("b1_b2", "B1/B2 — Turismo ou Negócios"), ("f1_f2", "F1/F2 — Estudante ou dependente de estudante")],
        hint="Já vem preenchido conforme o que a equipe registrou no seu caso -- confirme antes de continuar."))
    qs.append(radio(
        "consulado", "tipo_visto", "Consulado americano onde pretende fazer a entrevista",
        [("brasilia", "Brasília"), ("recife", "Recife"), ("rio_de_janeiro", "Rio de Janeiro"),
         ("sao_paulo", "São Paulo"), ("porto_alegre", "Porto Alegre")],
        hint="Preencha mesmo que seja renovação de visto."))
    qs.append(radio(
        "solicitando_via_agencia", "tipo_visto",
        "Você está solicitando o visto através de uma agência (além da Saes)?",
        [("nao", "Não, sou o solicitante direto"), ("sim", "Sim, estou usando outra agência também")]))
    qs.append(text("nome_agencia", "tipo_visto", "Nome da agência",
                    show_if={"question": "solicitando_via_agencia", "equals": "sim"}))

    # ---------------------------------------------------------------
    # 1. Informações pessoais
    # ---------------------------------------------------------------
    qs.append(text("sobrenome_passaporte", "pessoal", "Sobrenome (exatamente como no passaporte)"))
    qs.append(text("nome_passaporte", "pessoal", "Nome e nome(s) do meio (exatamente como no passaporte)"))
    qs.append(text("nome_alfabeto_nativo", "pessoal",
                    "Nome completo no alfabeto nativo (se o passaporte não usa alfabeto latino)",
                    hint='Se não se aplica ao seu caso, escreva "Não se aplica".', required=False))
    qs.append(yesno("outros_nomes", "pessoal",
                     "Você já usou outros nomes (solteira, religioso, profissional, pseudônimo)?"))
    qs.append(text("outros_nomes_sobrenomes", "pessoal", "Outros sobrenomes utilizados", show_if=SI_OUTROS_NOMES))
    qs.append(text("outros_nomes_nomes", "pessoal", "Outros nomes utilizados", show_if=SI_OUTROS_NOMES))
    qs.append(radio("sexo", "pessoal", "Sexo", [("masculino", "Masculino"), ("feminino", "Feminino")]))
    qs.append(radio("estado_civil_ds160", "pessoal", "Estado civil oficial", [
        ("casado", "Casado(a)"), ("solteiro", "Solteiro(a)"), ("viuvo", "Viúvo(a)"),
        ("divorciado", "Divorciado(a)"), ("separado", "Separado(a) legalmente"),
        ("uniao_estavel", "União estável (com ou sem contrato)"), ("outro", "Outro"),
    ]))
    qs.append(text("estado_civil_outro_detalhe", "pessoal", "Especifique o estado civil",
                    show_if={"question": "estado_civil_ds160", "equals": "outro"}))
    qs.append(date_q("data_nascimento", "pessoal", "Data de nascimento"))
    qs.append(text("cidade_nascimento", "pessoal", "Cidade de nascimento"))
    qs.append(text("estado_nascimento", "pessoal", "Estado de nascimento"))
    qs.append(text("pais_nascimento", "pessoal", "País de nascimento"))
    qs.append(text("nacionalidade", "pessoal", "Nacionalidade"))
    qs.append(yesno("outra_nacionalidade", "pessoal",
                     "Possui (ou já possuiu) outra nacionalidade além da informada acima?"))
    qs.append(text("outra_nacionalidade_qual", "pessoal", "Qual outra nacionalidade", show_if=SI_OUTRA_NACIONALIDADE))
    qs.append(text("outra_nacionalidade_passaporte", "pessoal",
                    "Número do passaporte dessa outra nacionalidade (se possuir passaporte válido)",
                    required=False, show_if=SI_OUTRA_NACIONALIDADE))
    qs.append(text("cpf", "pessoal", 'Número do CPF (se não possuir, escreva "Não se aplica")'))
    qs.append(text("rg", "pessoal", "Número do RG", required=False))
    qs.append(text("ssn_eua", "pessoal",
                    'Possui Social Security Number (SSN) americano? Informe o número (ou "Não se aplica")',
                    required=False))
    qs.append(text("itin_eua", "pessoal",
                    'Possui número de identificação fiscal americano (ITIN/Taxpayer ID)? Informe (ou "Não se aplica")',
                    required=False))

    # ---------------------------------------------------------------
    # 2. Endereço e contato
    # ---------------------------------------------------------------
    qs.append(text("endereco_rua", "endereco_contato", "Endereço residencial — Rua/Avenida, número e complemento"))
    qs.append(text("endereco_bairro", "endereco_contato", "Bairro"))
    qs.append(text("endereco_cidade", "endereco_contato", "Cidade"))
    qs.append(text("endereco_estado", "endereco_contato", "Estado"))
    qs.append(text("endereco_cep", "endereco_contato", "CEP"))
    qs.append(text("endereco_pais", "endereco_contato", "País", required=False,
                    hint="Deixe em branco se for o Brasil."))
    qs.append(radio("endereco_correspondencia_igual", "endereco_contato",
                     "O endereço acima é para onde seu passaporte deve ser enviado após o processo?",
                     SIM_NAO))
    qs.append(text("correspondencia_rua", "endereco_contato",
                    "Endereço de correspondência — Rua/Avenida, número e complemento",
                    show_if=SI_ENDERECO_CORRESP_DIFERENTE))
    qs.append(text("correspondencia_bairro", "endereco_contato", "Bairro (correspondência)",
                    show_if=SI_ENDERECO_CORRESP_DIFERENTE))
    qs.append(text("correspondencia_cidade", "endereco_contato", "Cidade (correspondência)",
                    show_if=SI_ENDERECO_CORRESP_DIFERENTE))
    qs.append(text("correspondencia_estado", "endereco_contato", "Estado (correspondência)",
                    show_if=SI_ENDERECO_CORRESP_DIFERENTE))
    qs.append(text("correspondencia_cep", "endereco_contato", "CEP (correspondência)",
                    show_if=SI_ENDERECO_CORRESP_DIFERENTE))
    qs.append(text("telefone_residencial", "endereco_contato", "Telefone residencial com DDD"))
    qs.append(text("telefone_celular", "endereco_contato", "Telefone celular com DDD"))
    qs.append(text("telefone_comercial", "endereco_contato",
                    'Telefone do trabalho ou escola (se estudante) com DDD (ou "Não se aplica")', required=False))
    qs.append(text("email", "endereco_contato", "E-mail"))
    qs.append(yesno("outros_telefones_5anos", "endereco_contato",
                     "Você utilizou outros números de telefone nos últimos 5 anos?"))
    qs.append(text("outros_telefones_quais", "endereco_contato", "Quais números", show_if=SI_OUTROS_TELEFONES))
    qs.append(yesno("outros_emails_5anos", "endereco_contato",
                     "Você utilizou outros endereços de e-mail nos últimos 5 anos?"))
    qs.append(text("outros_emails_quais", "endereco_contato", "Quais e-mails", show_if=SI_OUTROS_EMAILS))
    qs.append(yesno("usa_redes_sociais", "endereco_contato",
                     "Você usou alguma plataforma de rede social nos últimos 5 anos?",
                     hint="Não informe senhas, só o nome de usuário/identificador de cada plataforma."))
    qs.append(checkbox_group(
        "redes_sociais_plataformas", "endereco_contato", "Quais plataformas (marque todas que usou)",
        [("facebook", "Facebook"), ("instagram", "Instagram"), ("linkedin", "LinkedIn"),
         ("youtube", "YouTube"), ("twitter_x", "Twitter/X"), ("tiktok", "TikTok"),
         ("outra", "Outra")], show_if=SI_REDE_SOCIAL_OUTRAS))
    qs.append(text("redes_sociais_usuarios", "endereco_contato",
                    "Para cada plataforma marcada acima, informe o nome de usuário (um por linha)",
                    show_if=SI_REDE_SOCIAL_OUTRAS))
    qs.append(yesno("outra_presenca_online", "endereco_contato",
                     "Deseja informar presença em outros sites/apps (fora redes sociais) usados nos últimos 5 anos "
                     "para criar ou compartilhar conteúdo?"))
    qs.append(text("outra_presenca_online_quais", "endereco_contato", "Quais", show_if=SI_OUTRA_PRESENCA_ONLINE))

    # ---------------------------------------------------------------
    # 3. Passaporte
    # ---------------------------------------------------------------
    qs.append(text("passaporte_numero", "passaporte", "Número do passaporte"))
    qs.append(text("passaporte_book_number", "passaporte",
                    'Número de controle do passaporte (Book Number) -- não se aplica a passaporte brasileiro',
                    required=False))
    qs.append(text("passaporte_cidade_emissao", "passaporte", "Cidade onde foi emitido"))
    qs.append(text("passaporte_estado_emissao", "passaporte", "Estado onde foi emitido"))
    qs.append(text("passaporte_pais_emissao", "passaporte", "País onde foi emitido", required=False,
                    hint="Deixe em branco se for o Brasil."))
    qs.append(date_q("passaporte_data_emissao", "passaporte", "Data de emissão"))
    qs.append(date_q("passaporte_data_expiracao", "passaporte", "Data de expiração/vencimento"))
    qs.append(yesno("passaporte_perdido", "passaporte", "Já teve algum passaporte roubado ou perdido?"))
    qs.append(text("passaporte_perdido_numero", "passaporte",
                    'Número do passaporte perdido/roubado (escreva "Não sei" se não souber)',
                    show_if=SI_PASSAPORTE_PERDIDO))
    qs.append(text("passaporte_perdido_pais", "passaporte", "País que emitiu esse passaporte",
                    show_if=SI_PASSAPORTE_PERDIDO))
    qs.append(text("passaporte_perdido_detalhes", "passaporte",
                    "Mês/ano aproximado e como perdeu ou foi roubado", show_if=SI_PASSAPORTE_PERDIDO))

    # ---------------------------------------------------------------
    # 4. Viagem aos EUA
    # ---------------------------------------------------------------
    qs.append(yesno("aplicante_principal", "viagem",
                     "Você é o aplicante principal deste pedido de visto?",
                     hint="Você NÃO é o aplicante principal se estiver viajando para acompanhar cônjuge/parente "
                          "que vai trabalhar (H1/L1) ou estudar (F/J/M/Q) -- isso é o \"visto de acompanhante\"."))
    qs.append(text("aplicante_principal_sobrenome", "viagem", "Sobrenome do aplicante principal",
                    show_if=SI_NAO_APLICANTE_PRINCIPAL))
    qs.append(text("aplicante_principal_nome", "viagem", "Nome do aplicante principal",
                    show_if=SI_NAO_APLICANTE_PRINCIPAL))
    qs.append(text("aplicante_principal_categoria", "viagem",
                    "Categoria do visto do aplicante principal e, se souber, número da petição/SEVIS ID",
                    show_if=SI_NAO_APLICANTE_PRINCIPAL))

    qs.append(radio("motivo_viagem_b1b2", "viagem", "Finalidade da viagem", [
        ("negocios", "Negócios/conferência (B1)"), ("turismo", "Turismo/visita familiar (B2)"),
        ("negocios_turismo", "Negócios e turismo (B1/B2)"), ("fronteira", "Visto de fronteira (BCC)"),
        ("outro", "Outro"),
    ], show_if=SI_B1B2))
    qs.append(text("motivo_viagem_b1b2_outro", "viagem", "Especifique a finalidade",
                    show_if={"question": "motivo_viagem_b1b2", "equals": "outro"}))

    qs.append(text("f1f2_nome_escola", "viagem", "Nome da instituição de ensino nos EUA", show_if=SI_F1F2))
    qs.append(text("f1f2_endereco_escola", "viagem", "Endereço completo da instituição de ensino", show_if=SI_F1F2))
    qs.append(text("f1f2_sevis_id", "viagem", "Número do SEVIS ID (do formulário I-20)", show_if=SI_F1F2))
    qs.append(text("f1f2_curso", "viagem", "Curso/programa pretendido", show_if=SI_F1F2))
    qs.append(date_q("f1f2_data_inicio_curso", "viagem", "Data de início do curso/programa", show_if=SI_F1F2))

    qs.append(yesno("tem_plano_viagem", "viagem", "Você já tem planos específicos de viagem (passagens compradas)?"))
    qs.append(date_q("viagem_data_chegada", "viagem", "Data de chegada nos EUA", show_if=SI_TEM_PLANO_VIAGEM))
    qs.append(text("viagem_voo_chegada", "viagem", "Número do voo de desembarque", required=False,
                    show_if=SI_TEM_PLANO_VIAGEM))
    qs.append(text("viagem_cidade_desembarque", "viagem", "Cidade de desembarque nos EUA", show_if=SI_TEM_PLANO_VIAGEM))
    qs.append(date_q("viagem_data_saida", "viagem", "Data de saída dos EUA", show_if=SI_TEM_PLANO_VIAGEM))
    qs.append(text("viagem_cidade_saida", "viagem", "Cidade de onde vai partir ao sair dos EUA",
                    show_if=SI_TEM_PLANO_VIAGEM))
    qs.append(text("viagem_locais_visitar", "viagem", "Outras cidades/estados que pretende visitar",
                    required=False, show_if=SI_TEM_PLANO_VIAGEM))
    qs.append(date_q("viagem_data_chegada_aproximada", "viagem", "Data aproximada de chegada nos EUA",
                      show_if={"question": "tem_plano_viagem", "equals": "nao"}))
    qs.append(text("viagem_tempo_permanencia_pretendido", "viagem",
                    "Tempo de permanência pretendido (em dias/meses)",
                    show_if={"question": "tem_plano_viagem", "equals": "nao"}))
    qs.append(text("viagem_endereco_eua_pretendido", "viagem",
                    "Endereço pretendido nos EUA (hotel -- não precisa de reserva -- ou residência de amigos, "
                    "com no mínimo cidade e estado)", show_if={"question": "tem_plano_viagem", "equals": "nao"}))

    qs.append(radio("quem_paga_viagem", "viagem", "Quem vai pagar a viagem?", [
        ("proprios_recursos", "Recursos próprios — eu mesmo(a) pagarei"),
        ("outra_pessoa", "Outra pessoa física"), ("empresa", "Empresa/organização"),
    ]))
    qs.append(text("pagador_nome", "viagem", "Nome completo de quem vai pagar", show_if=SI_QUEM_PAGA_OUTRO))
    qs.append(text("pagador_telefone", "viagem", "Telefone com DDD de quem vai pagar", show_if=SI_QUEM_PAGA_OUTRO))
    qs.append(text("pagador_email", "viagem", 'E-mail de quem vai pagar (ou "Não se aplica")', required=False,
                    show_if=SI_QUEM_PAGA_OUTRO))
    qs.append(text("pagador_parentesco", "viagem", "Parentesco/relação do pagador com você", show_if=SI_QUEM_PAGA_OUTRO))
    qs.append(text("pagador_endereco", "viagem",
                    'Endereço completo de quem vai pagar (ou "mesmo endereço do aplicante")',
                    show_if=SI_QUEM_PAGA_OUTRO))
    qs.append(text("pagador_empresa_nome", "viagem", "Nome completo da empresa/organização pagadora",
                    show_if=SI_QUEM_PAGA_EMPRESA))
    qs.append(text("pagador_empresa_telefone", "viagem", "Telefone com DDD da empresa pagadora",
                    show_if=SI_QUEM_PAGA_EMPRESA))
    qs.append(text("pagador_empresa_relacao", "viagem", "Relação da empresa com você (ex.: empregador)",
                    show_if=SI_QUEM_PAGA_EMPRESA))
    qs.append(text("pagador_empresa_endereco", "viagem",
                    'Endereço completo da empresa pagadora (ou "mesmo endereço do aplicante")',
                    show_if=SI_QUEM_PAGA_EMPRESA))

    # ---------------------------------------------------------------
    # 5. Acompanhantes de viagem
    # ---------------------------------------------------------------
    qs.append(yesno("viaja_acompanhado", "acompanhantes", "Existem outras pessoas viajando com você?"))
    for i in (1, 2, 3, 4):
        qs.append(text(f"acompanhante_{i}_nome", "acompanhantes", f"Acompanhante {i} — nome completo",
                        required=(i == 1), show_if=SI_VIAJA_ACOMPANHADO))
        qs.append(text(f"acompanhante_{i}_parentesco", "acompanhantes", f"Acompanhante {i} — parentesco/relação",
                        required=(i == 1), show_if=SI_VIAJA_ACOMPANHADO))
    qs.append(yesno("viaja_em_grupo", "acompanhantes",
                     "Está viajando com alguma agência de turismo, grupo ou organização?"))
    qs.append(text("viaja_em_grupo_nome", "acompanhantes", "Nome do grupo/agência/organização",
                    show_if={"question": "viaja_em_grupo", "equals": "sim"}))

    # ---------------------------------------------------------------
    # 6. Viagens e vistos anteriores aos EUA
    # ---------------------------------------------------------------
    qs.append(yesno("ja_esteve_eua", "viagens_anteriores", "Você já esteve nos Estados Unidos alguma vez?"))
    for i in (1, 2, 3, 4, 5):
        qs.append(date_q(f"visita_{i}_data_chegada", "viagens_anteriores",
                          f"Viagem anterior {i} — data de chegada", required=(i == 1), show_if=SI_JA_ESTEVE_EUA))
        qs.append(text(f"visita_{i}_tempo_permanencia", "viagens_anteriores",
                        f"Viagem anterior {i} — tempo de permanência (dias/meses)",
                        required=(i == 1), show_if=SI_JA_ESTEVE_EUA))

    qs.append(yesno("tem_habilitacao_eua", "viagens_anteriores",
                     "Você possui (ou já possuiu) carteira de habilitação americana (Driver License)?"))
    qs.append(text("habilitacao_eua_numero", "viagens_anteriores",
                    'Número da licença (escreva "Não sei" se não souber)', show_if=SI_TEM_HABILITACAO_EUA))
    qs.append(text("habilitacao_eua_estado", "viagens_anteriores", "Estado americano emissor",
                    show_if=SI_TEM_HABILITACAO_EUA))

    qs.append(yesno("ja_teve_visto_eua", "viagens_anteriores", "Você já teve um visto americano emitido antes?"))
    qs.append(date_q("visto_anterior_data_emissao", "viagens_anteriores",
                      "Data de emissão do último visto", show_if=SI_JA_TEVE_VISTO))
    qs.append(text("visto_anterior_numero", "viagens_anteriores",
                    "Número do visto (8 dígitos, em vermelho no canto inferior)", show_if=SI_JA_TEVE_VISTO))
    qs.append(text("visto_anterior_tipo", "viagens_anteriores",
                    "Tipo do visto anterior (turismo, negócios, estudante etc.)", show_if=SI_JA_TEVE_VISTO))
    qs.append(yesno("visto_mesmo_tipo", "viagens_anteriores",
                     "Está solicitando o mesmo tipo de visto do anterior?", show_if=SI_JA_TEVE_VISTO))
    qs.append(yesno("visto_mesmo_pais_residencia", "viagens_anteriores",
                     "Está solicitando no mesmo país onde o visto anterior foi emitido e que é sua "
                     "residência principal?", show_if=SI_JA_TEVE_VISTO))
    qs.append(yesno("ja_deu_digitais_10_dedos", "viagens_anteriores",
                     "Alguma vez, ao entrar nos EUA ou obter um visto, colheram suas digitais dos 10 dedos?"))

    qs.extend(yesno_explain("visto_perdido_roubado", "viagens_anteriores",
                             "Você já teve algum visto americano perdido ou roubado?",
                             explain_label="Informe o ano do extravio/roubo"))
    qs.extend(yesno_explain("visto_cancelado_revogado", "viagens_anteriores",
                             "Você já teve algum visto americano cancelado ou revogado?",
                             explain_label="Explique quando, onde e o tipo de visto cancelado"))
    qs.extend(yesno_explain("visto_negado_entrada_negada", "viagens_anteriores",
                             "Alguma vez já lhe negaram um visto americano, negaram sua entrada nos EUA, "
                             "ou retiraram seu cartão de admissão, ou você desistiu de um pedido de entrada?",
                             explain_label="Informe o ano e o motivo alegado"))
    qs.extend(yesno_explain("peticao_imigrante_seu_nome", "viagens_anteriores",
                             "Alguém já deu entrada em uma petição de imigrante em seu nome?",
                             explain_label="Explique de que petição se trata e por quê"))

    # ---------------------------------------------------------------
    # 7. Contato nos EUA
    # ---------------------------------------------------------------
    qs.append(yesno("tem_contato_eua", "contato_eua",
                     "Você possui alguma organização ou pessoa de contato nos EUA (parente, amigo, contato comercial)?"))
    qs.append(text("contato_eua_nome", "contato_eua", "Nome completo do contato", show_if=SI_TEM_CONTATO_EUA))
    qs.append(text("contato_eua_empresa", "contato_eua", "Nome da empresa/organização (se aplicável)",
                    required=False, show_if=SI_TEM_CONTATO_EUA))
    qs.append(text("contato_eua_parentesco", "contato_eua", "Relação/parentesco com você", show_if=SI_TEM_CONTATO_EUA))
    qs.append(text("contato_eua_endereco", "contato_eua", "Endereço completo do contato", show_if=SI_TEM_CONTATO_EUA))
    qs.append(text("contato_eua_telefone", "contato_eua", "Telefone com DDD do contato", show_if=SI_TEM_CONTATO_EUA))
    qs.append(text("contato_eua_email", "contato_eua", 'E-mail do contato (ou "Não se aplica")', required=False,
                    show_if=SI_TEM_CONTATO_EUA))
    qs.append(radio("contato_eua_status", "contato_eua", "Situação migratória do contato nos EUA", [
        ("cidadao", "Cidadão americano"), ("residente_permanente", "Residente permanente legal"),
        ("outro", "Outra/não sei"),
    ], required=False, show_if=SI_TEM_CONTATO_EUA))

    # ---------------------------------------------------------------
    # 8. Família
    # ---------------------------------------------------------------
    qs.append(text("pai_nome", "familia", "Nome completo do pai"))
    qs.append(date_q("pai_data_nascimento", "familia", "Data de nascimento do pai", required=False))
    qs.append(yesno("pai_nos_eua", "familia", "Seu pai se encontra nos EUA?"))
    qs.append(radio("pai_situacao_eua", "familia", "Situação do pai nos EUA", [
        ("cidadao", "Cidadão americano"), ("residente_permanente", "Residente permanente legal"),
        ("nao_imigrante", "Não-imigrante (turista, estudante etc.)"), ("outro", "Outro/não sei"),
    ], show_if=SI_PAI_NOS_EUA))

    qs.append(text("mae_nome", "familia", "Nome completo da mãe"))
    qs.append(date_q("mae_data_nascimento", "familia", "Data de nascimento da mãe", required=False))
    qs.append(yesno("mae_nos_eua", "familia", "Sua mãe se encontra nos EUA?"))
    qs.append(radio("mae_situacao_eua", "familia", "Situação da mãe nos EUA", [
        ("cidadao", "Cidadão americano"), ("residente_permanente", "Residente permanente legal"),
        ("nao_imigrante", "Não-imigrante (turista, estudante etc.)"), ("outro", "Outro/não sei"),
    ], show_if=SI_MAE_NOS_EUA))

    qs.append(yesno("tem_parente_imediato_eua", "familia",
                     "Você possui algum outro parente imediato (não os pais) nos Estados Unidos?"))
    qs.append(text("parente_imediato_nome", "familia", "Nome completo do parente", show_if=SI_TEM_PARENTE_EUA))
    qs.append(text("parente_imediato_parentesco", "familia", "Grau de parentesco", show_if=SI_TEM_PARENTE_EUA))
    qs.append(radio("parente_imediato_status", "familia", "Situação migratória do parente nos EUA", [
        ("cidadao", "Cidadão americano"), ("residente_permanente", "Residente permanente legal"),
        ("outro", "Outra/não sei"),
    ], show_if=SI_TEM_PARENTE_EUA))

    qs.append(text("conjuge_nome", "familia",
                    'Nome completo do cônjuge atual (ou anterior, se divorciado/separado/viúvo). '
                    'Se solteiro(a), escreva "Não se aplica"', show_if=SI_TEM_CONJUGE))
    qs.append(date_q("conjuge_data_nascimento", "familia", "Data de nascimento do cônjuge", required=False,
                      show_if=SI_TEM_CONJUGE))
    qs.append(text("conjuge_nacionalidade", "familia", "Nacionalidade do cônjuge", required=False,
                    show_if=SI_TEM_CONJUGE))
    qs.append(text("conjuge_cidade_nascimento", "familia", "Cidade/estado/país de nascimento do cônjuge",
                    required=False, show_if=SI_TEM_CONJUGE))
    qs.append(text("conjuge_endereco", "familia",
                    'Endereço do cônjuge (ou "mesmo endereço do aplicante")', required=False, show_if=SI_TEM_CONJUGE))
    qs.append(date_q("data_casamento", "familia", "Data de casamento", required=False, show_if=SI_TEM_CONJUGE))
    qs.append(date_q("data_divorcio", "familia", "Data do divórcio (se aplicável)", required=False,
                      show_if=SI_DIVORCIADO_SEPARADO))
    qs.append(text("motivo_fim_casamento", "familia", "Como o casamento terminou (motivo resumido)",
                    required=False, show_if=SI_DIVORCIADO_SEPARADO))

    # ---------------------------------------------------------------
    # 9. Trabalho/escola atual
    # ---------------------------------------------------------------
    qs.append(text("ocupacao_atual", "trabalho_atual",
                    "Ocupação/profissão atual (se desempregado ou estudante, explique)"))
    qs.append(text("empresa_escola_nome", "trabalho_atual", "Nome da empresa ou instituição de ensino"))
    qs.append(text("empresa_escola_cnpj", "trabalho_atual", "CNPJ (caso seja proprietário do negócio)",
                    required=False))
    qs.append(text("empresa_escola_endereco", "trabalho_atual", "Endereço completo da empresa/escola"))
    qs.append(text("empresa_escola_telefone", "trabalho_atual", "Telefone com DDD da empresa/escola"))
    qs.append(date_q("empresa_escola_data_inicio", "trabalho_atual", "Data de início nesse emprego/curso/ocupação"))
    qs.append(text("cargo_funcao", "trabalho_atual", "Cargo/função"))
    qs.append(text("salario_mensal_bruto", "trabalho_atual",
                    'Renda/salário mensal bruto em reais (se estudante ou desempregado, escreva "Não se aplica")'))
    qs.append(text("descricao_atividades", "trabalho_atual",
                    "Breve descrição das atividades profissionais (ou curso/série, se estudante)"))
    qs.append(text("anos_experiencia_area", "trabalho_atual",
                    "Quantos anos de experiência possui na área de atuação/formação?", required=False))
    qs.append(text("carteira_profissional", "trabalho_atual",
                    "Carteira funcional/registro profissional (CREA, CRM, CRP, OAB etc.), se possuir",
                    required=False))

    # ---------------------------------------------------------------
    # 10. Trabalho/escola anteriores
    # ---------------------------------------------------------------
    qs.append(yesno("menos_5_anos_trabalho_atual", "trabalho_anterior",
                     "Você está há menos de 5 anos no seu emprego/ocupação atual?"))
    qs.append(radio("teve_emprego_anterior", "trabalho_anterior",
                     "Teve algum emprego anterior ao atual (nos últimos 5 anos)?", SIM_NAO,
                     show_if=SI_MENOS_5_ANOS_ATUAL))
    for i in (1, 2):
        qs.append(text(f"emprego_anterior_{i}_empresa", "trabalho_anterior",
                        f"Emprego anterior {i} — nome da empresa/instituição", show_if=SI_TRABALHOU_ANTES))
        qs.append(text(f"emprego_anterior_{i}_endereco", "trabalho_anterior",
                        f"Emprego anterior {i} — endereço completo", show_if=SI_TRABALHOU_ANTES))
        qs.append(text(f"emprego_anterior_{i}_telefone", "trabalho_anterior",
                        f"Emprego anterior {i} — telefone com DDD", required=False, show_if=SI_TRABALHOU_ANTES))
        qs.append(text(f"emprego_anterior_{i}_cargo", "trabalho_anterior",
                        f"Emprego anterior {i} — cargo e breve descrição das funções", show_if=SI_TRABALHOU_ANTES))
        qs.append(text(f"emprego_anterior_{i}_supervisor", "trabalho_anterior",
                        f"Emprego anterior {i} — nome completo do supervisor/gerente", required=False,
                        show_if=SI_TRABALHOU_ANTES))
        qs.append(date_q(f"emprego_anterior_{i}_data_admissao", "trabalho_anterior",
                          f"Emprego anterior {i} — data de admissão", show_if=SI_TRABALHOU_ANTES))
        qs.append(date_q(f"emprego_anterior_{i}_data_demissao", "trabalho_anterior",
                          f"Emprego anterior {i} — data de saída", show_if=SI_TRABALHOU_ANTES))

    # ---------------------------------------------------------------
    # 11. Educação
    # ---------------------------------------------------------------
    qs.append(radio("tem_formacao_superior", "educacao",
                     "Possui graduação, MBA, pós-graduação ou curso técnico concluído?", SIM_NAO))
    for i in (1, 2, 3):
        qs.append(text(f"escola_{i}_nome", "educacao", f"Instituição de ensino {i} — nome",
                        required=(i == 1), show_if=SI_TEM_FORMACAO_SUPERIOR))
        qs.append(text(f"escola_{i}_endereco", "educacao", f"Instituição de ensino {i} — endereço completo",
                        required=(i == 1), show_if=SI_TEM_FORMACAO_SUPERIOR))
        qs.append(text(f"escola_{i}_curso", "educacao", f"Instituição de ensino {i} — curso",
                        required=(i == 1), show_if=SI_TEM_FORMACAO_SUPERIOR))
        qs.append(date_q(f"escola_{i}_data_inicio", "educacao", f"Instituição de ensino {i} — mês/ano de início",
                          required=(i == 1), show_if=SI_TEM_FORMACAO_SUPERIOR))
        qs.append(date_q(f"escola_{i}_data_conclusao", "educacao",
                          f"Instituição de ensino {i} — mês/ano de conclusão",
                          required=(i == 1), show_if=SI_TEM_FORMACAO_SUPERIOR))
    qs.append(text("idiomas_fluentes", "educacao", "Idiomas que fala fluentemente, além do português",
                    required=False))

    # ---------------------------------------------------------------
    # 12. Informações adicionais
    # ---------------------------------------------------------------
    qs.append(yesno("viajou_outros_paises_5anos", "info_adicional",
                     "Você viajou para outros países (fora os EUA) nos últimos 5 anos?"))
    qs.append(text("viajou_outros_paises_quais", "info_adicional", "Quais países", show_if=SI_VIAJOU_OUTROS_PAISES))
    qs.append(radio("pertence_cla_tribo", "info_adicional", "Pertence a algum clã ou tribo?", SIM_NAO))
    qs.append(radio("participa_caridade", "info_adicional",
                     "Já pertenceu, contribuiu ou trabalhou para alguma organização de caridade ou social?", SIM_NAO))
    qs.append(text("participa_caridade_nome", "info_adicional", "Nome da organização", show_if=SI_PARTICIPA_CARIDADE))
    qs.extend(yesno_explain("habilidade_armas_explosivos", "info_adicional",
                             "Possui alguma habilidade ou treinamento específico em armas de fogo, explosivos, "
                             "ou experiência nuclear, biológica ou química?"))
    qs.append(radio("servico_militar", "info_adicional", "Você já prestou serviço militar?", SIM_NAO))
    qs.append(text("servico_militar_pais", "info_adicional", "País onde prestou o serviço", show_if=SI_SERVICO_MILITAR))
    qs.append(text("servico_militar_batalhao", "info_adicional", "Batalhão/tipo de serviço/ramo das forças armadas",
                    show_if=SI_SERVICO_MILITAR))
    qs.append(text("servico_militar_patente", "info_adicional", "Posição/patente", show_if=SI_SERVICO_MILITAR))
    qs.append(text("servico_militar_especialidade", "info_adicional", "Especialidade militar", required=False,
                    show_if=SI_SERVICO_MILITAR))
    qs.append(date_q("servico_militar_data_inicio", "info_adicional", "Data de início do serviço",
                      show_if=SI_SERVICO_MILITAR))
    qs.append(date_q("servico_militar_data_fim", "info_adicional", "Data de término do serviço",
                      show_if=SI_SERVICO_MILITAR))
    qs.extend(yesno_explain("unidade_paramilitar", "info_adicional",
                             "Já serviu, foi membro, ou esteve envolvido com uma unidade paramilitar, unidade de "
                             "vigilantes, grupo rebelde, grupo de guerrilha, ou organização insurgente?"))

    # ---------------------------------------------------------------
    # 13. Segurança e antecedentes (mesma lista do DS-160 oficial)
    # ---------------------------------------------------------------
    seguranca_perguntas = [
        ("doenca_transmissivel", "Você tem uma doença transmissível de importância para a saúde pública, "
                                  "como tuberculose (TB)?"),
        ("disturbio_mental_fisico", "Você tem um distúrbio mental ou físico que represente ou possa representar "
                                     "uma ameaça para a segurança ou bem-estar de si mesmo ou de outros?"),
        ("viciado_drogas", "Você é ou já foi viciado(a) em drogas?"),
        ("preso_condenado", "Alguma vez você já foi preso(a) ou condenado(a) por qualquer ofensa ou crime, "
                             "mesmo que objeto de indulto, anistia ou ação similar?"),
        ("violou_substancias_controladas", "Alguma vez você violou, ou participou de conspiração para violar, "
                                            "qualquer lei relativa a substâncias controladas?"),
        ("prostituicao", "Você vem para os EUA para exercer prostituição/comercialização ilegal, ou esteve "
                          "envolvido(a) em prostituição ou na busca de prostitutas nos últimos 10 anos?"),
        ("lavagem_dinheiro", "Alguma vez você já esteve envolvido(a) ou procurou se envolver em lavagem de dinheiro?"),
        ("trafico_pessoas_cometeu", "Você já cometeu ou conspirou para cometer uma ofensa de tráfico de pessoas "
                                     "nos Estados Unidos ou fora deles?"),
        ("trafico_pessoas_ajudou", "Você já ajudou, incitou, ou conspirou conscientemente com alguém que cometeu "
                                    "ou conspirou para cometer tráfico de pessoas?"),
        ("trafico_pessoas_beneficiou", "Você é cônjuge, filho(a) de uma pessoa que cometeu tráfico de pessoas e, "
                                        "nos últimos 5 anos, se beneficiou conscientemente dessas atividades?"),
        ("espionagem_sabotagem", "Você procurará se envolver em espionagem, sabotagem, violação de controle de "
                                  "exportação, ou qualquer outra atividade ilegal nos Estados Unidos?"),
        ("terrorismo", "Você procurará se envolver em atividades terroristas nos EUA, ou já está envolvido(a) "
                        "com atividades terroristas?"),
        ("apoio_financeiro_terrorista", "Alguma vez você já prestou ou pretendeu prestar apoio financeiro ou "
                                         "outro tipo de apoio a terroristas ou organizações terroristas?"),
        ("membro_organizacao_terrorista", "Você é membro ou representante de uma organização terrorista?"),
        ("genocidio", "Alguma vez você já ordenou, incitou, esteve comprometido, assistiu ou participou de genocídio?"),
        ("tortura", "Alguma vez você já cometeu, ordenou, incitou, assistiu ou participou de atos de tortura?"),
        ("execucoes_violencia", "Você já cometeu, ordenou, incitou ou participou de execuções extrajudiciais, "
                                 "assassinatos políticos, ou outros atos de violência?"),
        ("criancas_soldado", "Você já se envolveu no recrutamento ou uso de crianças soldado?"),
        ("liberdade_religiosa", "Alguma vez você foi responsável, direta ou indiretamente, por graves violações "
                                 "da liberdade religiosa?"),
        ("controle_populacional_forcado", "Você já esteve diretamente envolvido no estabelecimento ou fiscalização "
                                           "de controles populacionais forçando aborto ou esterilização contra "
                                           "a livre vontade de alguém?"),
        ("transplante_orgaos_coercitivo", "Você já esteve diretamente envolvido no transplante coercitivo de "
                                           "órgãos humanos ou tecidos corporais?"),
        ("audiencia_deportacao", "Alguma vez você já foi objeto de uma audiência de deportação ou remoção?"),
        ("fraude_visto_beneficio", "Alguma vez você já procurou obter, ou ajudou terceiros a obter, um visto ou "
                                    "qualquer benefício de imigração dos EUA por fraude, falsa declaração ou "
                                    "outros meios ilícitos?"),
        ("audiencia_inadmissibilidade", "Você participou de uma audiência sobre inadmissibilidade nos últimos "
                                         "cinco anos?"),
        ("overstay_violacao_visto", "Você já ultrapassou o prazo concedido por um funcionário de imigração, "
                                     "violando os termos de um visto americano?"),
        ("custodia_crianca_fora_eua", "Alguma vez você já manteve fora dos EUA uma criança cidadã americana, "
                                       "separada da pessoa com a guarda legal por um tribunal dos EUA?"),
        ("votou_ilegalmente_eua", "Você já votou nos Estados Unidos em violação de qualquer lei ou regulamento?"),
        ("renuncia_cidadania_impostos", "Alguma vez você já renunciou à cidadania americana com a finalidade de "
                                         "evitar o pagamento de impostos?"),
        ("escola_publica_f_sem_reembolso", "Você já frequentou uma escola pública como estudante (F) ou uma "
                                            "escola secundária pública, depois de 30 de novembro de 1996, sem "
                                            "reembolsar a escola pelo custo do ensino?"),
    ]
    for qid, label in seguranca_perguntas:
        qs.extend(yesno_explain(qid, "seguranca", label))

    return qs


def build():
    questionnaire = {
        "form": "ds160",
        "title": "Rascunho — Visto Americano (DS-160)",
        "description": (
            "Rascunho para pedido de visto de não-imigrante (B1/B2 turismo/negócios ou "
            "F1/F2 estudante) junto ao Consulado Americano. As respostas abaixo serão "
            "usadas pela equipe da Saes Professional Services para preencher o DS-160 "
            "oficial no sistema do Departamento de Estado (CEAC) -- não existe PDF "
            "oficial para este formulário, ele só existe online. Responda com atenção: "
            "nenhum campo pode ficar em branco no DS-160 real, e qualquer erro pode "
            "atrasar ou comprometer seu processo."
        ),
        "sections": SECTIONS,
        "questions": build_questions(),
    }
    out_path = Path(__file__).resolve().parent.parent / "data" / "questionnaires" / "ds160.json"
    out_path.write_text(json.dumps(questionnaire, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gerado {out_path} com {len(questionnaire['questions'])} perguntas.")


if __name__ == "__main__":
    build()
