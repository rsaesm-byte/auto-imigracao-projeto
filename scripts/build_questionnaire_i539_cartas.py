"""
build_questionnaire_i539_cartas.py — Gera data/questionnaires/i-539-cartas.json.

Formulário SEPARADO do I-539 oficial (não tem PDF/AcroForm associado, não usa
data/mappings/). Coleta duas coisas que não fazem parte do formulário USCIS
em si, mas que a operação da empresa usa para preparar o processo do cliente:

1. Perguntas de narrativa (uma pergunta "servico" própria + ~10-12 perguntas
   por serviço) — usadas pela equipe para redigir a carta pessoal de
   extensão/mudança de status.
2. Dados para até 4 cartas complementares assinadas por terceiros:
   - Carta de Endereço: quando o comprovante de endereço no país de origem
     NÃO está no nome do requerente.
   - Carta de Patrocínio: quando o extrato bancário usado como prova
     financeira NÃO está no nome do requerente.
   - Carta do Empregador: quando o requerente NÃO tem empresa própria no
     país de origem (precisa de uma carta de um empregador).
   - Carta de "quem está cuidando da empresa": quando o requerente TEM
     empresa própria e precisa formalizar quem vai administrá-la durante o
     período fora do país.

Rodado com scripts/run_questionnaire.py normalmente, e consumido por
scripts/generate_cartas_i539.py (não por fill_form.py).
"""
import json
from pathlib import Path

SECTIONS = [
    {"id": "tipo_servico", "title": "Serviço"},
    {"id": "narrativa_eos", "title": "Carta Narrativa — Extensão de Status (EOS)"},
    {"id": "narrativa_b2", "title": "Carta Narrativa — Mudança para Visitante (COS B2)"},
    {"id": "narrativa_f1", "title": "Carta Narrativa — Mudança para Estudante (COS F1)"},
    {"id": "narrativa_f2", "title": "Carta Narrativa — Mudança para Dependente F-2 (COS F2)"},
    {"id": "carta_endereco", "title": "Carta de Endereço"},
    {"id": "carta_patrocinio", "title": "Carta de Patrocínio"},
    {"id": "vinculo_profissional", "title": "Vínculo Profissional no País de Origem"},
    {"id": "carta_empregador", "title": "Carta do Empregador"},
    {"id": "carta_empresa_cuidador", "title": "Carta de Quem Vai Cuidar da Empresa"},
]


def txt(qid, section, label, hint="", required=True, show_if=None):
    d = {"id": qid, "section": section, "label": label, "type": "text", "required": required}
    if hint:
        d["hint"] = hint
    if show_if:
        d["show_if"] = show_if
    return d


def radio(qid, section, label, options, required=True, show_if=None, hint=None):
    d = {"id": qid, "section": section, "label": label, "type": "radio", "required": required,
         "options": [{"value": v, "label": l} for v, l in options]}
    if show_if:
        d["show_if"] = show_if
    if hint:
        d["hint"] = hint
    return d


SI_EOS = {"question": "servico", "equals": "eos"}
SI_B2 = {"question": "servico", "equals": "cos_b2"}
SI_F1 = {"question": "servico", "equals": "cos_f1"}
SI_F2 = {"question": "servico", "equals": "cos_f2"}

# Avisos anexados às perguntas de narrativa que tocam em dinheiro/carreira —
# risco real de o cliente, sem querer, escrever algo que pareça admissão de
# trabalho não autorizado (violação grave de status). Concatenado ao final
# do texto normal da pergunta, não substitui a pergunta.
WORK_WARNING = (
    " ATENÇÃO: NÃO mencione qualquer trabalho nos EUA, nem trabalho remoto "
    "para empresas do Brasil ou de outro país enquanto estiver fisicamente "
    "nos EUA — isso pode ser interpretado como violação do seu status. "
    "Fale apenas sobre poupança pessoal, patrocinador, renda de bens/"
    "investimentos, ou negócio que continua operando no seu país de origem "
    "sem a sua atuação direta enquanto você estiver fora."
)
CAREER_WARNING = (
    " ATENÇÃO: descreva sua carreira APENAS no passado (antes de viajar) ou "
    "no futuro (depois que você retornar) — NÃO diga que vai continuar "
    "trabalhando, nem remotamente, enquanto estiver nos EUA."
)

EOS_QS = [
    ("narr_eos_1", "1. Motivação Inicial",
     "Qual foi o principal motivo que o(a) trouxe aos Estados Unidos inicialmente? Havia um propósito específico, como turismo, trabalho ou outra atividade?"),
    ("narr_eos_2", "2. Histórico de Permanência nos EUA",
     "Desde que chegou aos EUA, quais lugares você visitou e por que escolheu esses destinos? Você se envolveu em alguma atividade ou evento marcante nesses locais?"),
    ("narr_eos_3", "3. Razões para Estender a Sua Permanência",
     "Por que você deseja estender sua permanência nos Estados Unidos? Quais lugares gostaria de visitar durante o período de extensão de sua estadia?"),
    ("narr_eos_4", "4. Impacto no Retorno ao País de Origem",
     "Como esse período prolongado de permanência ou experiência cultural nos EUA beneficiará sua vida pessoal e/ou profissional quando você retornar ao seu país de origem? Há algo específico que você deseja alcançar antes de retornar?"),
    ("narr_eos_5", "5. Interação com a Cultura Americana",
     "Como o contato prolongado com a cultura americana pode enriquecer sua perspectiva pessoal e profissional? Há algo específico na cultura americana que o(a) inspira ou motiva?"),
    ("narr_eos_6", "6. Apoio Financeiro",
     "Quem será responsável pelos custos de sua estadia nos EUA (moradia, alimentação, transporte, etc.)? Qual é o vínculo dessa pessoa com você e qual a capacidade financeira dela para esse suporte?" + WORK_WARNING),
    ("narr_eos_7", "7. Área de Atuação e Impacto na Carreira",
     "Qual é a sua área de atuação profissional em seu país de origem? Como uma estadia prolongada nos EUA poderia agregar valor à sua carreira atual? Que oportunidades você acredita que essa experiência poderia abrir no mercado de trabalho após seu retorno?" + CAREER_WARNING),
    ("narr_eos_8", "8. Formação Acadêmica",
     "Você possui formação superior? Em caso afirmativo, qual é a sua formação e como uma estadia prolongada nos EUA poderia impactar ou complementar sua formação acadêmica?"),
    ("narr_eos_9", "9. Nível de Inglês",
     "Qual é o seu nível de inglês atualmente (básico, intermediário, avançado)? Você já estudou inglês no seu país de origem? Em caso afirmativo, como você acredita que uma estadia mais longa nos EUA poderia ajudar a aprimorar suas habilidades em inglês?"),
    ("narr_eos_10", "10. Impacto Pessoal e Profissional",
     "Como essa extensão poderia impactar positivamente sua vida pessoal? Exemplos: aumento da confiança, ampliação da rede de contatos, experiências culturais."),
    ("narr_eos_11", "11. Planejamento Pós-Retorno",
     "Quais são seus planos imediatos após retornar ao seu país de origem? Você planeja buscar novas qualificações ou se especializar em uma área específica? O contato com a cultura/língua americana influenciou essa decisão?"),
    ("narr_eos_12", "12. Impacto Familiar",
     "Como sua estadia prolongada nos EUA afeta ou é apoiada por sua família/familiares em seu país de origem?"),
]

B2_QS = [
    ("narr_b2_1", "1. Motivação Inicial",
     "Qual foi o principal motivo que levou você a vir para os Estados Unidos inicialmente, no seu status atual? O que te motivou a escolher esse status? Havia um objetivo específico, como aprimorar o inglês, vivenciar uma nova cultura ou outro motivo pessoal ou profissional?"),
    ("narr_b2_2", "2. Histórico de Permanência nos EUA",
     "Desde sua chegada aos Estados Unidos, quais cidades ou estados você visitou durante seu tempo livre? Por que escolheu esses destinos? Algum deles teve um significado especial para você? Participou de alguma atividade cultural, evento ou experiência marcante nesses locais?"),
    ("narr_b2_3", "3. Razão para Mudar seu Status para B-2 (turista)",
     "Por que você deseja alterar seu status atual para B-2 (turista)? Quais são seus planos caso a mudança de status para turista seja aprovada? Que cidades ou pontos turísticos pretende visitar durante esse período?"),
    ("narr_b2_4", "4. Impacto no Retorno ao País de Origem",
     "Como esse período prolongado de permanência ou experiência cultural nos EUA beneficiará sua vida pessoal e/ou profissional quando você retornar ao seu país de origem? Há algo específico que você deseja alcançar antes de retornar?"),
    ("narr_b2_5", "5. Interação com a Cultura Americana",
     "Como o contato prolongado com a cultura americana pode enriquecer sua perspectiva pessoal e profissional? Há algo específico na cultura americana que o(a) inspira ou motiva?"),
    ("narr_b2_6", "6. Apoio Financeiro",
     "Quem será responsável pelos custos de sua estadia nos EUA (moradia, alimentação, etc.)? Qual é o vínculo dessa pessoa com você e qual a capacidade financeira dela para esse suporte?" + WORK_WARNING),
    ("narr_b2_7", "7. Área de Especialização, Formação Acadêmica e Impacto na Carreira",
     "Qual é a sua área de especialização em seu país de origem? Você tem diploma universitário ou alguma qualificação acadêmica formal? Em caso afirmativo, informe o diploma, o campo de estudo e o nome da instituição. Como você acredita que esse período nos EUA beneficiará sua vida pessoal e/ou profissional ao retornar? Mesmo sem estar matriculado em um programa acadêmico, como essa estadia como visitante B-2 pode contribuir para seu desenvolvimento pessoal, habilidades linguísticas ou futuras oportunidades de carreira?" + CAREER_WARNING),
    ("narr_b2_8", "8. Nível de Inglês",
     "Qual é o seu nível de inglês atualmente (básico, intermediário, avançado)? Você já estudou inglês no seu país de origem? Em caso afirmativo, como você acredita que uma estadia mais longa nos EUA poderia ajudar a aprimorar suas habilidades em inglês?"),
    ("narr_b2_9", "9. Planejamento Pós-Retorno",
     "Quais são seus planos imediatos após retornar ao seu país de origem? Como sua estadia prolongada nos EUA afeta ou recebe apoio de sua família/parentes em seu país de origem? Sua exposição ao idioma/cultura americana influenciou essa decisão?"),
    ("narr_b2_10", "10. Impacto Familiar",
     "Como sua estadia prolongada nos EUA afeta ou é apoiada por sua família/familiares em seu país de origem?"),
]

F1_QS = [
    ("narr_f1_1", "1. Motivação Inicial",
     "Qual foi o principal motivo que o(a) trouxe aos Estados Unidos inicialmente? Havia um propósito específico, como turismo, trabalho ou outra atividade?"),
    ("narr_f1_2", "2. Histórico de Permanência nos EUA",
     "Desde que chegou aos EUA, quais lugares você visitou e por que escolheu esses destinos? Você se envolveu em alguma atividade ou evento marcante nesses locais?"),
    ("narr_f1_3", "3. Razão para Estudar nos EUA",
     "Por que você deseja estudar nos Estados Unidos? O que torna o sistema de ensino nos EUA mais vantajoso ou único em comparação ao seu país de origem?"),
    ("narr_f1_4", "4. Impacto no Retorno ao País de Origem",
     "Como essa experiência educacional ou cultural nos EUA irá beneficiar sua vida pessoal e/ou profissional quando retornar ao seu país de origem? Você já tem planos de como aplicar os conhecimentos adquiridos ao voltar?"),
    ("narr_f1_5", "5. Interação com a Cultura Americana",
     "Como o contato prolongado com a cultura americana pode enriquecer sua perspectiva pessoal e profissional? Há algo específico na cultura americana que o(a) inspira ou motiva?"),
    ("narr_f1_6", "6. Apoio Financeiro",
     "Quem será responsável pelos custos de sua estadia nos EUA (moradia, alimentação, estudos, etc.)? Qual é o vínculo dessa pessoa com você e qual a capacidade financeira dela para esse suporte?" + WORK_WARNING),
    ("narr_f1_7", "7. Área de Atuação e Impacto na Carreira",
     "Qual é a sua área de atuação profissional em seu país de origem? Como os estudos nos EUA podem agregar valor à sua carreira atual ou abrir novas oportunidades no mercado de trabalho ao retornar?" + CAREER_WARNING),
    ("narr_f1_8", "8. Formação Acadêmica",
     "Você possui formação superior? Em caso positivo, qual o seu curso de formação e como ele está relacionado aos estudos que deseja realizar nos EUA?"),
    ("narr_f1_9", "9. Nível de Inglês",
     "Qual é o seu nível de inglês atualmente (básico, intermediário, avançado)? Você já estudou inglês no seu país de origem? Se sim, o que acredita que seria diferente ao estudar inglês nos Estados Unidos?"),
    ("narr_f1_10", "10. Impacto Pessoal e Profissional",
     "Como estudar nos EUA pode impactar positivamente sua vida pessoal (ex.: aumento da confiança, networking)? Em sua perspectiva profissional, quais oportunidades acredita que surgirão após completar seus estudos nos EUA?"),
    ("narr_f1_11", "11. Planejamento Pós-Estudos",
     "Quais são seus planos imediatos após concluir seus estudos nos EUA? Você pretende buscar novas qualificações ou se especializar em alguma área específica ao retornar ao seu país?"),
    ("narr_f1_12", "12. Impacto Familiar",
     "Como sua estadia prolongada nos EUA afeta ou é apoiada por sua família/familiares em seu país de origem?"),
]

F2_QS = [
    ("narr_f2_1", "1. Motivação Inicial",
     "Qual foi o principal motivo que o(a) trouxe aos Estados Unidos inicialmente? Seu objetivo era turismo, estudos, intercâmbio, trabalho ou outro motivo específico?"),
    ("narr_f2_2", "2. Histórico de Permanência nos EUA",
     "Desde que chegou aos EUA, quais lugares você visitou e por que escolheu esses destinos? Você se envolveu em alguma atividade ou evento marcante nesses locais?"),
    ("narr_f2_3", "3. Motivo para Solicitar o Status F-2 (Dependente de Estudante)",
     "Por que deseja mudar seu status atual para F-2 (dependente de estudante)? Qual a sua intenção durante esse período como dependente nos EUA?"),
    ("narr_f2_4", "4. Planejamento Pessoal e Familiar",
     "Sua família apoia sua permanência prolongada nos Estados Unidos como dependente? Como essa mudança de status se encaixa nos seus planos pessoais e familiares? Como sua estadia prolongada nos EUA afeta ou é apoiada por sua família/familiares em seu país de origem?"),
    ("narr_f2_5", "5. Impacto Cultural e Pessoal",
     "Como a convivência com a cultura americana pode enriquecer sua vida pessoal? Existe algo na cultura dos EUA que o(a) inspira ou que deseja vivenciar mais profundamente?"),
    ("narr_f2_6", "6. Apoio Financeiro",
     "Quem será o responsável pelos custos da sua estadia nos EUA (moradia, alimentação, plano de saúde, etc.)? Qual a relação dessa pessoa com você e como ela comprova capacidade financeira para este suporte?" + WORK_WARNING),
    ("narr_f2_7", "7. Formação Acadêmica e Profissional",
     "Você possui formação acadêmica (ensino superior ou técnico)? Se sim, qual? Qual é sua área de atuação profissional atualmente? Como acredita que essa experiência nos EUA, mesmo como dependente, pode contribuir para seu crescimento acadêmico ou profissional?" + CAREER_WARNING),
    ("narr_f2_8", "8. Nível de Inglês",
     "Qual é o seu nível atual de inglês (básico, intermediário, avançado)? Já estudou inglês no seu país de origem? Como a permanência nos EUA pode contribuir para o seu desenvolvimento no idioma?"),
    ("narr_f2_9", "9. Benefícios Pessoais e Profissionais",
     "De que forma sua experiência nos EUA pode trazer benefícios pessoais (ex.: aumento da autoconfiança, ampliação de visão de mundo)? Em termos profissionais, que tipo de oportunidades acredita que poderá conquistar após essa vivência?"),
    ("narr_f2_10", "10. Planos Futuros Após a Estadia nos EUA",
     "Quais são seus planos após o término do período como F-2? Pretende retornar ao seu país de origem? Tem planos de continuar os estudos ou buscar outras qualificações?"),
]


def build():
    questions = []

    questions.append(txt(
        "nome_completo_requerente", "tipo_servico",
        "Nome completo do requerente (para quem as cartas serão escritas)",
    ))
    questions.append(radio(
        "servico", "tipo_servico",
        "Para qual serviço você está preparando as cartas complementares?",
        [
            ("eos", "EOS — Extensão de Status"),
            ("cos_f1", "COS F1 — Mudança de Status para Estudante"),
            ("cos_f2", "COS F2 — Mudança de Status para Dependente de F-1"),
            ("cos_b2", "COS B2 — Mudança de Status para Visitante"),
        ],
    ))

    for qid, label, hint in EOS_QS:
        questions.append(txt(qid, "narrativa_eos", label, hint, show_if=SI_EOS))
    for qid, label, hint in B2_QS:
        questions.append(txt(qid, "narrativa_b2", label, hint, show_if=SI_B2))
    for qid, label, hint in F1_QS:
        questions.append(txt(qid, "narrativa_f1", label, hint, show_if=SI_F1))
    for qid, label, hint in F2_QS:
        questions.append(txt(qid, "narrativa_f2", label, hint, show_if=SI_F2))

    # ---- Carta de Endereço ----
    questions.append(radio(
        "endereco_comprovante_proprio", "carta_endereco",
        "O comprovante de endereço recente do seu país de origem está no SEU PRÓPRIO nome?",
        [("sim", "Sim"), ("nao", "Não, está no nome de outra pessoa")],
    ))
    si_end = {"question": "endereco_comprovante_proprio", "equals": "nao"}
    questions += [
        txt("carta_endereco_titular_nome", "carta_endereco", "Nome completo do titular do comprovante de endereço",
            "Pessoa em cujo nome está a conta de água, luz, internet, etc.", show_if=si_end),
        txt("carta_endereco_titular_endereco", "carta_endereco", "Endereço completo (igual ao do comprovante)",
            show_if=si_end),
        txt("carta_endereco_titular_tax_id", "carta_endereco", "Número de identificação fiscal do titular (CPF ou equivalente)",
            required=False, show_if=si_end),
        txt("carta_endereco_titular_doc_id", "carta_endereco", "Número de identificação (RG ou documento equivalente) do titular",
            required=False, show_if=si_end),
        txt("carta_endereco_titular_email", "carta_endereco", "E-mail do titular", required=False, show_if=si_end),
        txt("carta_endereco_titular_telefone", "carta_endereco", "Telefone do titular", required=False, show_if=si_end),
        txt("carta_endereco_titular_cidade_nascimento", "carta_endereco", "Cidade e estado de nascimento do titular",
            required=False, show_if=si_end),
        txt("carta_endereco_titular_parentesco", "carta_endereco", "Grau de parentesco do titular com você",
            "IMPORTANTE: responda em INGLÊS — este texto entra direto na carta em inglês. "
            "Ex.: father, mother, brother, sister, son, daughter, friend, etc.", show_if=si_end),
    ]

    # ---- Carta de Patrocínio ----
    questions.append(radio(
        "patrocinio_terceiro", "carta_patrocinio",
        "Os extratos bancários usados como prova de suporte financeiro estão no nome de outra pessoa (patrocinador)?",
        [("sim", "Sim"), ("nao", "Não, são meus próprios extratos")],
    ))
    si_pat = {"question": "patrocinio_terceiro", "equals": "sim"}
    questions += [
        txt("carta_patrocinio_nome", "carta_patrocinio", "Nome completo do patrocinador", show_if=si_pat),
        txt("carta_patrocinio_email", "carta_patrocinio", "E-mail do patrocinador", show_if=si_pat),
        txt("carta_patrocinio_telefone", "carta_patrocinio", "Telefone do patrocinador", show_if=si_pat),
        txt("carta_patrocinio_endereco", "carta_patrocinio", "Endereço completo do patrocinador", show_if=si_pat),
        txt("carta_patrocinio_parentesco", "carta_patrocinio", "Grau de parentesco do patrocinador com você",
            "IMPORTANTE: responda em INGLÊS — este texto entra direto na carta em inglês. "
            "Ex.: father, mother, brother, sister, spouse, friend, etc.", show_if=si_pat),
        txt("carta_patrocinio_cidade_nascimento", "carta_patrocinio", "Cidade e estado de nascimento do patrocinador",
            required=False, show_if=si_pat),
    ]

    # ---- Vínculo profissional: empresa própria ou empregador ----
    questions.append(radio(
        "tem_empresa_propria", "vinculo_profissional",
        "Você tem uma empresa registrada em seu nome no seu país de origem?",
        [("sim", "Sim, tenho empresa própria"), ("nao", "Não, preciso de uma carta de um empregador")],
    ))

    si_sem_empresa = {"question": "tem_empresa_propria", "equals": "nao"}
    questions += [
        txt("carta_empregador_nome_empresa", "carta_empregador", "Nome da empresa empregadora", show_if=si_sem_empresa),
        txt("carta_empregador_proprietario_nome", "carta_empregador", "Nome completo do proprietário da empresa (empregador)",
            show_if=si_sem_empresa),
        txt("carta_empregador_endereco_empresa", "carta_empregador", "Endereço completo da empresa", show_if=si_sem_empresa),
        txt("carta_empregador_proprietario_cpf", "carta_empregador", "Número de identificação fiscal do proprietário (CPF)",
            show_if=si_sem_empresa),
        txt("carta_empregador_cnpj", "carta_empregador", "Número do CNPJ/registro estadual da empresa (se houver)",
            required=False, show_if=si_sem_empresa),
        txt("carta_empregador_proprietario_email", "carta_empregador", "E-mail do proprietário da empresa", show_if=si_sem_empresa),
        txt("carta_empregador_proprietario_telefone", "carta_empregador", "Telefone do proprietário da empresa", show_if=si_sem_empresa),
        txt("carta_empregador_requerente_cpf", "carta_empregador", "Seu número de identificação fiscal (CPF, do requerente)",
            show_if=si_sem_empresa),
        txt("carta_empregador_proprietario_cidade_nascimento", "carta_empregador", "Cidade e estado de nascimento do proprietário",
            required=False, show_if=si_sem_empresa),
    ]

    si_com_empresa = {"question": "tem_empresa_propria", "equals": "sim"}
    questions += [
        txt("carta_empresa_nome", "carta_empresa_cuidador", "Nome da sua empresa", show_if=si_com_empresa),
        txt("carta_empresa_cnpj", "carta_empresa_cuidador", "Número do CNPJ/registro estadual da empresa", show_if=si_com_empresa),
        txt("carta_empresa_endereco", "carta_empresa_cuidador", "Endereço completo da empresa", show_if=si_com_empresa),
        txt("carta_empresa_proprietario_cpf", "carta_empresa_cuidador", "Seu número de identificação fiscal (CPF), como proprietário",
            show_if=si_com_empresa),
        txt("carta_empresa_cuidador_nome", "carta_empresa_cuidador",
            "Nome completo da pessoa que vai cuidar da empresa enquanto você estiver nos EUA", show_if=si_com_empresa),
        txt("carta_empresa_cuidador_cargo", "carta_empresa_cuidador",
            "Cargo/função dessa pessoa na empresa, ou grau de parentesco com você",
            "IMPORTANTE: responda em INGLÊS — este texto entra direto na carta em inglês. "
            "Ex.: business partner, manager, accountant, spouse, son/daughter, etc.", show_if=si_com_empresa),
        txt("carta_empresa_cuidador_cpf", "carta_empresa_cuidador", "CPF de quem vai cuidar da empresa",
            required=False, show_if=si_com_empresa),
        txt("carta_empresa_cuidador_email", "carta_empresa_cuidador", "E-mail de quem vai cuidar da empresa", show_if=si_com_empresa),
        txt("carta_empresa_cuidador_telefone", "carta_empresa_cuidador", "Telefone de quem vai cuidar da empresa", show_if=si_com_empresa),
        txt("carta_empresa_cuidador_endereco", "carta_empresa_cuidador", "Endereço de quem vai cuidar da empresa",
            required=False, show_if=si_com_empresa),
    ]

    return {
        "form": "I-539-CARTAS",
        "title": "I-539 — Cartas Complementares e Narrativa",
        "description": "Formulário separado do I-539 oficial. Coleta as informações para a carta narrativa pessoal e para até 4 cartas complementares assinadas por terceiros (endereço, patrocínio, empregador, ou responsável pela empresa). Campos marcados com * são obrigatórios.",
        "sections": SECTIONS,
        "questions": questions,
    }


if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent / "data" / "questionnaires" / "i-539-cartas.json"
    data = build()
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"questions: {len(data['questions'])}")
    print(f"sections: {len(data['sections'])}")
    print(f"saved: {out_path}")
