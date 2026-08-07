"""Verificação de conta por código de 6 dígitos enviado por e-mail --
exigida antes de contratar um pacote (gate global em
app/__init__.py::create_app()). Mesmo estilo de
app/services/password_reset_service.py, mas guarda o código no próprio
`User` (código curto digitado por um humano, não um token de URL de uso
único): expira sozinho, tem limite de tentativas erradas, e reenvio tem
rate limit em memória (mesmo padrão do módulo irmão).
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.models import User

CODE_MAX_AGE = timedelta(minutes=15)
MAX_ATTEMPTS = 5
RESEND_RATE_LIMIT_SECONDS = 60  # no máx. 1 reenvio por conta por minuto

_last_resend_at: dict[int, float] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_verification_code(user: User) -> str:
    """Gera um novo código de 6 dígitos, grava o hash + expiração no
    usuário, e zera o contador de tentativas erradas. Não comita -- quem
    chama é responsável por SessionLocal.commit() (mesmo padrão do resto
    do projeto)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    user.email_verification_code_hash = generate_password_hash(code)
    user.email_verification_expires_at = _utcnow() + CODE_MAX_AGE
    user.email_verification_attempts = 0
    return code


def verify_code(user: User, code: str) -> bool:
    """Confere `code` contra o hash guardado, com prazo de validade e
    limite de tentativas erradas. Incrementa o contador a cada tentativa
    (certa ou errada) -- só reenviar um código novo zera o contador de
    novo. Nunca levanta exceção."""
    if not user.email_verification_code_hash or not user.email_verification_expires_at:
        return False
    if user.email_verification_attempts >= MAX_ATTEMPTS:
        return False

    expires_at = user.email_verification_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if _utcnow() > expires_at:
        return False

    user.email_verification_attempts += 1
    if not check_password_hash(user.email_verification_code_hash, code):
        return False

    user.email_verified = True
    user.email_verification_code_hash = None
    user.email_verification_expires_at = None
    user.email_verification_attempts = 0
    return True


def is_resend_rate_limited(user_id: int) -> bool:
    """True se já houve um reenvio pra esta conta há menos de
    RESEND_RATE_LIMIT_SECONDS. Registra o pedido atual como efeito
    colateral quando devolve False (só chame quando for de fato reenviar)."""
    now = time.time()
    last = _last_resend_at.get(user_id, 0.0)
    if now - last < RESEND_RATE_LIMIT_SECONDS:
        return True
    _last_resend_at[user_id] = now
    return False
