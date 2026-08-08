"""Signed, expirable URLs para anexos do Financial Planning (SAES_Financial
Planning_Master_Spec, Seção 14: "Signed temporary URLs" / "Attachment URLs
expire" -- item pendente até 2026-08-08). `app/services/storage/` já serve
os bytes por trás de auth de sessão (nunca um caminho de disco/URL pública
permanente) -- isto ACRESCENTA uma segunda camada: um token assinado
(`itsdangerous`, mesma SECRET_KEY já usada pra sessão) com validade curta,
verificado ANTES de checar a sessão/ownership de novo na rota. Link sem
token, com token errado, ou com token expirado -- todos caem em 404, nunca
em "faça login" (não vaza se o attachment existe pra quem não devia ver).
"""
from __future__ import annotations

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

ATTACHMENT_TOKEN_MAX_AGE_SECONDS = 3600  # 1 hora -- link expira mesmo se vazado
_SALT = "financial-attachment-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT)


def generate_attachment_token(attachment_id: int) -> str:
    return _serializer().dumps(attachment_id)


def verify_attachment_token(token: str, *, max_age: int = ATTACHMENT_TOKEN_MAX_AGE_SECONDS) -> int | None:
    """Devolve o attachment_id se o token for válido e ainda dentro da
    validade; None em qualquer outro caso (assinatura errada, token de
    outro attachment_id incompatível não existe -- o id É o payload,
    expirado, ou corrompido)."""
    try:
        return _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def attachment_url(endpoint: str, attachment_id: int, **kwargs) -> str:
    """Helper pra template: monta a URL de `endpoint` (que deve aceitar
    `attachment_id` e ler `token` da querystring) já com um token novo
    assinado. Gerado a cada render -- um link visto numa página antiga
    (aba deixada aberta) expira em 1h como qualquer outro, forçando um
    reload pra pegar um token novo."""
    token = generate_attachment_token(attachment_id)
    return url_for(endpoint, attachment_id=attachment_id, token=token, **kwargs)
