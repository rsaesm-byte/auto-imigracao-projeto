"""Blueprint de autenticação: signup, login, logout, esqueci/redefinir senha."""
from __future__ import annotations

from flask import (Blueprint, current_app, flash, redirect, render_template,
                    request, session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import SessionLocal
from app.models import User
from app.services.email_service import (send_password_reset_email,
                                          send_verification_code_email)
from app.services.email_verification_service import (
    generate_verification_code, is_resend_rate_limited, verify_code)
from app.services.password_reset_service import (generate_reset_token,
                                                   is_rate_limited,
                                                   verify_reset_token)

auth_bp = Blueprint("auth", __name__)


def _post_login_redirect(next_url: str):
    """Destino padrão pós-login/verificação pro CLIENTE (nunca pra staff,
    ver login() abaixo) -- pedido do usuário 2026-08-06: quando a conta
    nasceu do formulário público de interesse inicial
    (app/lead_intake.py::start()), o próximo passo é o WhatsApp da Saes
    (nova aba), não direto "Meu Caso". `next_url` explícito (ex.: alguém
    tentando abrir uma página específica antes de logar) sempre ganha de
    qualquer um dos dois."""
    if next_url:
        return redirect(next_url)
    from app.lead_intake import pop_pending_lead_whatsapp_url
    whatsapp_url = pop_pending_lead_whatsapp_url()
    if whatsapp_url:
        session["lead_intake_whatsapp_url"] = whatsapp_url
        return redirect(url_for("lead_intake.whatsapp_handoff"))
    return redirect(url_for("crm_client.meu_caso"))


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or request.args.get("next") or ""

        if not email or "@" not in email:
            flash("Digite um e-mail válido.", "error")
            return render_template("signup.html", email=email, next_url=next_url)
        if len(password) < 8:
            flash("A senha precisa ter pelo menos 8 caracteres.", "error")
            return render_template("signup.html", email=email, next_url=next_url)

        existing = SessionLocal.query(User).filter_by(email=email).first()
        if existing:
            flash("Já existe uma conta com esse e-mail.", "error")
            return render_template("signup.html", email=email, next_url=next_url)

        user = User(email=email, password_hash=generate_password_hash(password))
        SessionLocal.add(user)
        SessionLocal.flush()  # precisa do user.id antes de gravar o código
        code = generate_verification_code(user)
        SessionLocal.commit()
        send_verification_code_email(user, code)

        login_user(user)
        return redirect(url_for("auth.verify_email", next=next_url) if next_url
                         else url_for("auth.verify_email"))

    return render_template("signup.html", email="", next_url=request.args.get("next") or "")


@auth_bp.route("/verificar-email", methods=["GET", "POST"])
@login_required
def verify_email():
    from app.i18n import t

    next_url = request.form.get("next") or request.args.get("next") or ""

    if current_user.email_verified:
        return _post_login_redirect(next_url)

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if verify_code(current_user, code):
            SessionLocal.commit()
            flash(t("email_verify_success"), "success")
            return _post_login_redirect(next_url)

        SessionLocal.commit()  # grava a tentativa incrementada mesmo em erro
        flash(t("email_verify_invalid_code"), "error")

    return render_template("verify_email.html", next_url=next_url)


@auth_bp.route("/verificar-email/reenviar", methods=["POST"])
@login_required
def resend_verification():
    from app.i18n import t

    next_url = request.form.get("next") or ""
    if not current_user.email_verified and not is_resend_rate_limited(current_user.id):
        code = generate_verification_code(current_user)
        SessionLocal.commit()
        send_verification_code_email(current_user, code)
        flash(t("email_verify_resent"), "success")
    else:
        flash(t("email_verify_resend_rate_limited"), "error")
    return redirect(url_for("auth.verify_email", next=next_url) if next_url
                     else url_for("auth.verify_email"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or request.args.get("next") or ""
        # "client" ou "staff" -- qual aba o usuário escolheu no toggle de
        # app/templates/login.html. Só muda o destino pós-login e, para
        # "staff", exige is_staff=True -- não é uma segunda credencial,
        # a equipe usa a mesma senha da conta, só entra por uma aba
        # separada que leva direto pro painel próprio (ver app/staff.py,
        # app/templates/staff_base.html).
        login_as = request.form.get("login_as", "client")

        # Aceita e-mail OU username (só a equipe tem username preenchido
        # hoje, ver app/models.py::User.username / app/staff.py::profile) --
        # tenta e-mail primeiro por ser o caso comum, cai pro username se
        # não achar.
        user = SessionLocal.query(User).filter_by(email=identifier).first()
        if user is None:
            user = SessionLocal.query(User).filter_by(username=identifier).first()
        email = identifier
        if user is None or not check_password_hash(user.password_hash, password):
            flash("E-mail/usuário ou senha incorretos.", "error")
            return render_template("login.html", email=email, next_url=next_url, login_as=login_as)
        if not user.is_active:
            flash("Esta conta está desativada.", "error")
            return render_template("login.html", email=email, next_url=next_url, login_as=login_as)
        if login_as == "staff" and not user.is_staff:
            flash("Esta conta não tem acesso à área da equipe Saes Professional.", "error")
            return render_template("login.html", email=email, next_url=next_url, login_as=login_as)

        login_user(user)
        if login_as == "staff":
            return redirect(url_for("staff.dashboard"))
        return _post_login_redirect(next_url)

    login_as = request.args.get("login_as", "client")
    return render_template("login.html", email="", next_url=request.args.get("next") or "", login_as=login_as)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    from app.i18n import t

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        dev_reset_url = None

        if email and not is_rate_limited(email):
            user = SessionLocal.query(User).filter_by(email=email).first()
            if user is not None:
                token = generate_reset_token(user)
                reset_url = url_for("auth.reset_password", token=token, _external=True)
                send_password_reset_email(user, reset_url)
                if current_app.debug:
                    dev_reset_url = reset_url

        # Mesma mensagem sempre, exista ou não a conta, esteja ou não sob
        # rate limit -- nunca deixamos alguém descobrir quais e-mails têm
        # cadastro (ou quando foi o último pedido) só testando este
        # formulário.
        flash(t("forgot_password_sent"), "success")
        if dev_reset_url:
            # Conveniência só em modo debug -- ainda não há provedor de
            # e-mail configurado (ver app/services/email_service.py), sem
            # isso não haveria como testar o fluxo de verdade agora.
            flash(f"[DEV] {dev_reset_url}", "success")
        return redirect(url_for("auth.forgot_password"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    from app.i18n import t

    user = verify_reset_token(token)
    if user is None:
        flash(t("reset_link_invalid"), "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if len(password) < 8:
            flash(t("password_too_short"), "error")
            return render_template("reset_password.html", token=token)
        if password != password_confirm:
            flash(t("passwords_dont_match"), "error")
            return render_template("reset_password.html", token=token)

        user.password_hash = generate_password_hash(password)
        SessionLocal.commit()

        flash(t("password_reset_success"), "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)
