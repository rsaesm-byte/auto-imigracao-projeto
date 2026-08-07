"""Formulário público de interesse inicial -- pedido do usuário
2026-08-06: "na página inicial mostre logo de cara uma apresentação em
que ele deverá definir o tipo de serviço que ele quer". Fluxo: visitante
marca o(s) serviço(s) de interesse -> preenche nome/e-mail/telefone/
melhor horário/como chegou até nós -> isso cria um Lead (mesmo padrão de
app/packages.py::_get_or_create_professional_lead) e avisa a equipe
(notify) -> visitante cai numa tela explicando que este contato fica
registrado (timeline completa até o fechamento do serviço) com um botão
"Criar conta" -> ao terminar o cadastro (app/auth.py), é redirecionado
pra uma nova aba do WhatsApp da Saes com uma mensagem pronta, pra falar
com um colaborador de verdade.

Blueprint público (sem @login_required em nenhuma rota) -- mesmo padrão
de app/packages.py para o público não-autenticado.
"""
from __future__ import annotations

from urllib.parse import quote

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.crm_models import Lead, LeadInterestedService, LeadSource, ServiceCatalog
from app.db import SessionLocal
from app.i18n import t_in
from app.services.service_interests import all_options, labels_for_keys, slugs_for_keys

lead_intake_bp = Blueprint("lead_intake", __name__, url_prefix="/interesse")


@lead_intake_bp.app_context_processor
def _inject_lead_intake_form_data():
    # app_context_processor (não route_context_processor) -- pedido do
    # usuário 2026-08-06: o formulário de interesse aparece "logo de
    # cara" em index.html (app/wizard.py::index()), uma rota de outro
    # blueprint que não sabe (nem precisa saber) desses dados -- mesmo
    # padrão já usado em app/crm_client.py::_inject_has_crm_case().
    return {
        # Lista completa (INCLUI cabeçalhos de grupo, is_group=True) --
        # o template decide como renderizar cada um; filtrar aqui já
        # descartava os cabeçalhos antes de chegarem lá, então eles
        # nunca apareciam (bug real, corrigido junto desta mudança).
        "lead_intake_options": all_options(),
        "lead_intake_sources": SessionLocal.query(LeadSource).order_by(LeadSource.name).all(),
    }

# Mesmo número do WhatsApp da Saes usado no resto do site (ver
# app/payment_gate.py::WHATSAPP_NUMBER) -- formato internacional sem
# símbolos, exigido pelo link wa.me.
WHATSAPP_NUMBER = "17815209935"


@lead_intake_bp.route("/", methods=["GET", "POST"])
def start():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        best_contact_time = request.form.get("best_contact_time", "").strip()
        lead_source_id_raw = request.form.get("lead_source_id", "")
        selected_keys = request.form.getlist("services")

        if not full_name or not email or not phone or not selected_keys:
            flash("Preencha nome, e-mail, telefone e selecione ao menos um serviço.", "error")
            return redirect(url_for("lead_intake.start"))

        try:
            lead_source_id = int(lead_source_id_raw)
        except (TypeError, ValueError):
            lead_source_id = None

        labels = labels_for_keys(selected_keys)
        lead = Lead(
            name=full_name,
            contact_email=email,
            contact_phone=phone,
            best_contact_time=best_contact_time or None,
            lead_source_id=lead_source_id,
            interest_notes="Interesse inicial (site): " + "; ".join(labels),
        )
        SessionLocal.add(lead)
        SessionLocal.flush()

        for slug in slugs_for_keys(selected_keys):
            service = SessionLocal.query(ServiceCatalog).filter_by(slug=slug).first()
            if service is not None:
                SessionLocal.add(LeadInterestedService(lead_id=lead.id, service_id=service.id))

        SessionLocal.commit()

        from app.services.notification_service import notify
        notify(
            "lead_new",
            title=f"New lead — {full_name}",
            body="Interested in: " + ", ".join(labels),
            url=url_for("crm_pipeline.lead_detail", lead_id=lead.id),
        )

        # Sessão (não querystring) -- mesmo padrão já usado em
        # app/payment_gate.py::submitted() -- só a próxima página lê isso,
        # uma vez, e o auth.py também consome pra saber que este signup
        # veio de um lead recém-criado (ver _redirect_after_login abaixo).
        # Guarda as CHAVES (não os rótulos em português já resolvidos) --
        # assim a tela seguinte e a mensagem de WhatsApp traduzem cada
        # serviço no idioma certo na hora de exibir, em vez de ficarem
        # presas ao português independente do idioma escolhido pelo
        # visitante (pedido do usuário 2026-08-06: traduzir este formulário).
        session["lead_intake"] = {
            "lead_id": lead.id, "full_name": full_name, "keys": selected_keys,
        }
        return redirect(url_for("lead_intake.next_step"))

    return render_template(
        "lead_intake_start.html", options=all_options(),
        lead_sources=SessionLocal.query(LeadSource).order_by(LeadSource.name).all())


@lead_intake_bp.route("/proximo-passo")
def next_step():
    data = session.get("lead_intake")
    if data is None:
        return redirect(url_for("lead_intake.start"))
    return render_template(
        "lead_intake_next_step.html", full_name=data.get("full_name"), keys=data.get("keys") or [])


def pop_pending_lead_whatsapp_url() -> str | None:
    """Chamado por app/auth.py nos 3 pontos de redirect pós-login/signup --
    monta o link do WhatsApp (mensagem citando o serviço de interesse) se
    (e só se) este login veio do fluxo de interesse inicial acima (mesma
    chave de sessão gravada em start(), lida aqui uma única vez). `.pop`
    -- aviso de uso único, mesmo padrão do resto do projeto (ver
    app/payment_gate.py::submitted())."""
    data = session.pop("lead_intake", None)
    if data is None:
        return None
    full_name = data.get("full_name") or "there"
    keys = data.get("keys") or []
    # Sempre em inglês, independente do idioma que o visitante usou no
    # site -- mesma regra de app/payment_gate.py::_whatsapp_url ("pedido
    # explícito do usuário"): é uma mensagem pro TIME ler, não pro cliente.
    labels_en = [t_in("en", "service_interest_" + k) for k in keys]
    interest = ", ".join(labels_en) if labels_en else "your immigration case"
    message = (
        f"Hello, this is {full_name}. I just created an account and I'm interested in: "
        f"{interest}. Could you help me get started?"
    )
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}"


@lead_intake_bp.route("/whatsapp")
def whatsapp_handoff():
    """Página de destino logo após o cliente terminar de criar a conta,
    quando ele veio do formulário de interesse inicial (ver
    app/auth.py::login()/verify_email()) -- mesmo padrão de "fica na
    interface do site + WhatsApp abre sozinho numa nova aba" já usado em
    app/payment_gate.py::submitted() (pedido do usuário 2026-08-06)."""
    whatsapp_url = session.pop("lead_intake_whatsapp_url", None)
    if whatsapp_url is None:
        return redirect(url_for("crm_client.meu_caso"))
    return render_template("lead_intake_whatsapp_handoff.html", whatsapp_url=whatsapp_url)
