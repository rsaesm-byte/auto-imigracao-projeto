"""Motor de decisão dos quizzes de elegibilidade (data/eligibility_quizzes/).

Diferente do motor de questionário principal (que só coleta dados para
preencher um PDF), aqui cada quiz termina em um VEREDITO: "eligible"
(provavelmente elegível), "needs_review" (pontos de atenção, recomenda-se
falar com a equipe/advogado) ou "not_eligible" (não parece ser o serviço
certo para o caso, ou uma barreira legal conhecida se aplica).

As regras abaixo são resumos informativos de requisitos legais reais (INA,
regulamentos, instruções oficiais da USCIS) -- não são aconselhamento
jurídico, e isso é reforçado tanto no texto de cada mensagem quanto no
aviso fixo da tela de resultado (ver eligibility.py). Em caso de dúvida
sobre uma regra, o veredito pende para "needs_review" em vez de decidir
por conta própria -- é o comportamento seguro tanto para o cliente quanto
para o negócio (ver references/compliance.md)."""
from __future__ import annotations

from datetime import date, timedelta


def _parse_date(raw: str) -> date | None:
    try:
        m, d, y = raw.split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29 de fevereiro em ano não bissexto na data de destino.
        return d.replace(month=2, day=28, year=d.year + years)


def _fmt(d: date, lang: str) -> str:
    return d.strftime("%m/%d/%Y")


def _msg(tone: str, text_pt: str, text_en: str, text_es: str) -> dict:
    return {"tone": tone, "text": text_pt, "text_en": text_en, "text_es": text_es}


# ── Cidadania (N-400) ────────────────────────────────────────────────────────

def evaluate_cidadania(answers: dict) -> dict:
    messages: list[dict] = []
    verdict = "eligible"
    filing_window = None

    if answers.get("idade_18") == "nao":
        return {
            "verdict": "not_eligible",
            "filing_window": None,
            "messages": [_msg(
                "danger",
                "Menores de 18 anos não podem protocolar o N-400 por conta própria — a naturalização exige ter 18 anos ou mais no momento do protocolo.",
                "People under 18 can't file the N-400 on their own — naturalization requires being 18 or older at the time of filing.",
                "Los menores de 18 años no pueden presentar el N-400 por su cuenta — la naturalización exige tener 18 años o más al momento de la solicitud.",
            )],
        }

    if answers.get("crime_grave") == "sim":
        return {
            "verdict": "not_eligible",
            "filing_window": None,
            "messages": [_msg(
                "danger",
                "Uma condenação por assassinato, ou por um crime classificado como \"aggravated felony\" depois de 29/11/1990, é uma barreira PERMANENTE ao bom caráter moral exigido para a naturalização — não há prazo que \"resolva\" isso sozinho. Fale com um advogado de imigração antes de prosseguir.",
                "A conviction for murder, or for a crime classified as an \"aggravated felony\" after 11/29/1990, is a PERMANENT bar to the good moral character required for naturalization — no amount of waiting fixes this on its own. Talk to an immigration attorney before proceeding.",
                "Una condena por homicidio, o por un delito clasificado como \"aggravated felony\" (delito grave agravado) después del 29/11/1990, es una barrera PERMANENTE al buen carácter moral exigido para la naturalización — ningún plazo de espera resuelve esto por sí solo. Hable con un abogado de inmigración antes de continuar.",
            )],
        }

    is_military = answers.get("militar") == "sim"
    is_marriage_based = (
        answers.get("casado_com_cidadao") == "sim"
        and answers.get("conjuge_cidadao_3anos") == "sim"
    )

    if is_military:
        messages.append(_msg(
            "info",
            "Serviço militar tem regras próprias de naturalização (INA 328/329) — em alguns casos (serviço durante período de hostilidades designado) não há exigência mínima de tempo de residência. Recomendamos falar com nossa equipe ou com o Military Help Line da USCIS para aplicar a regra certa ao seu caso, em vez da regra geral de 5/3 anos usada abaixo.",
            "Military service has its own naturalization rules (INA 328/329) — in some cases (service during a designated period of hostilities) there's no minimum residency requirement at all. We recommend talking to our team or the USCIS Military Help Line to apply the right rule to your case, instead of the general 5/3-year rule used below.",
            "El servicio militar tiene sus propias reglas de naturalización (INA 328/329) — en algunos casos (servicio durante un período de hostilidades designado) no existe ningún requisito mínimo de tiempo de residencia. Recomendamos hablar con nuestro equipo o con la Military Help Line de USCIS para aplicar la regla correcta a su caso, en lugar de la regla general de 5/3 años usada a continuación.",
        ))
        verdict = "needs_review"

    gc_date = _parse_date(answers.get("gc_data", ""))
    if gc_date:
        years = 3 if is_marriage_based else 5
        eligible_date = _add_years(gc_date, years)
        window_start = eligible_date - timedelta(days=90)
        today = date.today()
        basis_pt = "cônjuge de cidadão americano (3 anos)" if is_marriage_based else "regra geral (5 anos)"
        basis_en = "spouse of a U.S. citizen (3 years)" if is_marriage_based else "general rule (5 years)"
        basis_es = "cónyuge de ciudadano(a) estadounidense (3 años)" if is_marriage_based else "regla general (5 años)"
        if today >= window_start:
            filing_window = _msg(
                "success",
                f"Você já está dentro da janela de 90 dias — pode protocolar agora! (Base: {basis_pt}; você completa o tempo de residência exigido em {_fmt(eligible_date, 'pt')}.)",
                f"You're already inside the 90-day window — you can file now! (Basis: {basis_en}; you complete the required residency period on {_fmt(eligible_date, 'en')}.)",
                f"Ya está dentro de la ventana de 90 días — ¡puede presentar la solicitud ahora! (Base: {basis_es}; usted completa el tiempo de residencia exigido el {_fmt(eligible_date, 'es')}.)",
            )
        else:
            filing_window = _msg(
                "info",
                f"Você poderá protocolar a partir de {_fmt(window_start, 'pt')} (90 dias antes de completar os {years} anos de residência exigidos, em {_fmt(eligible_date, 'pt')}). Base: {basis_pt}.",
                f"You'll be able to file starting {_fmt(window_start, 'en')} (90 days before completing the {years} years of required residency, on {_fmt(eligible_date, 'en')}). Basis: {basis_en}.",
                f"Usted podrá presentar la solicitud a partir del {_fmt(window_start, 'es')} (90 días antes de completar los {years} años de residencia exigidos, el {_fmt(eligible_date, 'es')}). Base: {basis_es}.",
            )

    if answers.get("viagem_1ano") == "sim":
        verdict = "needs_review"
        messages.append(_msg(
            "danger",
            "Viagens de 1 ano ou mais fora dos EUA sem uma Permissão de Reentrada geralmente QUEBRAM a continuidade da residência exigida — isso pode reiniciar a contagem do tempo mínimo. Fale com um advogado antes de protocolar.",
            "Trips of 1 year or more outside the U.S. without a Reentry Permit generally BREAK the continuous residence requirement — this can reset your required time count. Talk to an attorney before filing.",
            "Los viajes de 1 año o más fuera de los EE. UU. sin un Permiso de Reingreso generalmente ROMPEN la continuidad de residencia exigida — esto puede reiniciar el conteo del tiempo mínimo. Hable con un abogado antes de presentar la solicitud.",
        ))
    elif answers.get("viagem_6meses") == "sim":
        verdict = "needs_review" if verdict == "eligible" else verdict
        messages.append(_msg(
            "warning",
            "Viagens entre 6 meses e 1 ano criam uma presunção de quebra da residência contínua, mas isso pode ser contestado com evidência de que você manteve vínculos nos EUA (moradia, contas, emprego). Reúna essa documentação com antecedência.",
            "Trips between 6 months and 1 year create a presumption that continuous residence was broken, but this can be rebutted with evidence you maintained ties to the U.S. (housing, accounts, employment). Gather that documentation ahead of time.",
            "Los viajes de entre 6 meses y 1 año generan una presunción de ruptura de la residencia continua, pero esto puede refutarse con evidencia de que usted mantuvo vínculos con los EE. UU. (vivienda, cuentas, empleo). Reúna esa documentación con anticipación.",
        ))

    if answers.get("residencia_estado") == "nao":
        verdict = "needs_review"
        messages.append(_msg(
            "warning",
            "É exigido morar no estado (ou distrito da USCIS) onde você vai protocolar por pelo menos 3 meses antes do protocolo.",
            "You're required to have lived in the state (or USCIS district) where you'll file for at least 3 months before filing.",
            "Se exige haber vivido en el estado (o distrito de USCIS) donde va a presentar la solicitud durante al menos 3 meses antes de la solicitud.",
        ))

    if answers.get("prisao_condenacao") == "sim":
        verdict = "needs_review"
        messages.append(_msg(
            "warning",
            "Prisões, detenções, condenações ou programas alternativos no período de bom caráter moral (5 ou 3 anos) precisam ser declarados e documentados (boletins, sentenças, comprovantes de conclusão) — reúna tudo com antecedência e considere consultar um advogado, mesmo que o caso pareça simples.",
            "Arrests, detentions, convictions, or alternative programs within the good-moral-character period (5 or 3 years) need to be disclosed and documented (reports, sentencing records, proof of completion) — gather everything ahead of time and consider consulting an attorney, even if the case seems simple.",
            "Los arrestos, detenciones, condenas o programas alternativos ocurridos dentro del período de buen carácter moral (5 o 3 años) deben declararse y documentarse (partes policiales, sentencias, comprobantes de finalización) — reúna todo con anticipación y considere consultar a un abogado, aunque el caso parezca sencillo.",
        ))

    if answers.get("sexo_masculino") == "sim" and answers.get("selective_service") == "nao":
        verdict = "needs_review"
        messages.append(_msg(
            "warning",
            "Pode ser necessário apresentar uma carta de status do Selective Service e uma justificativa por escrito para explicar por que não se registrou.",
            "You may need to submit a Selective Service status letter and a written explanation of why you didn't register.",
            "Es posible que deba presentar una carta de estatus del Selective Service y una justificación por escrito explicando por qué no se registró.",
        ))

    if not messages and verdict == "eligible":
        messages.append(_msg(
            "success",
            "Não identificamos nenhum ponto de atenção nas suas respostas.",
            "We didn't identify any red flags in your answers.",
            "No identificamos ningún punto de atención en sus respuestas.",
        ))

    return {"verdict": verdict, "filing_window": filing_window, "messages": messages}


# ── GC Removal of Conditions (I-751) ─────────────────────────────────────────

def evaluate_gc_roc(answers: dict) -> dict:
    if answers.get("casamento_origem") == "nao":
        return {
            "verdict": "not_eligible",
            "filing_window": None,
            "messages": [_msg(
                "info",
                "O Formulário I-751 é apenas para quem obteve residência condicional através de casamento. Esse não parece ser o seu caso — fale com nossa equipe para descobrir qual serviço se aplica a você.",
                "Form I-751 is only for those who obtained conditional residency through marriage. That doesn't seem to be your case — talk to our team to find out which service applies to you.",
                "El Formulario I-751 es solo para quienes obtuvieron la residencia condicional a través del matrimonio. Ese no parece ser su caso — hable con nuestro equipo para saber qué servicio se aplica a usted.",
            )],
        }

    if answers.get("condicional") == "nao":
        return {
            "verdict": "not_eligible",
            "filing_window": None,
            "messages": [_msg(
                "info",
                "Este serviço é só para quem tem Green Card CONDICIONAL (validade de 2 anos). Se o seu já é o cartão permanente (10 anos), você não precisa deste formulário.",
                "This service is only for those with a CONDITIONAL Green Card (2-year validity). If yours is already the permanent 10-year card, you don't need this form.",
                "Este servicio es solo para quienes tienen una Green Card CONDICIONAL (validez de 2 años). Si la suya ya es la tarjeta permanente (10 años), no necesita este formulario.",
            )],
        }

    messages: list[dict] = []
    verdict = "eligible"
    filing_window = None

    expiration = _parse_date(answers.get("data_expiracao", ""))
    still_married = answers.get("ainda_casado") == "sim"

    if expiration:
        window_start = expiration - timedelta(days=90)
        today = date.today()
        if still_married:
            if today < window_start:
                filing_window = _msg(
                    "info",
                    f"Ainda não é possível protocolar — a janela de 90 dias abre em {_fmt(window_start, 'pt')} (seu Green Card condicional expira em {_fmt(expiration, 'pt')}).",
                    f"It's not yet possible to file — the 90-day window opens on {_fmt(window_start, 'en')} (your conditional Green Card expires on {_fmt(expiration, 'en')}).",
                    f"Todavía no es posible presentar la solicitud — la ventana de 90 días se abre el {_fmt(window_start, 'es')} (su Green Card condicional vence el {_fmt(expiration, 'es')}).",
                )
            elif today <= expiration:
                filing_window = _msg(
                    "success",
                    f"Você está na janela certa — pode protocolar agora! (Prazo final: {_fmt(expiration, 'pt')}.)",
                    f"You're in the right window — you can file now! (Final deadline: {_fmt(expiration, 'en')}.)",
                    f"Usted está dentro de la ventana correcta — ¡puede presentar la solicitud ahora! (Plazo final: {_fmt(expiration, 'es')}.)",
                )
            else:
                verdict = "needs_review"
                filing_window = _msg(
                    "danger",
                    f"Seu Green Card condicional expirou em {_fmt(expiration, 'pt')} e o protocolo ainda não foi feito — isso é urgente. Fale com um advogado de imigração imediatamente.",
                    f"Your conditional Green Card expired on {_fmt(expiration, 'en')} and filing hasn't happened yet — this is urgent. Talk to an immigration attorney immediately.",
                    f"Su Green Card condicional venció el {_fmt(expiration, 'es')} y la solicitud aún no se ha presentado — esto es urgente. Hable con un abogado de inmigración de inmediato.",
                )

    if not still_married:
        motivo = answers.get("motivo_dispensa")
        valid_waivers = {"falecimento", "divorcio_anulacao", "violencia_domestica", "dificuldade_extrema"}
        if motivo in valid_waivers:
            filing_window = _msg(
                "success",
                "Pedidos de dispensa (waiver) da petição conjunta podem ser protocolados a qualquer momento antes do Green Card condicional expirar — não há janela de 90 dias nesse caso.",
                "Waiver requests for the joint-filing requirement can be filed any time before the conditional Green Card expires — there's no 90-day window in this case.",
                "Las solicitudes de dispensa (waiver) del requisito de petición conjunta pueden presentarse en cualquier momento antes de que venza la Green Card condicional — no hay ventana de 90 días en este caso.",
            )
            messages.append(_msg(
                "info",
                "Reúna evidência de que o casamento foi feito de boa-fé (não apenas para fins de imigração), além da documentação específica do seu motivo de dispensa (ex: certidão de óbito, sentença de divórcio, evidência de violência doméstica).",
                "Gather evidence the marriage was entered in good faith (not just for immigration purposes), plus the documentation specific to your waiver reason (e.g. death certificate, divorce decree, evidence of domestic violence).",
                "Reúna evidencia de que el matrimonio se contrajo de buena fe (no solo con fines migratorios), además de la documentación específica de su motivo de dispensa (por ejemplo: certificado de defunción, sentencia de divorcio, evidencia de violencia doméstica).",
            ))
        else:
            verdict = "needs_review"
            messages.append(_msg(
                "warning",
                "O motivo informado não corresponde a nenhuma das 5 bases oficiais de dispensa reconhecidas pela USCIS (viuvez, divórcio/anulação de boa-fé, violência doméstica, ou dificuldade extrema). Fale com nossa equipe para entender qual caminho se aplica ao seu caso.",
                "The reason given doesn't match any of the 5 official waiver grounds recognized by USCIS (widowhood, good-faith divorce/annulment, domestic violence, or extreme hardship). Talk to our team to understand which path applies to your case.",
                "El motivo indicado no corresponde a ninguna de las 5 bases oficiales de dispensa reconocidas por USCIS (viudez, divorcio/anulación de buena fe, violencia doméstica, o dificultad extrema). Hable con nuestro equipo para entender qué camino se aplica a su caso.",
            ))

    if answers.get("condenacao") == "sim":
        verdict = "needs_review"
        messages.append(_msg(
            "warning",
            "Prisões ou condenações desde que recebeu a residência condicional podem afetar a análise da petição — reúna toda a documentação (boletins, sentenças) e considere consultar um advogado.",
            "Arrests or convictions since receiving conditional residency can affect how the petition is reviewed — gather all documentation (reports, sentencing records) and consider consulting an attorney.",
            "Los arrestos o condenas ocurridos desde que recibió la residencia condicional pueden afectar la evaluación de la petición — reúna toda la documentación (partes policiales, sentencias) y considere consultar a un abogado.",
        ))

    if not messages:
        messages.append(_msg(
            "success",
            "Não identificamos nenhum ponto de atenção nas suas respostas.",
            "We didn't identify any red flags in your answers.",
            "No identificamos ningún punto de atención en sus respuestas.",
        ))

    return {"verdict": verdict, "filing_window": filing_window, "messages": messages}


# ── GC Adjustment of Status (I-130 + I-485 + I-765 + I-130A + I-864 + I-131) ─

_IMMEDIATE_RELATIVE_VALUES = {"conjuge_cidadao", "filho_solteiro_menor21_cidadao", "pai_mae_cidadao"}


def evaluate_gc_aos(answers: dict) -> dict:
    if answers.get("presente_eua") == "nao":
        return {
            "verdict": "not_eligible",
            "filing_window": None,
            "messages": [_msg(
                "info",
                "Ajuste de status exige presença física nos Estados Unidos. Como você está fora do país, o caminho correto é o Green Card via Processamento Consular, não o AOS — confira o quiz de elegibilidade do GC Consular.",
                "Adjustment of status requires physical presence in the United States. Since you're outside the country, the right path is a Green Card via Consular Processing, not AOS — check the GC Consular eligibility quiz.",
                "El ajuste de estatus exige presencia física en los Estados Unidos. Como usted está fuera del país, el camino correcto es la Green Card por Trámite Consular, no el AOS — consulte el cuestionario de elegibilidad de GC Consular.",
            )],
        }

    messages: list[dict] = []
    verdict = "eligible"

    entrada = answers.get("entrada")
    if entrada == "ewi":
        verdict = "needs_review"
        messages.append(_msg(
            "danger",
            "Entrada sem inspeção geralmente IMPEDE o ajuste de status dentro dos EUA, salvo exceções específicas (seção 245(i), VAWA, asilo/refúgio, entre outras). Este é um ponto crítico — fale com um advogado de imigração antes de prosseguir.",
            "Entry without inspection generally BARS adjustment of status inside the U.S., except under specific exceptions (section 245(i), VAWA, asylum/refugee status, among others). This is a critical issue — talk to an immigration attorney before proceeding.",
            "El ingreso sin inspección generalmente IMPIDE el ajuste de estatus dentro de los EE. UU., salvo excepciones específicas (sección 245(i), VAWA, asilo/refugio, entre otras). Este es un punto crítico — hable con un abogado de inmigración antes de continuar.",
        ))
    elif entrada == "nao_sei":
        verdict = "needs_review"
        messages.append(_msg(
            "warning",
            "Confira seu registro de entrada (Formulário I-94) em i94.cbp.dhs.gov para confirmar como e quando você entrou nos EUA — isso é essencial para saber se o ajuste de status é possível no seu caso.",
            "Check your arrival record (Form I-94) at i94.cbp.dhs.gov to confirm how and when you entered the U.S. — this is essential to know whether adjustment of status is possible in your case.",
            "Revise su registro de entrada (Formulario I-94) en i94.cbp.dhs.gov para confirmar cómo y cuándo ingresó a los EE. UU. — esto es esencial para saber si el ajuste de estatus es posible en su caso.",
        ))

    vinculo = answers.get("vinculo")
    is_immediate_relative = vinculo in _IMMEDIATE_RELATIVE_VALUES

    if vinculo == "outro":
        messages.append(_msg(
            "info",
            "Vínculos baseados em emprego, asilo, ou outras categorias especiais têm regras próprias de elegibilidade e disponibilidade de visto — fale com nossa equipe para avaliar o seu caso especificamente.",
            "Employment-based, asylum, or other special-category relationships have their own eligibility and visa-availability rules — talk to our team to evaluate your specific case.",
            "Los vínculos basados en empleo, asilo, u otras categorías especiales tienen sus propias reglas de elegibilidad y disponibilidad de visa — hable con nuestro equipo para evaluar su caso específico.",
        ))
        filing_window = None
    elif is_immediate_relative:
        filing_window = _msg(
            "success",
            "Como parente imediato de cidadão americano, um visto está SEMPRE disponível para você — na maioria dos casos é possível protocolar o I-130 e o I-485 ao mesmo tempo (concurrent filing), sem esperar fila.",
            "As an immediate relative of a U.S. citizen, a visa is ALWAYS available to you — in most cases you can file the I-130 and I-485 at the same time (concurrent filing), with no wait in line.",
            "Como familiar inmediato de un(a) ciudadano(a) estadounidense, siempre hay una visa disponible para usted — en la mayoría de los casos es posible presentar el I-130 y el I-485 al mismo tiempo (concurrent filing), sin esperar en fila.",
        )
    else:
        filing_window = _msg(
            "info",
            "Sua categoria está sujeita ao limite anual de vistos (fila) — você só pode protocolar o I-485 quando sua Data de Prioridade estiver atual no Boletim de Vistos do Departamento de Estado. Consulte o boletim mais recente para saber sua posição na fila.",
            "Your category is subject to the annual visa cap (a waiting line) — you can only file the I-485 once your Priority Date is current on the State Department's Visa Bulletin. Check the latest bulletin to see where you stand in line.",
            "Su categoría está sujeta al límite anual de visas (una fila de espera) — solo puede presentar el I-485 cuando su Fecha de Prioridad esté vigente en el Boletín de Visas del Departamento de Estado. Consulte el boletín más reciente para saber su posición en la fila.",
        )

    if answers.get("peticao_status") == "nao_protocolei":
        messages.append(_msg(
            "info",
            "A petição de base (I-130, ou equivalente) ainda precisa ser protocolada — isso pode ser feito ao mesmo tempo que o I-485 se você for parente imediato, ou precisa ser aprovada primeiro nos demais casos.",
            "The underlying petition (I-130, or equivalent) still needs to be filed — this can happen at the same time as the I-485 if you're an immediate relative, or needs to be approved first in other cases.",
            "La petición base (I-130, o equivalente) todavía debe presentarse — esto puede hacerse al mismo tiempo que el I-485 si usted es familiar inmediato, o debe aprobarse primero en los demás casos.",
        ))

    messages.append(_msg(
        "info",
        "Você também vai precisar do Formulário I-693 (Relatório de Exame Médico e Registro de Vacinação), preenchido por um médico credenciado pela USCIS (civil surgeon) e entregue em envelope selado. Não preenchemos esse formulário, mas fornecemos o máximo de informações sobre ele — procure um médico credenciado pela ferramenta oficial \"Find a Civil Surgeon\" da USCIS (uscis.gov/tools/find-a-civil-surgeon).",
        "You'll also need Form I-693 (Report of Medical Examination and Vaccination Record), completed by a USCIS-designated civil surgeon and delivered in a sealed envelope. We don't complete this form ourselves, but we provide as much guidance about it as possible — find a credentialed doctor through USCIS's official \"Find a Civil Surgeon\" tool (uscis.gov/tools/find-a-civil-surgeon).",
        "También necesitará el Formulario I-693 (Informe de Examen Médico y Registro de Vacunación), completado por un médico designado por USCIS (civil surgeon) y entregado en un sobre sellado. Nosotros no completamos este formulario, pero ofrecemos toda la orientación posible sobre él — busque un médico acreditado a través de la herramienta oficial \"Find a Civil Surgeon\" de USCIS (uscis.gov/tools/find-a-civil-surgeon).",
    ))

    if answers.get("condenacao") == "sim":
        verdict = "needs_review"
        messages.append(_msg(
            "warning",
            "Condenações criminais podem gerar questões de inadmissibilidade — reúna toda a documentação (sentenças, comprovantes de conclusão) e consulte um advogado antes de protocolar.",
            "Criminal convictions can raise inadmissibility issues — gather all documentation (sentencing records, proof of completion) and consult an attorney before filing.",
            "Las condenas penales pueden generar problemas de inadmisibilidad — reúna toda la documentación (sentencias, comprobantes de finalización) y consulte a un abogado antes de presentar la solicitud.",
        ))

    if answers.get("trabalho_nao_autorizado") == "sim":
        if is_immediate_relative:
            messages.append(_msg(
                "info",
                "Trabalho não autorizado geralmente impede o ajuste de status em categorias de preferência familiar, mas parentes imediatos de cidadão americano costumam estar isentos dessa barreira específica (INA 245(c)) — ainda assim, vale confirmar o seu caso com nossa equipe.",
                "Unauthorized employment generally bars adjustment of status in family-preference categories, but immediate relatives of a U.S. citizen are usually exempt from this specific bar (INA 245(c)) — it's still worth confirming your case with our team.",
                "El empleo no autorizado generalmente impide el ajuste de estatus en las categorías de preferencia familiar, pero los familiares inmediatos de un(a) ciudadano(a) estadounidense suelen estar exentos de esta barrera específica (INA 245(c)) — aun así, vale la pena confirmar su caso con nuestro equipo.",
            ))
        else:
            verdict = "needs_review"
            messages.append(_msg(
                "warning",
                "Trabalho não autorizado por mais de 180 dias geralmente impede o ajuste de status em categorias de preferência familiar (INA 245(c)) — esse é um ponto que precisa de atenção especial no seu caso.",
                "Unauthorized employment for more than 180 days generally bars adjustment of status in family-preference categories (INA 245(c)) — this needs special attention in your case.",
                "El empleo no autorizado por más de 180 días generalmente impide el ajuste de estatus en las categorías de preferencia familiar (INA 245(c)) — esto requiere atención especial en su caso.",
            ))

    if answers.get("beneficio_publico") == "sim":
        verdict = "needs_review" if verdict == "eligible" else verdict
        messages.append(_msg(
            "warning",
            "Uso de benefícios assistenciais pode ser considerado na avaliação de \"public charge\" (encargo público) — as regras sobre isso mudaram ao longo do tempo, então vale discutir o seu caso específico com nossa equipe.",
            "Use of means-tested public benefits can be considered in the \"public charge\" evaluation — the rules on this have changed over time, so it's worth discussing your specific case with our team.",
            "El uso de beneficios asistenciales puede considerarse en la evaluación de \"carga pública\" (public charge) — las reglas al respecto han cambiado con el tiempo, así que vale la pena discutir su caso específico con nuestro equipo.",
        ))

    if not messages:
        messages.append(_msg(
            "success",
            "Não identificamos nenhum ponto de atenção nas suas respostas.",
            "We didn't identify any red flags in your answers.",
            "No identificamos ningún punto de atención en sus respuestas.",
        ))

    return {"verdict": verdict, "filing_window": filing_window, "messages": messages}


# ── GC Consular Processing (I-130 + DS-260 + I-864) ──────────────────────────

def evaluate_gc_consular(answers: dict) -> dict:
    messages: list[dict] = []
    verdict = "eligible"

    vinculo = answers.get("vinculo")
    is_immediate_relative = vinculo in _IMMEDIATE_RELATIVE_VALUES

    if vinculo == "outro":
        filing_window = None
        messages.append(_msg(
            "info",
            "Esse vínculo tem regras próprias de elegibilidade e disponibilidade de visto — fale com nossa equipe para avaliar o seu caso especificamente.",
            "That relationship has its own eligibility and visa-availability rules — talk to our team to evaluate your specific case.",
            "Ese vínculo tiene sus propias reglas de elegibilidad y disponibilidad de visa — hable con nuestro equipo para evaluar su caso específico.",
        ))
    elif is_immediate_relative:
        filing_window = _msg(
            "success",
            "Como parente imediato de cidadão americano, um visto está SEMPRE disponível — assim que o I-130 for aprovado, o processo segue direto para o National Visa Center (NVC), sem espera de fila.",
            "As an immediate relative of a U.S. citizen, a visa is ALWAYS available — once the I-130 is approved, the process goes straight to the National Visa Center (NVC), with no wait in line.",
            "Como familiar inmediato de un(a) ciudadano(a) estadounidense, siempre hay una visa disponible — en cuanto se apruebe el I-130, el proceso pasa directamente al National Visa Center (NVC), sin espera en fila.",
        )
    else:
        filing_window = _msg(
            "info",
            "Sua categoria está sujeita à fila de vistos — acompanhe o Boletim de Vistos do Departamento de Estado para saber quando a Data de Prioridade ficará atual, antes que o NVC agende a entrevista.",
            "Your category is subject to the visa line — track the State Department's Visa Bulletin to know when the Priority Date becomes current, before the NVC schedules the interview.",
            "Su categoría está sujeta a la fila de visas — siga el Boletín de Visas del Departamento de Estado para saber cuándo su Fecha de Prioridad estará vigente, antes de que el NVC programe la entrevista.",
        )

    messages.append(_msg(
        "info",
        "Depois que o I-130 for aprovado e enviado ao National Visa Center (NVC), é preciso responder às solicitações de documentos dentro do prazo indicado (normalmente até 1 ano) para não arquivarem o caso por inatividade.",
        "After the I-130 is approved and sent to the National Visa Center (NVC), document requests must be answered within the indicated deadline (usually up to 1 year) to avoid the case being administratively closed for inactivity.",
        "Después de que el I-130 sea aprobado y enviado al National Visa Center (NVC), es necesario responder a las solicitudes de documentos dentro del plazo indicado (normalmente hasta 1 año) para evitar que el caso se cierre administrativamente por inactividad.",
    ))

    messages.append(_msg(
        "info",
        "O beneficiário também vai precisar de um exame médico — mas, diferente do ajuste de status, o processamento consular NÃO usa o Formulário I-693; o exame é feito por um médico credenciado (panel physician) indicado pelo consulado/embaixada responsável pelo caso, geralmente agendado depois que o NVC enviar as instruções para a entrevista. Não realizamos esse exame, mas fornecemos o máximo de informações sobre o processo — siga as instruções do NVC/consulado para agendar com o médico credenciado correto.",
        "The beneficiary will also need a medical exam — but unlike adjustment of status, consular processing does NOT use Form I-693; the exam is performed by a credentialed panel physician designated by the consulate/embassy handling the case, usually scheduled after the NVC sends interview instructions. We don't perform this exam ourselves, but we provide as much guidance about the process as possible — follow the NVC/consulate's instructions to schedule with the correct designated physician.",
        "El (la) beneficiario(a) también necesitará un examen médico — pero, a diferencia del ajuste de estatus, el trámite consular NO utiliza el Formulario I-693; el examen lo realiza un médico acreditado (panel physician) designado por el consulado/embajada a cargo del caso, generalmente programado después de que el NVC envíe las instrucciones de la entrevista. Nosotros no realizamos este examen, pero ofrecemos toda la orientación posible sobre el proceso — siga las instrucciones del NVC/consulado para programar la cita con el médico designado correcto.",
    ))

    if answers.get("morou_ilegal") in ("sim", "nao_sei"):
        verdict = "needs_review"
        messages.append(_msg(
            "danger",
            "Presença ilegal nos EUA por mais de 180 dias antes de sair do país pode ativar uma barra de reentrada de 3 ou 10 anos (INA 212(a)(9)(B)) no momento em que o beneficiário sair dos EUA ou comparecer à entrevista consular. Este é um ponto crítico — é essencial consultar um advogado de imigração antes de prosseguir, já que pode ser necessário um perdão (waiver, Formulário I-601) primeiro.",
            "Unlawful presence in the U.S. for more than 180 days before leaving the country can trigger a 3- or 10-year reentry bar (INA 212(a)(9)(B)) once the beneficiary leaves the U.S. or attends the consular interview. This is a critical issue — it's essential to consult an immigration attorney before proceeding, since a waiver (Form I-601) may be needed first.",
            "La presencia ilegal en los EE. UU. por más de 180 días antes de salir del país puede activar una barra de reingreso de 3 o 10 años (INA 212(a)(9)(B)) en el momento en que el (la) beneficiario(a) salga de los EE. UU. o asista a la entrevista consular. Este es un punto crítico — es fundamental consultar a un abogado de inmigración antes de continuar, ya que primero puede ser necesario un perdón (waiver, Formulario I-601).",
        ))

    if answers.get("condenacao") == "sim":
        verdict = "needs_review"
        messages.append(_msg(
            "warning",
            "Condenações criminais, deportações anteriores, ou histórico de fraude podem gerar questões sérias de inadmissibilidade na entrevista consular — consulte um advogado de imigração antes de prosseguir.",
            "Criminal convictions, prior deportations, or a history of fraud can raise serious inadmissibility issues at the consular interview — consult an immigration attorney before proceeding.",
            "Las condenas penales, deportaciones previas, o antecedentes de fraude pueden generar problemas serios de inadmisibilidad en la entrevista consular — consulte a un abogado de inmigración antes de continuar.",
        ))

    return {"verdict": verdict, "filing_window": filing_window, "messages": messages}


EVALUATORS = {
    "cidadania": evaluate_cidadania,
    "gc-roc": evaluate_gc_roc,
    "gc-aos": evaluate_gc_aos,
    "gc-consular": evaluate_gc_consular,
}
