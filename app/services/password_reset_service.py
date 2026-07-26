"""Tokens seguros de redefinição de senha, sem precisar de tabela nova no
banco: usa `itsdangerous` (já é dependência do próprio Flask) para assinar
um payload com prazo de validade, usando SECRET_KEY do app.

Propriedades de segurança:
- **Expira sozinho**: `verify_reset_token` rejeita qualquer token mais
  velho que RESET_TOKEN_MAX_AGE_SECONDS, mesmo com assinatura válida.
- **Vira inválido depois de usado**: o payload assinado inclui uma
  impressão digital do `password_hash` atual do usuário (não a senha em
  si). Assim que a senha muda, todo token emitido antes -- inclusive o que
  acabou de ser usado -- deixa de bater com o hash novo e é rejeitado.
  Isso dá "uso único" de graça, sem precisar guardar/marcar tokens usados
  em banco.
- **Sem enumeração de e-mail**: a função de request (em app/auth.py) deve
  sempre mostrar a mesma mensagem genérica ao usuário, exista ou não uma
  conta com aquele e-mail -- só o comportamento aqui dentro (gerar token e
  chamar o envio) difere.
- **Rate limit básico por e-mail**: `is_rate_limited` guarda em memória
  (nível de módulo, mesmo padrão do cache de app/services/news_service.py)
  o horário do último pedido por e-mail, para não deixar disparar pedidos
  repetidos em sequência.
"""
from __future__ import annotations

import hashlib
import time

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.db import SessionLocal
from app.models import User

RESET_TOKEN_SALT = "password-reset-v1"
RESET_TOKEN_MAX_AGE_SECONDS = 60 * 60  # 1 hora
RESET_RATE_LIMIT_SECONDS = 60  # no máx. 1 pedido por e-mail por minuto

_last_request_at: dict[str, float] = {}


def _hash_fingerprint(password_hash: str) -> str:
    """Impressão digital curta do password_hash atual -- não é o hash em
    si (não precisa ser reversível, só precisa mudar quando a senha muda)."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_reset_token(user: User) -> str:
    payload = {"uid": user.id, "fp": _hash_fingerprint(user.password_hash)}
    return _serializer().dumps(payload, salt=RESET_TOKEN_SALT)


def verify_reset_token(token: str) -> User | None:
    """Decodifica e valida `token` de ponta a ponta -- assinatura, prazo, e
    que a senha do usuário não mudou desde que o token foi emitido (o que
    o torna de uso único: assim que a senha muda, o fingerprint embutido
    deixa de bater). Devolve o User se tudo bater, ou None -- nunca
    levanta exceção -- para qualquer token inválido, expirado, de usuário
    inexistente, ou já "gasto" por uma redefinição anterior."""
    try:
        payload = _serializer().loads(token, salt=RESET_TOKEN_SALT,
                                       max_age=RESET_TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None

    user = SessionLocal.get(User, payload.get("uid"))
    if user is None:
        return None
    if payload.get("fp") != _hash_fingerprint(user.password_hash):
        return None
    return user


def is_rate_limited(email: str) -> bool:
    """True se já houve um pedido de reset para este e-mail há menos de
    RESET_RATE_LIMIT_SECONDS. Registra o pedido atual como efeito colateral
    quando devolve False (ou seja, chame só quando for de fato processar
    o pedido)."""
    now = time.time()
    last = _last_request_at.get(email, 0.0)
    if now - last < RESET_RATE_LIMIT_SECONDS:
        return True
    _last_request_at[email] = now
    return False
