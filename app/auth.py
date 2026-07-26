"""Blueprint de autenticação: signup, login, logout, esqueci/redefinir senha."""
from __future__ import annotations

from flask import (Blueprint, current_app, flash, redirect, render_template,
                    request, url_for)
from flask_login import login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import SessionLocal
from app.models import User
from app.services.email_service import send_password_reset_email
from app.services.password_reset_service import (generate_reset_token,
                                                   is_rate_limited,
                                                   verify_reset_token)

auth_bp = Blueprint("auth", __name__)


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
        SessionLocal.commit()

        login_user(user)
        return redirect(next_url or url_for("wizard.dashboard"))

    return render_template("signup.html", email="", next_url=request.args.get("next") or "")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or request.args.get("next") or ""

        user = SessionLocal.query(User).filter_by(email=email).first()
        if user is None or not check_password_hash(user.password_hash, password):
            flash("E-mail ou senha incorretos.", "error")
            return render_template("login.html", email=email, next_url=next_url)
        if not user.is_active:
            flash("Esta conta está desativada.", "error")
            return render_template("login.html", email=email, next_url=next_url)

        login_user(user)
        return redirect(next_url or url_for("wizard.dashboard"))

    return render_template("login.html", email="", next_url=request.args.get("next") or "")


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
