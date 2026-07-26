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

from app.models import User


def send_password_reset_email(user: User, reset_url: str) -> None:
    """Envia (hoje: apenas loga) o link de redefinição de senha para
    `user`. Nunca levanta exceção -- uma falha de envio não deve quebrar
    o fluxo de "esqueci minha senha" para o usuário."""
    current_app.logger.info(
        "AVISO: nenhum provedor de e-mail configurado ainda -- link de "
        "redefinição de senha para %s (válido por 1h): %s",
        user.email, reset_url,
    )
