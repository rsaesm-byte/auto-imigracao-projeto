"""Envio de e-mails transacionais.

**Ainda não há provedor de e-mail configurado para redefinição de senha /
notificação de pagamento** (sem SMTP/SendGrid/SES etc.) -- essas duas
continuam só registrando no log do servidor, fora de escopo desta
mudança. `send_verification_code_email` abaixo é a exceção: envia de
verdade via Gmail SMTP (uma das contas Gmail que a empresa já usa, com uma
"Senha de app" do Google), porque o código de verificação de conta
(app/services/email_verification_service.py) só é útil se chegar na
caixa de entrada do cliente de fato -- sem provedor real, o gate de
verificação de e-mail trancaria toda conta nova. Configurado via
SMTP_EMAIL/SMTP_APP_PASSWORD (ver .env.example); se não configurado,
cai pro log (mesmo comportamento das outras duas), pra não quebrar em
ambiente de desenvolvimento sem essas variáveis.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

from app.models import Payment, User

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Endereços da equipe que devem ser notificados quando um cliente envia um
# comprovante de pagamento (ver app/payment_gate.py::checkout) -- fixos por
# enquanto (não há um cadastro de equipe além das contas de staff em
# app/models.py::User.is_staff). Quando houver um provedor de e-mail real,
# send_payment_notification_email() abaixo deve mandar pra esta lista.
STAFF_NOTIFICATION_EMAILS = (
    "saesprofessional.alessandra@gmail.com",
    "saesprofessional.barbara@gmail.com",
    "saes.professionalservices@gmail.com",
)


def send_password_reset_email(user: User, reset_url: str) -> None:
    """Envia (hoje: apenas loga) o link de redefinição de senha para
    `user`. Nunca levanta exceção -- uma falha de envio não deve quebrar
    o fluxo de "esqueci minha senha" para o usuário."""
    current_app.logger.warning(
        "AVISO: nenhum provedor de e-mail configurado ainda -- link de "
        "redefinição de senha para %s (válido por 1h): %s",
        user.email, reset_url,
    )


def send_payment_notification_email(payment: Payment, client_email: str,
                                     case_label: str, amount_display: str) -> None:
    """Notifica a equipe (STAFF_NOTIFICATION_EMAILS acima) que um cliente
    enviou um comprovante de pagamento -- hoje só loga (ver docstring do
    módulo: nenhum provedor de e-mail real configurado ainda). Quando
    houver um provedor, esta função deve enviar um e-mail de verdade pros 3
    endereços com o comprovante (payment.proof_path) anexado e um link
    para o painel /staff para confirmar o pagamento. `client_name`/
    `client_phone` vêm do formulário de checkout (app/payment_gate.py),
    não da conta logada -- é o telefone que app/staff.py::confirm_payment
    usa depois pra abrir o WhatsApp direto com o cliente. Nunca levanta
    exceção -- mesma garantia de send_password_reset_email() acima."""
    from flask import url_for
    staff_url = url_for("staff.dashboard", _external=True)
    current_app.logger.warning(
        "AVISO: nenhum provedor de e-mail configurado ainda -- notificação de "
        "pagamento pendente (destinatários: %s): cliente=%s (%s, tel. %s), caso=%s, "
        "valor=%s, forma=%s, comprovante=%s, confirmar em: %s",
        ", ".join(STAFF_NOTIFICATION_EMAILS), payment.client_name or client_email,
        payment.client_email or client_email, payment.client_phone, case_label,
        amount_display, payment.method, payment.proof_path, staff_url,
    )


def send_verification_code_email(user: User, code: str) -> None:
    """Envia o código de verificação de conta de 6 dígitos (ver
    app/services/email_verification_service.py) pro e-mail de `user`, via
    Gmail SMTP quando SMTP_EMAIL/SMTP_APP_PASSWORD estão configurados
    (ver .env.example) -- cai pro log, como as outras duas funções acima,
    se essas variáveis não estiverem definidas (ex.: ambiente de dev sem
    provedor configurado ainda). Nunca levanta exceção -- mesma garantia
    das outras funções deste módulo: uma falha de envio não deve derrubar
    o fluxo de cadastro."""
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_APP_PASSWORD")

    if not smtp_email or not smtp_password:
        current_app.logger.warning(
            "AVISO: SMTP_EMAIL/SMTP_APP_PASSWORD não configurados -- código de "
            "verificação para %s (válido por 15 min): %s",
            user.email, code,
        )
        return

    message = EmailMessage()
    message["Subject"] = f"Saes Professional Services -- código de verificação: {code}"
    message["From"] = smtp_email
    message["To"] = user.email
    message.set_content(
        "Seu código de verificação da Saes Professional Services é:\n\n"
        f"    {code}\n\n"
        "Este código expira em 15 minutos. Se você não pediu este código, "
        "pode ignorar este e-mail."
    )

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(message)
    except Exception:
        current_app.logger.exception(
            "Falha ao enviar e-mail de verificação para %s via Gmail SMTP", user.email)
