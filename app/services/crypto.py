"""Criptografia simétrica para dados sensíveis em repouso -- hoje só as
credenciais USCIS/Embaixada (app/crm_models.py::ClientCredential). O Notion
original guardava essas credenciais em texto puro (o próprio documento
mapeado sinaliza isso com ⚠️); aqui elas nunca tocam o banco sem passar por
`encrypt()` antes.

Chave lida de `CRM_CREDENTIALS_KEY` (.env, nunca commitada -- ver
.env.example) -- **falha alto e claro** se a chave não estiver configurada
em vez de, por exemplo, cair para um valor padrão ou gravar em texto puro
"só dessa vez". Uma credencial gravada sem chave configurada é exatamente o
tipo de dívida de segurança que este módulo existe para eliminar.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class CredentialsKeyNotConfigured(RuntimeError):
    """CRM_CREDENTIALS_KEY não está definida no ambiente."""


def _fernet() -> Fernet:
    key = os.environ.get("CRM_CREDENTIALS_KEY")
    if not key:
        raise CredentialsKeyNotConfigured(
            "CRM_CREDENTIALS_KEY não configurada -- gere uma com "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` e coloque no .env. "
            "Credencial nenhuma pode ser gravada sem isso.")
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt(plaintext: str | None) -> str | None:
    """None permanece None (campo de credencial não preenchido) -- nunca
    criptografa string vazia como se fosse um valor real."""
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str | None) -> str | None:
    """Devolve None tanto para `ciphertext` vazio quanto para um valor
    corrompido/de chave errada (`InvalidToken`) -- a tela que exibe a
    credencial decriptada trata None como "indisponível", nunca deve
    quebrar a página inteira por causa de uma credencial ilegível."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None
