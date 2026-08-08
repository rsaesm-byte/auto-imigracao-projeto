"""Painel do CEO -- criar/bloquear contas de colaborador e conceder área
de acesso (Prompt Mestre 1, Seção 13, pedido do usuário 2026-08-08:
"perfis por área inteira, não ação por ação"). Só quem tem
`User.is_ceo=True` acessa este painel inteiro -- gerenciar OUTRAS contas
é mais sensível do que qualquer área de trabalho normal (ver
app/staff_permissions.py), então não usa `require_area()`, tem seu
próprio gate.
"""
from __future__ import annotations

import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from app.db import SessionLocal
from app.models import StaffAreaAccess, User
from app.staff_permissions import AREAS

crm_staff_admin_bp = Blueprint("crm_staff_admin", __name__, url_prefix="/staff/equipe")


@crm_staff_admin_bp.before_request
@login_required
def _require_ceo():
    if not current_user.is_staff or not current_user.is_ceo:
        abort(403)


@crm_staff_admin_bp.route("/")
def list_staff():
    staff = SessionLocal.query(User).filter_by(is_staff=True).order_by(User.email).all()
    areas_by_user = {
        user_id: {row.area for row in rows}
        for user_id, rows in _group_areas(staff).items()
    }
    return render_template("crm_staff_admin.html", staff=staff, areas=AREAS, areas_by_user=areas_by_user)


def _group_areas(staff: list[User]) -> dict[int, list[StaffAreaAccess]]:
    if not staff:
        return {}
    ids = [u.id for u in staff]
    rows = SessionLocal.query(StaffAreaAccess).filter(StaffAreaAccess.user_id.in_(ids)).all()
    grouped: dict[int, list[StaffAreaAccess]] = {u.id: [] for u in staff}
    for row in rows:
        grouped[row.user_id].append(row)
    return grouped


@crm_staff_admin_bp.route("/nova", methods=["POST"])
def new_staff():
    email = request.form.get("email", "").strip().lower()
    job_title = request.form.get("job_title", "").strip() or None
    selected_areas = set(request.form.getlist("areas")) & set(AREAS)
    make_ceo = request.form.get("is_ceo") == "on"

    if not email:
        flash("Informe um e-mail.", "error")
        return redirect(url_for("crm_staff_admin.list_staff"))
    if SessionLocal.query(User).filter_by(email=email).first() is not None:
        flash(f"Já existe uma conta com o e-mail {email}.", "error")
        return redirect(url_for("crm_staff_admin.list_staff"))

    temp_password = secrets.token_urlsafe(9)
    user = User(
        email=email, password_hash=generate_password_hash(temp_password), is_staff=True,
        email_verified=True, job_title=job_title, is_ceo=make_ceo, areas_provisioned=True,
    )
    SessionLocal.add(user)
    SessionLocal.flush()
    for area in selected_areas:
        SessionLocal.add(StaffAreaAccess(user_id=user.id, area=area))
    SessionLocal.commit()

    flash(
        f"Conta criada para {email}. Senha temporária (mostrada só agora, "
        f"anote e repasse com segurança): {temp_password}",
        "success",
    )
    return redirect(url_for("crm_staff_admin.list_staff"))


@crm_staff_admin_bp.route("/<int:user_id>/areas", methods=["POST"])
def update_areas(user_id: int):
    user = SessionLocal.get(User, user_id)
    if user is None or not user.is_staff:
        abort(404)

    selected_areas = set(request.form.getlist("areas")) & set(AREAS)
    existing = SessionLocal.query(StaffAreaAccess).filter_by(user_id=user.id).all()
    existing_areas = {row.area for row in existing}

    for row in existing:
        if row.area not in selected_areas:
            SessionLocal.delete(row)
    for area in selected_areas - existing_areas:
        SessionLocal.add(StaffAreaAccess(user_id=user.id, area=area))

    # Ninguém remove o próprio "is_ceo" por engano nesta mesma tela (evita
    # ficar sem nenhum CEO pra desfazer o erro) -- só outra conta CEO pode
    # tirar o status de alguém.
    if user.id != current_user.id:
        user.is_ceo = request.form.get("is_ceo") == "on"

    SessionLocal.commit()
    flash(f"Áreas de {user.email} atualizadas.", "success")
    return redirect(url_for("crm_staff_admin.list_staff"))


@crm_staff_admin_bp.route("/<int:user_id>/bloquear", methods=["POST"])
def block_staff(user_id: int):
    user = SessionLocal.get(User, user_id)
    if user is None or not user.is_staff:
        abort(404)
    if user.id == current_user.id:
        flash("Você não pode bloquear a própria conta.", "error")
        return redirect(url_for("crm_staff_admin.list_staff"))
    user.is_active_ = False
    SessionLocal.commit()
    flash(f"{user.email} bloqueado(a) -- não consegue mais fazer login (sessões já abertas continuam até sair).", "success")
    return redirect(url_for("crm_staff_admin.list_staff"))


@crm_staff_admin_bp.route("/<int:user_id>/desbloquear", methods=["POST"])
def unblock_staff(user_id: int):
    user = SessionLocal.get(User, user_id)
    if user is None or not user.is_staff:
        abort(404)
    user.is_active_ = True
    SessionLocal.commit()
    flash(f"{user.email} desbloqueado(a).", "success")
    return redirect(url_for("crm_staff_admin.list_staff"))


@crm_staff_admin_bp.route("/<int:user_id>/resetar-senha", methods=["POST"])
def reset_password(user_id: int):
    user = SessionLocal.get(User, user_id)
    if user is None or not user.is_staff:
        abort(404)
    temp_password = secrets.token_urlsafe(9)
    user.password_hash = generate_password_hash(temp_password)
    SessionLocal.commit()
    flash(
        f"Nova senha temporária de {user.email} (mostrada só agora): {temp_password}",
        "success",
    )
    return redirect(url_for("crm_staff_admin.list_staff"))
