"""Blueprint da vitrine de pacotes (data/packages.json): como o negócio
realmente vende os serviços -- agrupando o formulário principal com os
formulários administrativos que quase sempre o acompanham (G-1145 de
notificação, G-1450/G-1650 de pagamento) e, no caso do I-539, com o
I-539A repetível por dependente.

"Iniciar pacote" reaproveita 100% do motor de formulário único já
existente (FormSubmission por form_slug) -- só cria uma submissão nova
para cada formulário "core" do pacote de uma vez, marcada com
package_slug para o dashboard conseguir agrupar visualmente. Nenhuma UI
de wizard nova foi necessária para isso."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.db import SessionLocal
from app.models import FormSubmission

packages_bp = Blueprint("packages", __name__, url_prefix="/pacotes")

ROOT = Path(__file__).resolve().parent.parent


def _load_packages() -> list[dict]:
    path = ROOT / "data" / "packages.json"
    return json.loads(path.read_text(encoding="utf-8"))["packages"]


def _find_package(slug: str) -> dict | None:
    return next((p for p in _load_packages() if p["slug"] == slug), None)


def _pick(pkg: dict, key: str, lang: str):
    if lang == "en":
        alt = pkg.get(f"{key}_en")
        if alt:
            return alt
    return pkg.get(key)


@packages_bp.route("/")
def index():
    from app.i18n import get_lang
    from app.wizard import _form_display_name
    lang = get_lang()
    packages = []
    for pkg in _load_packages():
        form_items = [i for i in pkg["items"] if i["type"] == "form"]
        packages.append({
            "slug": pkg["slug"],
            "name": _pick(pkg, "name", lang),
            "description": _pick(pkg, "description", lang),
            "form_names": [_form_display_name(i["slug"]) for i in form_items],
        })
    return render_template("packages_index.html", packages=packages)


@packages_bp.route("/<slug>")
def detail(slug: str):
    pkg = _find_package(slug)
    if pkg is None:
        abort(404)
    from app.i18n import get_lang, t
    from app.wizard import _form_display_name
    lang = get_lang()

    items = []
    for item in pkg["items"]:
        if item["type"] == "form":
            items.append({
                "type": "form", "slug": item["slug"],
                "name": _form_display_name(item["slug"]),
                "optional": item.get("optional", False),
                "note": item.get("note_pt"),
            })
        elif item["type"] == "payment_choice":
            items.append({
                "type": "payment_choice",
                "options": [{"slug": s, "name": _form_display_name(s)} for s in item["options"]],
                "note": item.get("note_pt"),
            })
        elif item["type"] == "repeatable":
            items.append({
                "type": "repeatable", "slug": item["slug"],
                "label": _pick(item, "label", lang),
            })
        elif item["type"] == "external":
            items.append({
                "type": "external", "name": item["name"],
                "note": item.get("note_pt"),
            })

    return render_template(
        "packages_detail.html",
        slug=slug,
        name=_pick(pkg, "name", lang),
        description=_pick(pkg, "description", lang),
        items=items,
        eligibility_quiz=pkg.get("eligibility_quiz"),
    )


@packages_bp.route("/<slug>/iniciar", methods=["POST"])
@login_required
def start_package(slug: str):
    pkg = _find_package(slug)
    if pkg is None:
        abort(404)

    core_form_slugs = [i["slug"] for i in pkg["items"] if i["type"] == "form" and not i.get("optional")]

    created = 0
    for form_slug in core_form_slugs:
        existing = (
            SessionLocal.query(FormSubmission)
            .filter_by(user_id=current_user.id, form_slug=form_slug, status="in_progress")
            .first()
        )
        if existing:
            continue
        submission = FormSubmission(user_id=current_user.id, form_slug=form_slug, package_slug=slug)
        submission.set_answers({})
        SessionLocal.add(submission)
        created += 1

    SessionLocal.commit()

    from app.i18n import t
    if created:
        flash(t("pkg_started_flash"), "success")
    else:
        flash(t("pkg_already_started_flash"), "success")
    return redirect(url_for("wizard.dashboard"))
