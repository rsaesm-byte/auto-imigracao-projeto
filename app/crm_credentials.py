"""Tela staff dedicada às credenciais USCIS/Embaixada (criptografadas --
ver app/services/crypto.py e app/crm_models.py::ClientCredential).

Isolada de propósito num módulo/URL próprios (`/staff/crm/credenciais/...`),
separada do resto do CRM: nunca decripta automaticamente ao carregar a
página (só sob clique explícito em "Revelar", via POST, nunca GET), e todo
acesso decriptado fica registrado em `CredentialAccessLog` para auditoria.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import (Blueprint, abort, flash, make_response, redirect,
                    render_template, request, url_for)
from flask_login import current_user, login_required

from app.crm_models import (Client, ClientCredential, CredentialAccessLog,
                             CredentialService)
from app.db import SessionLocal
from app.models import User
from app.services.crypto import CredentialsKeyNotConfigured, decrypt, encrypt
from app.staff_permissions import require_area

crm_credentials_bp = Blueprint("crm_credentials", __name__, url_prefix="/staff/crm/credenciais")


@crm_credentials_bp.before_request
@login_required
def _require_staff():
    if not current_user.is_staff:
        abort(403)
    require_area("internal_management")


def _render_detail(client_id: int, *, revealed_credential_id: int | None = None,
                    revealed_values: dict | None = None):
    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)

    credentials = (
        SessionLocal.query(ClientCredential)
        .filter_by(client_id=client_id)
        .order_by(ClientCredential.service)
        .all()
    )

    access_log = []
    if credentials:
        credential_ids = [c.id for c in credentials]
        rows = (
            SessionLocal.query(CredentialAccessLog)
            .filter(CredentialAccessLog.credential_id.in_(credential_ids))
            .order_by(CredentialAccessLog.accessed_at.desc())
            .limit(50)
            .all()
        )
        for row in rows:
            accessor = SessionLocal.get(User, row.accessed_by_user_id)
            access_log.append({
                "accessed_at": row.accessed_at,
                "accessed_by_email": accessor.email if accessor is not None else "—",
            })

    # Cache-Control: no-store em toda a tela (não só na resposta do
    # "Revelar") -- defesa em profundidade contra um proxy/navegador
    # guardar em cache uma resposta que, num acesso, veio com a senha em
    # texto plano no corpo (a URL em si nunca leva o segredo, ver reveal()
    # abaixo, mas o corpo da resposta sim).
    response = make_response(render_template(
        "crm_credentials.html", client=client, credentials=credentials,
        access_log=access_log, revealed_credential_id=revealed_credential_id,
        revealed_values=revealed_values or {}, services=list(CredentialService)))
    response.headers["Cache-Control"] = "no-store"
    return response


@crm_credentials_bp.route("/<int:client_id>")
def detail(client_id: int):
    return _render_detail(client_id)


@crm_credentials_bp.route("/revelar/<int:credential_id>", methods=["POST"])
def reveal(credential_id: int):
    """POST de propósito (nunca GET): revelar uma credencial não deve
    poder acontecer por um link/prefetch de navegador, e não queremos o
    id da credencial vista numa URL que possa ficar em histórico/logs de
    acesso do servidor. O registro de auditoria de verdade é a linha
    gravada em CredentialAccessLog logo abaixo."""
    credential = SessionLocal.get(ClientCredential, credential_id)
    if credential is None:
        abort(404)

    revealed_values = {
        "email": decrypt(credential.email_encrypted),
        "password": decrypt(credential.password_encrypted),
        "backup_code": decrypt(credential.backup_code_encrypted),
        "five_letters": decrypt(credential.five_letters_encrypted),
        "key_word": decrypt(credential.key_word_encrypted),
    }

    SessionLocal.add(CredentialAccessLog(
        credential_id=credential.id, accessed_by_user_id=current_user.id,
        accessed_at=datetime.now(timezone.utc)))
    SessionLocal.commit()

    return _render_detail(
        credential.client_id, revealed_credential_id=credential.id,
        revealed_values=revealed_values)


@crm_credentials_bp.route("/<int:client_id>/salvar", methods=["POST"])
def save(client_id: int):
    client = SessionLocal.get(Client, client_id)
    if client is None:
        abort(404)

    try:
        service = CredentialService(request.form.get("service", ""))
    except ValueError:
        flash("Invalid service.", "error")
        return redirect(url_for("crm_credentials.detail", client_id=client_id))

    credential = (
        SessionLocal.query(ClientCredential)
        .filter_by(client_id=client_id, service=service)
        .first()
    )
    if credential is None:
        credential = ClientCredential(client_id=client_id, service=service)
        SessionLocal.add(credential)

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    backup_code = request.form.get("backup_code", "").strip()
    # Só existem pro serviço Embassy (verificação por telefone com a
    # Embaixada) -- o form só manda esses campos no card de Embassy, mas a
    # rota não precisa validar isso: salvar em branco pra USCIS é inofensivo
    # (fica None, igual não ter enviado).
    five_letters = request.form.get("five_letters", "").strip()
    key_word = request.form.get("key_word", "").strip()

    try:
        # Só sobrescreve um campo se o form mandou algo novo -- deixar o
        # campo em branco no formulário de edição significa "não mudar",
        # não "apagar" (senão editar só a senha apagaria o e-mail salvo).
        if email:
            credential.email_encrypted = encrypt(email)
        if password:
            credential.password_encrypted = encrypt(password)
        if backup_code:
            credential.backup_code_encrypted = encrypt(backup_code)
        if five_letters:
            credential.five_letters_encrypted = encrypt(five_letters)
        if key_word:
            credential.key_word_encrypted = encrypt(key_word)
    except CredentialsKeyNotConfigured:
        SessionLocal.rollback()
        flash("Encryption key not configured (CRM_CREDENTIALS_KEY) -- "
              "notify the administrator. No credential was saved.", "error")
        return redirect(url_for("crm_credentials.detail", client_id=client_id))

    credential.updated_by_user_id = current_user.id
    SessionLocal.commit()
    flash("Credential saved.", "success")
    return redirect(url_for("crm_credentials.detail", client_id=client_id))
