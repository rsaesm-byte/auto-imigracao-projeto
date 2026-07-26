# -*- coding: utf-8 -*-
"""Textos fixos (não dependentes do formulário) dos dois checklists em PDF,
em português e inglês. Separado de generate_checklist.py só para manter
esse arquivo mais enxuto -- é puro dado, sem lógica."""

STRINGS = {
    "pt": {
        "protocol_title": "Checklist de Protocolo — {form_code}",
        "edition_label": "Edição do formulário",
        "before_sending_title": "1. Antes de enviar",
        "before_sending_1": "Revise o PDF preenchido campo por campo — compare com seus "
            "documentos originais (passaporte, certidões, cartão de "
            "residência) antes de imprimir.",
        "before_sending_2": "Confirme que está usando a edição do formulário listada acima "
            "— o USCIS rejeita formulários com edição vencida. Verifique a "
            "data mais recente em <a href='{official_url}' color='#3355aa'>{official_url}</a>.",
        "before_sending_3": "Reúna os documentos de apoio exigidos pelas instruções oficiais "
            "(<a href='{instructions_url}' color='#3355aa'>instruções do formulário</a>) "
            "— este checklist cobre apenas assinatura, envio e acompanhamento, "
            "não a lista de anexos.",

        "who_signs_title": "2. Quem precisa assinar e onde",
        "col_who": "Quem", "col_where": "Onde (no formulário)", "col_when": "Quando é obrigatório",
        "row_applicant": "Requerente / Peticionário(a) — você",
        "row_applicant_when": "Sempre obrigatório.",
        "row_spouse": "Cônjuge (co-requerente)",
        "row_spouse_when": "Apenas se o cônjuge também estiver peticionando junto (veja as "
            "instruções do formulário).",
        "row_interpreter": "Intérprete",
        "row_interpreter_when": "Apenas se alguém traduziu o formulário e as perguntas para você "
            "em outro idioma.",
        "row_preparer": "Preparador(a) (advogado(a) ou terceiro)",
        "row_preparer_when": "Apenas se alguém além de você preencheu o formulário em seu nome.",
        "who_signs_footnote": "Cada pessoa assina apenas a sua própria seção. Um advogado ou "
            "preparador NÃO pode assinar a seção do requerente, e o requerente "
            "não deve assinar pelo intérprete ou preparador.",

        "sign_correctly_title": "3. Como assinar corretamente",
        "sign_alert": "<b>AVISO — Nova regra do USCIS em vigor a partir de 10/07/2026:</b> "
            "assinaturas inválidas agora podem levar ao INDEFERIMENTO do pedido "
            "mesmo depois de aceito e processado (antes, só era rejeitado na "
            "triagem inicial) — com perda da taxa paga. Siga as regras abaixo "
            "com atenção redobrada.",
        "sign_valid": "<b>Válido:</b> assinatura original feita à mão, à caneta (tinta "
            "\"molhada\"), pela própria pessoa. Depois de assinado à mão, "
            "pode enviar o original, ou uma cópia digitalizada/xerocada/fax "
            "dessa página — desde que a assinatura original a caneta exista "
            "e seja guardada com você.",
        "sign_fresh": "<b>Cada protocolo exige sua própria assinatura nova.</b> Não "
            "reaproveite uma página já assinada de outro formulário nem uma "
            "imagem de assinatura salva — mesmo sendo a mesma pessoa "
            "assinando várias petições, cada uma precisa de uma assinatura "
            "física própria.",
        "sign_invalid": "<b>NÃO é válido:</b> nome digitado na linha de assinatura, "
            "carimbo, assinatura eletrônica/software (DocuSign, Adobe Sign "
            "etc. — isso só vale para os formulários feitos para "
            "protocolo 100% online, não para PDF impresso), ou qualquer "
            "pessoa assinando em nome de outra (advogado assinando pelo "
            "requerente, por exemplo).",
        "sign_online_note": "Se o protocolo for feito online pelo my.uscis.gov, a "
            "assinatura eletrônica própria do sistema USCIS é aceita — esta "
            "regra de \"tinta molhada\" vale para protocolo em papel.",

        "sign_date_title": "4. Data da assinatura",
        "sign_date_body": "Escreva a data no formato MM/DD/AAAA (padrão americano — mês "
            "primeiro), ao lado da sua assinatura. A data deve ser o dia real em "
            "que você assinou o documento, não a data de envio pelo correio. Se "
            "o formulário demorar para ser enviado depois de assinado, "
            "reconfirme se as instruções oficiais exigem assinar novamente perto "
            "da data de envio.",

        "fee_title": "5. Taxa de protocolo",
        "col_method": "Forma de envio", "col_amount": "Valor",
        "fee_online": "Online (my.uscis.gov)", "fee_paper": "Papel (correio)",
        "fee_reduced": "Taxa reduzida (se elegível)",
        "payable_to_label": "Pagável a",
        "fee_confirm": "Confirme o valor atual antes de enviar em "
            "<a href='https://www.uscis.gov/g-1055' color='#3355aa'>uscis.gov/g-1055</a> "
            "— taxas mudam periodicamente.",

        "where_send_title": "6. Onde e como enviar",
        "where_online": "<b>Online:</b> {online_url} — crie ou acesse sua conta myUSCIS e "
            "siga o protocolo eletrônico.",
        "where_paper": "<b>Papel (correio):</b> o endereço exato do lockbox depende do "
            "seu estado/localização e da categoria de elegibilidade "
            "selecionada, e pode mudar com o tempo — NÃO use um endereço "
            "antigo ou de memória. Confirme o endereço correto para o seu "
            "caso específico na página oficial do formulário "
            "(<a href='{official_url}' color='#3355aa'>{official_url}</a>, aba \"Direct Filing "
            "Addresses\" / \"Where to File\") antes de enviar.",

        "processing_title": "7. Tempo de processamento",
        "processing_body": "O tempo de processamento varia por categoria e pelo centro/escritório "
            "do USCIS responsável pelo seu caso, e muda mês a mês — por isso não "
            "é um número fixo aqui. Confirme o tempo estimado atual em "
            "<a href='{processing_url}' color='#3355aa'>{processing_url}</a>: "
            "selecione o formulário {form_code} e o centro/escritório indicado "
            "no seu Recibo (Form I-797, Notice of Action) depois que o "
            "protocolo for aceito.",

        "status_title": "8. Como acompanhar o status do caso",
        "status_1": "Depois que o USCIS aceitar seu protocolo, você recebe um "
            "<b>Número de Recibo</b> (Receipt Number) de 13 caracteres — 3 "
            "letras identificando o centro de processamento (ex.: MSC, EAC, "
            "WAC, LIN, SRC, NBC, IOE) seguidas de 10 dígitos — impresso no "
            "canto superior do Formulário I-797, Notice of Action, enviado "
            "por correio (ou disponível na sua conta myUSCIS, se protocolou "
            "online).",
        "status_2": "Verifique o status a qualquer momento em "
            "<a href='https://egov.uscis.gov/casestatus/landing.do' color='#3355aa'>"
            "egov.uscis.gov/casestatus</a>, digitando o número de recibo "
            "(sem espaços ou hífens).",
        "status_3": "Se protocolou pelo my.uscis.gov, o status e as atualizações "
            "também aparecem diretamente na sua conta, com notificações por "
            "e-mail/SMS opcionais.",
        "status_4": "Guarde o número de recibo — ele é necessário para consultar o "
            "status, ligar para o Contact Center do USCIS, e para vincular "
            "protocolos relacionados (ex.: I-765/I-131 pendentes junto com "
            "um I-485).",

        "address_title": "9. Se você se mudar depois de protocolar",
        "address_alert": "<b>Por lei (INA 265/266(b)), você é obrigado a informar qualquer "
            "mudança de endereço ao USCIS em até 10 dias após se mudar</b> — "
            "isso vale mesmo com o processo já protocolado e pendente, e "
            "mesmo que você já tenha informado o novo endereço em outro "
            "processo. Em 2025 o DHS reforçou publicamente que vai fiscalizar "
            "essa exigência com mais rigor.",
        "address_online": "<b>Online (recomendado):</b> pela sua conta USCIS "
            "(my.uscis.gov) em "
            "<a href='https://www.uscis.gov/addresschange' color='#3355aa'>"
            "uscis.gov/addresschange</a>. <b>Importante:</b> ao mudar o "
            "endereço pela conta, informe também o número de recibo de "
            "CADA processo pendente — só atualizar o endereço \"geral\" da "
            "conta não atualiza automaticamente os processos já protocolados.",
        "address_paper": "<b>Por papel:</b> Formulário AR-11 (Alien's Change of "
            "Address Card) pelo correio, se preferir não usar a conta "
            "online — também cumpre a exigência legal.",
        "address_consequence": "<b>Consequência de não informar:</b> multa de até $200 e/ou "
            "até 30 dias de prisão (contravenção classe B, INA 266(b)), "
            "além do risco muito mais comum na prática de perder "
            "correspondências importantes do USCIS — aviso de entrevista, "
            "pedido de mais evidência (RFE), ou a própria decisão do caso "
            "— o que pode causar atraso ou até negação por não resposta a tempo.",

        "protocol_footer": "Este checklist é um guia de apoio e não substitui as instruções "
            "oficiais do formulário nem aconselhamento jurídico. Taxas, "
            "endereços e tempos de processamento mudam — sempre reconfirme em "
            "uscis.gov antes de protocolar.",

        "documents_title": "Checklist de Documentos de Suporte — {form_code}",
        "documents_subtitle": "Documentos recomendados para anexar ao seu formulário, com base "
            "no que você respondeu no questionário.",
        "documents_always_title": "Documentos exigidos de todos os requerentes",
        "documents_specific_title": "Documentos específicos para o seu caso",
        "documents_no_match": "Nenhum documento adicional específico foi identificado a "
            "partir das suas respostas para este motivo de aplicação — "
            "revise as instruções oficiais do formulário para confirmar se "
            "algo se aplica ao seu caso.",
        "documents_footer": "Esta lista é um guia de apoio baseado nas suas respostas e nas "
            "instruções gerais do formulário — não substitui as instruções "
            "oficiais nem aconselhamento jurídico. Documentos em outro idioma "
            "que não o inglês precisam de tradução completa certificada "
            "(tradutor certificando que é competente para traduzir e que a "
            "tradução é fiel e precisa).",
    },
    "en": {
        "protocol_title": "Filing Checklist — {form_code}",
        "edition_label": "Form edition",
        "before_sending_title": "1. Before you send it",
        "before_sending_1": "Review the filled-out PDF field by field — compare it against "
            "your original documents (passport, certificates, resident card) "
            "before printing.",
        "before_sending_2": "Confirm you're using the form edition listed above — USCIS "
            "rejects forms with an expired edition. Check the current date at "
            "<a href='{official_url}' color='#3355aa'>{official_url}</a>.",
        "before_sending_3": "Gather the supporting evidence required by the official "
            "instructions (<a href='{instructions_url}' color='#3355aa'>form instructions</a>) "
            "— this checklist only covers signing, filing, and tracking, not the "
            "list of attachments.",

        "who_signs_title": "2. Who needs to sign, and where",
        "col_who": "Who", "col_where": "Where (on the form)", "col_when": "When it's required",
        "row_applicant": "Applicant / Petitioner — you",
        "row_applicant_when": "Always required.",
        "row_spouse": "Spouse (co-petitioner)",
        "row_spouse_when": "Only if the spouse is also petitioning jointly (see the form "
            "instructions).",
        "row_interpreter": "Interpreter",
        "row_interpreter_when": "Only if someone translated the form and questions for you "
            "into another language.",
        "row_preparer": "Preparer (attorney or other third party)",
        "row_preparer_when": "Only if someone other than you filled out the form on your behalf.",
        "who_signs_footnote": "Each person signs only their own section. An attorney or "
            "preparer may NOT sign the applicant's section, and the applicant "
            "must not sign for the interpreter or preparer.",

        "sign_correctly_title": "3. How to sign correctly",
        "sign_alert": "<b>NOTICE — New USCIS rule effective 07/10/2026:</b> invalid "
            "signatures can now lead to DENIAL of the request even after it has "
            "been accepted and processed (previously it was only rejected at "
            "intake) — with loss of the fee paid. Follow the rules below with "
            "extra care.",
        "sign_valid": "<b>Valid:</b> an original signature made by hand, in pen (\"wet\" "
            "ink), by the person themselves. After signing by hand, you may "
            "submit the original, or a scanned/photocopied/faxed copy of that "
            "page — as long as the original wet-ink signature exists and is "
            "kept by you.",
        "sign_fresh": "<b>Every filing requires its own fresh signature.</b> Do not reuse a "
            "page already signed for another form, nor a saved signature image "
            "— even if it's the same person signing several petitions, each one "
            "needs its own physical signature.",
        "sign_invalid": "<b>NOT valid:</b> a typed name on the signature line, a stamp, an "
            "electronic/software signature (DocuSign, Adobe Sign, etc. — that "
            "only applies to forms designed for fully online filing, not a "
            "printed PDF), or anyone signing on someone else's behalf (e.g., an "
            "attorney signing for the applicant).",
        "sign_online_note": "If filing online through my.uscis.gov, the system's own "
            "electronic signature is accepted — this \"wet ink\" rule applies to "
            "paper filings.",

        "sign_date_title": "4. Date of signature",
        "sign_date_body": "Write the date in MM/DD/YYYY format (U.S. standard — month "
            "first), next to your signature. The date must be the actual day "
            "you signed the document, not the mailing date. If the form takes "
            "a while to be mailed after signing, double-check whether the "
            "official instructions require signing again closer to the mailing "
            "date.",

        "fee_title": "5. Filing fee",
        "col_method": "Filing method", "col_amount": "Amount",
        "fee_online": "Online (my.uscis.gov)", "fee_paper": "Paper (mail)",
        "fee_reduced": "Reduced fee (if eligible)",
        "payable_to_label": "Payable to",
        "fee_confirm": "Confirm the current fee before mailing at "
            "<a href='https://www.uscis.gov/g-1055' color='#3355aa'>uscis.gov/g-1055</a> "
            "— fees change periodically.",

        "where_send_title": "6. Where and how to send it",
        "where_online": "<b>Online:</b> {online_url} — create or access your myUSCIS "
            "account and follow the electronic filing process.",
        "where_paper": "<b>Paper (mail):</b> the exact lockbox address depends on your "
            "state/location and the eligibility category selected, and can "
            "change over time — do NOT use an old or memorized address. "
            "Confirm the correct address for your specific case on the "
            "form's official page "
            "(<a href='{official_url}' color='#3355aa'>{official_url}</a>, "
            "\"Direct Filing Addresses\" / \"Where to File\" tab) before mailing it.",

        "processing_title": "7. Processing time",
        "processing_body": "Processing time varies by category and by the USCIS service "
            "center or office handling your case, and changes month to month "
            "— so it isn't a fixed number here. Check the current estimated "
            "time at <a href='{processing_url}' color='#3355aa'>{processing_url}</a>: "
            "select Form {form_code} and the office/service center shown on "
            "your Receipt Notice (Form I-797, Notice of Action) once your "
            "filing has been accepted.",

        "status_title": "8. How to track your case status",
        "status_1": "Once USCIS accepts your filing, you'll receive a "
            "<b>Receipt Number</b> — 13 characters: 3 letters identifying the "
            "processing center (e.g., MSC, EAC, WAC, LIN, SRC, NBC, IOE) "
            "followed by 10 digits — printed at the top of Form I-797, Notice "
            "of Action, mailed to you (or available in your myUSCIS account, "
            "if you filed online).",
        "status_2": "Check your status anytime at "
            "<a href='https://egov.uscis.gov/casestatus/landing.do' color='#3355aa'>"
            "egov.uscis.gov/casestatus</a>, by entering the receipt number "
            "(no spaces or dashes).",
        "status_3": "If you filed through my.uscis.gov, status and updates also appear "
            "directly in your account, with optional email/SMS notifications.",
        "status_4": "Keep the receipt number — you'll need it to check status, call the "
            "USCIS Contact Center, and to link related filings (e.g., a "
            "pending I-765/I-131 filed together with an I-485).",

        "address_title": "9. If you move after filing",
        "address_alert": "<b>By law (INA 265/266(b)), you are required to report any "
            "change of address to USCIS within 10 days of moving</b> — this "
            "applies even while your case is already filed and pending, and "
            "even if you've already reported your new address on another case. "
            "In 2025, DHS publicly announced it will enforce this requirement "
            "more strictly.",
        "address_online": "<b>Online (recommended):</b> through your USCIS account "
            "(my.uscis.gov) at "
            "<a href='https://www.uscis.gov/addresschange' color='#3355aa'>"
            "uscis.gov/addresschange</a>. <b>Important:</b> when changing your "
            "address through the account, also enter the receipt number of "
            "EACH pending case — updating only the account's \"general\" "
            "address does not automatically update cases already filed.",
        "address_paper": "<b>By paper:</b> Form AR-11 (Alien's Change of Address Card) by "
            "mail, if you'd rather not use the online account — this also "
            "satisfies the legal requirement.",
        "address_consequence": "<b>Consequence of not reporting it:</b> a fine of up to $200 "
            "and/or up to 30 days in jail (Class B misdemeanor, INA 266(b)), "
            "plus the much more common practical risk of missing important "
            "USCIS correspondence — an interview notice, a Request for "
            "Evidence (RFE), or the case decision itself — which can cause "
            "delays or even a denial for not responding in time.",

        "protocol_footer": "This checklist is a support guide and does not replace the "
            "form's official instructions or legal advice. Fees, addresses, "
            "and processing times change — always double-check at uscis.gov "
            "before filing.",

        "documents_title": "Supporting Documents Checklist — {form_code}",
        "documents_subtitle": "Documents recommended to attach to your form, based on what "
            "you answered in the questionnaire.",
        "documents_always_title": "Documents required from every applicant",
        "documents_specific_title": "Documents specific to your case",
        "documents_no_match": "No additional specific document was identified from your "
            "answers for this application reason — review the form's official "
            "instructions to confirm whether anything applies to your case.",
        "documents_footer": "This list is a support guide based on your answers and the "
            "form's general instructions — it does not replace the official "
            "instructions or legal advice. Documents in a language other than "
            "English need a complete certified translation (the translator "
            "certifying they are competent to translate and that the "
            "translation is complete and accurate).",
    },
}
