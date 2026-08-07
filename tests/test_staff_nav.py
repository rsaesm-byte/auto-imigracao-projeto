"""Regressão do bug reportado 2026-08-07: "quando eu mudo a ordem ou crio
novos grupos... não está salvando" (Edit navigation, staff_base.html).

Reproduzido ao vivo no Chrome: o "Save for all collaborators"
(app/staff_nav.py::save_layout, scope="global") gravava certinho em
StaffNavGlobalLayout, mas quem salvou não via a mudança nenhuma --
porque `resolve_nav_layout` sempre prioriza a linha pessoal
(StaffNavLayout) sobre a global, e essa pessoa já tinha uma
personalização própria de um save "só pra mim" anterior. Corrigido
sincronizando a linha pessoal de quem salva "pra todos" também.

`resolve_nav_layout` chama `url_for()` internamente (monta a URL de cada
aba) -- por isso todo teste aqui roda dentro de `app.test_request_context()`,
não só com a sessão de banco isolada.
"""
from __future__ import annotations


def _simple_layout(*item_ids):
    return [{"kind": "item", "id": item_id} for item_id in item_ids]


def _first_two_ids(app, user_id):
    from app.staff_nav import resolve_nav_layout
    with app.test_request_context():
        slots = resolve_nav_layout(user_id, endpoint=None, blueprint=None)
    return [s["id"] for s in slots if s["kind"] == "item"][:2]


def test_save_personal_reflects_in_resolve(app, db, staff_user):
    from app.staff_nav import save_layout

    ok = save_layout(staff_user.id, _simple_layout("crm_dashboard", "pending"), scope="personal")
    assert ok
    db.commit()

    assert _first_two_ids(app, staff_user.id) == ["crm_dashboard", "pending"]


def test_save_global_reflects_for_user_without_personal_override(app, db, staff_user):
    from app.staff_nav import save_layout

    ok = save_layout(staff_user.id, _simple_layout("pending", "crm_dashboard"), scope="global")
    assert ok
    db.commit()

    assert _first_two_ids(app, staff_user.id) == ["pending", "crm_dashboard"]


def test_save_global_after_personal_override_still_reflects_for_the_saver(app, db, staff_user):
    """O bug em si: usuário salva "só pra mim" primeiro (cria a linha
    pessoal), depois edita de novo e salva "pra todos" -- o resultado
    tem que aparecer pra ELE MESMO, não só pros outros colaboradores."""
    from app.staff_nav import save_layout

    save_layout(staff_user.id, _simple_layout("crm_dashboard", "pending"), scope="personal")
    db.commit()

    save_layout(staff_user.id, _simple_layout("approved", "crm_dashboard"), scope="global")
    db.commit()

    assert _first_two_ids(app, staff_user.id) == ["approved", "crm_dashboard"], (
        "o novo layout global devia ter substituído a personalização antiga "
        "de quem acabou de salvar 'pra todos', não ficar escondido atrás dela")


def test_save_global_does_not_touch_other_users_personal_override(app, db, staff_user):
    """A sincronização do fix só deve tocar a linha pessoal de quem
    salvou -- outro colaborador com personalização própria continua
    vendo a dele, sem ser sobrescrito sem consentimento."""
    from app.models import User
    from app.staff_nav import save_layout

    other = User(email="outro-colaborador@example.com", password_hash="x", is_staff=True, email_verified=True)
    db.add(other)
    db.commit()

    save_layout(other.id, _simple_layout("crm_dashboard", "financial"), scope="personal")
    db.commit()

    save_layout(staff_user.id, _simple_layout("approved", "pending"), scope="global")
    db.commit()

    assert _first_two_ids(app, other.id) == ["crm_dashboard", "financial"]
