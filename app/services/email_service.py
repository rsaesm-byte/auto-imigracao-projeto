"""Envio de e-mails transacionais -- hoje só o de redefinição de senha.

**Ainda não há provedor de e-mail configurado** (sem SMTP/SendGrid/SES
etc.). Por isso `send_password_reset_email` só registra o link no log do
servidor por enquanto -- não envia e-mail de verdade. Isso deixa o fluxo de
redefinição de senha inteiro funcionando (token seguro, expiração, uso
único) e pronto para testar, com o envio de fato isolado nesta única
função: quando houver um provedor, troque só o corpo desta função por uma
chamada real (smtplib, Flask-Mail, API do SendGrid, etc.) -- nenhum outro
código precisa mudar.
"""
from __future__ import annotations

from flask import current_app

from app.models import Payment, User

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
    current_app.logger.info(
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
    current_app.logger.info(
        "AVISO: nenhum provedor de e-mail configurado ainda -- notificação de "
        "pagamento pendente (destinatários: %s): cliente=%s (%s, tel. %s), caso=%s, "
        "valor=%s, forma=%s, comprovante=%s, confirmar em: %s",
        ", ".join(STAFF_NOTIFICATION_EMAILS), payment.client_name or client_email,
        payment.client_email or client_email, payment.client_phone, case_label,
        amount_display, payment.method, payment.proof_path, staff_url,
    )
