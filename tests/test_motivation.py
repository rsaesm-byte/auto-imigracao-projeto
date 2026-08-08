"""Fase 10 (Motivation Board) do SAES_Financial_Planning_Master_Spec,
2026-08-07 -- galeria de itens inspiracionais, upload de imagem,
favoritos, fixar no topo.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def workspace(db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc

    fc = FinancialClient(full_name="Cliente Motivation Teste")
    db.add(fc)
    db.commit()
    return fp_svc.enable_access(fc, actor=staff_user)


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------

def test_create_item_requires_title(db, workspace):
    from app.services import motivation_service

    with pytest.raises(motivation_service.MotivationValidationError):
        motivation_service.create_item(workspace, actor=None, title="")


def test_create_item(db, workspace):
    from app.financial_planning_models import MotivationItemType
    from app.services import motivation_service

    item = motivation_service.create_item(
        workspace, actor=None, title="Debt-free by 2028", item_type=MotivationItemType.affirmation,
        categories="debt, motivation", source_url="https://example.com", location="Maui, HI")
    assert item.title == "Debt-free by 2028"
    assert item.item_type == MotivationItemType.affirmation
    assert item.location == "Maui, HI"
    assert item.favorite is False
    assert item.pinned is False


def test_list_items_pinned_first(db, workspace):
    from app.services import motivation_service

    a = motivation_service.create_item(workspace, actor=None, title="A")
    b = motivation_service.create_item(workspace, actor=None, title="B")
    motivation_service.toggle_pinned(b)

    items = motivation_service.list_items(workspace)
    assert items[0].title == "B"
    assert items[1].title == "A"


def test_list_items_defaults_to_creation_order(db, workspace):
    """Novos itens entram no fim (sort_order crescente), não em ordem
    arbitrária -- confirma o `_next_sort_order` antes de testar
    reordenação manual em cima disso."""
    from app.services import motivation_service

    motivation_service.create_item(workspace, actor=None, title="First")
    motivation_service.create_item(workspace, actor=None, title="Second")
    motivation_service.create_item(workspace, actor=None, title="Third")

    items = motivation_service.list_items(workspace)
    assert [i.title for i in items] == ["First", "Second", "Third"]


def test_update_item_requires_title(db, workspace):
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    with pytest.raises(motivation_service.MotivationValidationError):
        motivation_service.update_item(item, title="")


def test_update_item_changes_fields(db, workspace):
    from app.financial_planning_models import MotivationItemType
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    motivation_service.update_item(
        item, title="A renamed", item_type=MotivationItemType.quote,
        categories="new", source_url="https://new.example.com", location="Rio de Janeiro")
    assert item.title == "A renamed"
    assert item.item_type == MotivationItemType.quote
    assert item.categories == "new"
    assert item.source_url == "https://new.example.com"
    assert item.location == "Rio de Janeiro"


def test_reorder_items_sets_sort_order_by_submitted_position(db, workspace):
    from app.services import motivation_service

    a = motivation_service.create_item(workspace, actor=None, title="A")
    b = motivation_service.create_item(workspace, actor=None, title="B")
    c = motivation_service.create_item(workspace, actor=None, title="C")

    motivation_service.reorder_items(workspace, [c.id, a.id, b.id])

    items = motivation_service.list_items(workspace)
    assert [i.title for i in items] == ["C", "A", "B"]


def test_reorder_items_ignores_ids_from_another_workspace(db, workspace, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.services import financial_planning_service as fp_svc
    from app.services import motivation_service

    other_fc = FinancialClient(full_name="Outro Cliente Motivation Reorder")
    db.add(other_fc)
    db.commit()
    other_ws = fp_svc.enable_access(other_fc, actor=staff_user)
    foreign_item = motivation_service.create_item(other_ws, actor=None, title="Not mine")

    a = motivation_service.create_item(workspace, actor=None, title="A")
    b = motivation_service.create_item(workspace, actor=None, title="B")
    # Tenta colar o item de outro workspace no meio -- deve ser ignorado.
    motivation_service.reorder_items(workspace, [b.id, foreign_item.id, a.id])

    assert [i.title for i in motivation_service.list_items(workspace)] == ["B", "A"]
    assert foreign_item.financial_workspace_id == other_ws.id  # intocado


def test_list_items_favorites_only(db, workspace):
    from app.services import motivation_service

    a = motivation_service.create_item(workspace, actor=None, title="A")
    motivation_service.create_item(workspace, actor=None, title="B")
    motivation_service.toggle_favorite(a)

    favorites = motivation_service.list_items(workspace, favorites_only=True)
    assert [i.title for i in favorites] == ["A"]


def test_toggle_favorite_and_pinned_flip(db, workspace):
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    motivation_service.toggle_favorite(item)
    assert item.favorite is True
    motivation_service.toggle_favorite(item)
    assert item.favorite is False

    motivation_service.toggle_pinned(item)
    assert item.pinned is True
    motivation_service.toggle_pinned(item)
    assert item.pinned is False


def test_delete_item_removes_row(db, workspace):
    from app.financial_planning_models import MotivationItem
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    item_id = item.id
    motivation_service.delete_item(item)
    assert db.get(MotivationItem, item_id) is None


# --------------------------------------------------------------------------
# Image upload
# --------------------------------------------------------------------------

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415478da6360000002000155035c4d000000004945"
    "4e44ae426082")


def test_set_image_rejects_bad_extension(db, workspace):
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    with pytest.raises(motivation_service.MotivationValidationError):
        motivation_service.set_image(item, actor=None, filename="virus.exe", mime_type="image/png", content=b"x")


def test_set_image_rejects_mime_mismatch(db, workspace):
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    with pytest.raises(motivation_service.MotivationValidationError):
        motivation_service.set_image(
            item, actor=None, filename="photo.png", mime_type="application/octet-stream", content=_TINY_PNG)


def test_set_image_rejects_oversize(db, workspace, monkeypatch):
    from app.services import motivation_service

    monkeypatch.setattr(motivation_service, "MAX_MOTIVATION_IMAGE_BYTES", 10)
    item = motivation_service.create_item(workspace, actor=None, title="A")
    with pytest.raises(motivation_service.MotivationValidationError):
        motivation_service.set_image(item, actor=None, filename="photo.png", mime_type="image/png", content=_TINY_PNG)


def test_set_image_stores_attachment_and_links_it(db, workspace):
    from app.financial_planning_models import FinancialAttachment
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    attachment = motivation_service.set_image(
        item, actor=None, filename="photo.png", mime_type="image/png", content=_TINY_PNG)

    assert item.image_attachment_id == attachment.id
    assert attachment.record_type == "MotivationItem"
    assert attachment.record_id == item.id
    assert attachment.financial_workspace_id == workspace.id
    assert db.get(FinancialAttachment, attachment.id) is not None


def test_set_image_twice_soft_deletes_old_attachment(db, workspace):
    from app.financial_planning_models import FinancialAttachment
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    first = motivation_service.set_image(item, actor=None, filename="a.png", mime_type="image/png", content=_TINY_PNG)
    first_id = first.id
    second = motivation_service.set_image(item, actor=None, filename="b.png", mime_type="image/png", content=_TINY_PNG)

    assert item.image_attachment_id == second.id
    old = db.get(FinancialAttachment, first_id)
    assert old.deleted_at is not None  # nunca apaga o arquivo/registro, só marca


def test_delete_item_soft_deletes_its_attachment(db, workspace):
    from app.financial_planning_models import FinancialAttachment
    from app.services import motivation_service

    item = motivation_service.create_item(workspace, actor=None, title="A")
    attachment = motivation_service.set_image(item, actor=None, filename="a.png", mime_type="image/png", content=_TINY_PNG)
    attachment_id = attachment.id
    motivation_service.delete_item(item)

    assert db.get(FinancialAttachment, attachment_id).deleted_at is not None


# --------------------------------------------------------------------------
# Integração: rota real, cliente logado
# --------------------------------------------------------------------------

@pytest.fixture()
def financial_client_login(client, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc

    user = User(email="motivationclient@example.com", password_hash="x", is_staff=False, email_verified=True)
    db.add(user)
    db.commit()
    fc = FinancialClient(full_name="Cliente Motivation HTTP", user_id=user.id)
    db.add(fc)
    db.commit()
    fp_svc.enable_access(fc, actor=staff_user)

    user_id = user.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return client


def test_motivation_page_renders(financial_client_login):
    resp = financial_client_login.get("/meu-plano-financeiro/workspace/inspiracao")
    assert resp.status_code == 200
    assert b"Motivation Board" in resp.data


def test_add_item_via_route(financial_client_login, db):
    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/inspiracao/novo",
        data={"title": "Keep going"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Keep going" in resp.data


def test_favorite_and_delete_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import MotivationItem
    from app.services import motivation_service

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Motivation HTTP").first()
    item = motivation_service.create_item(fc.workspace, actor=None, title="Temp item")
    item_id = item.id

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/inspiracao/{item_id}/favorito", follow_redirects=True)
    assert resp.status_code == 200
    assert db.get(MotivationItem, item_id).favorite is True

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/inspiracao/{item_id}/excluir", follow_redirects=True)
    assert resp.status_code == 200
    assert db.get(MotivationItem, item_id) is None


def test_edit_item_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.financial_planning_models import MotivationItem
    from app.services import motivation_service

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Motivation HTTP").first()
    item = motivation_service.create_item(fc.workspace, actor=None, title="Original title")
    item_id = item.id

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/inspiracao/{item_id}/editar",
        data={"title": "Edited title", "location": "Lisbon"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Edited title" in resp.data

    refreshed = db.get(MotivationItem, item_id)
    assert refreshed.title == "Edited title"
    assert refreshed.location == "Lisbon"


def test_reorder_items_via_route(financial_client_login, db):
    from app.crm_financial_models import FinancialClient
    from app.services import motivation_service

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Motivation HTTP").first()
    a = motivation_service.create_item(fc.workspace, actor=None, title="First")
    b = motivation_service.create_item(fc.workspace, actor=None, title="Second")
    a_id, b_id = a.id, b.id

    resp = financial_client_login.post(
        "/meu-plano-financeiro/workspace/inspiracao/reordenar",
        data={"item_id": [str(b_id), str(a_id)]}, follow_redirects=True)
    assert resp.status_code == 200

    fc = db.query(FinancialClient).filter_by(full_name="Cliente Motivation HTTP").first()
    items = motivation_service.list_items(fc.workspace)
    assert [i.title for i in items if i.id in (a_id, b_id)] == ["Second", "First"]


def test_motivation_item_from_another_workspace_is_404(financial_client_login, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc
    from app.services import motivation_service

    staff_user = db.query(User).filter_by(email="staff@example.com").first()
    other_fc = FinancialClient(full_name="Outro Cliente Motivation")
    db.add(other_fc)
    db.commit()
    other_ws = fp_svc.enable_access(other_fc, actor=staff_user)
    other_item = motivation_service.create_item(other_ws, actor=None, title="Not yours")

    resp = financial_client_login.post(
        f"/meu-plano-financeiro/workspace/inspiracao/{other_item.id}/favorito")
    assert resp.status_code == 404


def test_motivation_image_from_another_workspace_is_404(financial_client_login, db, staff_user):
    from app.crm_financial_models import FinancialClient
    from app.models import User
    from app.services import financial_planning_service as fp_svc
    from app.services import motivation_service

    staff_user = db.query(User).filter_by(email="staff@example.com").first()
    other_fc = FinancialClient(full_name="Outro Cliente Motivation 2")
    db.add(other_fc)
    db.commit()
    other_ws = fp_svc.enable_access(other_fc, actor=staff_user)
    other_item = motivation_service.create_item(other_ws, actor=None, title="Not yours either")
    other_attachment = motivation_service.set_image(
        other_item, actor=None, filename="a.png", mime_type="image/png", content=_TINY_PNG)

    resp = financial_client_login.get(
        f"/meu-plano-financeiro/workspace/inspiracao/imagem/{other_attachment.id}")
    assert resp.status_code == 404
