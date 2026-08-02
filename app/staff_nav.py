"""Canonical registry of the /staff top-nav tabs + per-collaborator layout
customization (order + groups) -- user request 2026-08-02: an "Edit
navigation" mode where a collaborator drags tabs to reorder them (any
direction -- the bar wraps, so moving a tab's position changes which row
it ends up on too) and drops one tab onto another to bundle both into a
named dropdown group.

`NAV_ITEMS` is the single source of truth for every tab that used to be
hardcoded directly in staff_base.html's <nav> block -- adding a future
staff page means adding one entry here, not hand-editing nav markup in
three places. `DEFAULT_LAYOUT` (one slot per item, in this exact order, no
groups) is the innermost fallback.

Resolution order, per collaborator (see resolve_nav_layout()), user
request 2026-08-02 ("Save for all collaborators" vs. "Save just for me"):
1. That user's own `StaffNavLayout` row, if they've ever saved "just for
   me".
2. Else the org-wide `StaffNavGlobalLayout` singleton, if ANY collaborator
   has ever saved "for all collaborators".
3. Else `DEFAULT_LAYOUT` (hardcoded, from NAV_ITEMS order above).
None of these three layers is ever a stored duplicate of another --
absence at one layer always means "fall through to the next."
"""
from __future__ import annotations

import json

from flask import url_for

from app.db import SessionLocal
from app.models import StaffNavGlobalLayout, StaffNavLayout

GLOBAL_LAYOUT_ID = 1  # StaffNavGlobalLayout is a singleton -- always this id.

# Order here IS the default nav order. `match` lists every endpoint that
# should highlight this tab as active; `match_blueprint` is used instead
# for tabs that own many endpoints across a whole blueprint (CRM Financial,
# Case Tracking) -- same two conventions staff_base.html's old hardcoded
# nav already used per-link.
_NAV_ITEMS_LIST = [
    {"id": "pending", "label": "Pending Approvals", "endpoint": "staff.pending",
     "match": ["staff.pending"]},
    {"id": "approved", "label": "Approved", "endpoint": "staff.approved",
     "match": ["staff.approved"]},
    {"id": "finalized", "label": "Finalized", "endpoint": "staff.finalized",
     "match": ["staff.finalized"]},
    {"id": "review", "label": "Request Review", "endpoint": "staff.review_queue",
     "match": ["staff.review_queue"]},
    {"id": "prices", "label": "Prices", "endpoint": "staff.prices",
     "match": ["staff.prices"]},
    {"id": "documents", "label": "Documents", "endpoint": "staff.documents_list",
     "match": ["staff.documents_list"], "badge": "pending_documents_count"},
    {"id": "crm_cases", "label": "CRM: Cases", "endpoint": "crm_pipeline.cases_kanban",
     "match": ["crm_pipeline.cases_kanban"]},
    {"id": "crm_tracking", "label": "Case Tracking", "endpoint": "crm_tracking.dashboard",
     "match_blueprint": "crm_tracking"},
    {"id": "crm_leads", "label": "Leads", "endpoint": "crm_pipeline.leads_kanban",
     "match": ["crm_pipeline.leads_kanban", "crm_pipeline.lead_new", "crm_pipeline.lead_convert"]},
    {"id": "crm_clients", "label": "Clients", "endpoint": "crm_pipeline.clients_list",
     "match": ["crm_pipeline.clients_list", "crm_pipeline.client_new", "crm_pipeline.client_detail"]},
    {"id": "crm_payments", "label": "Payments (CRM)", "endpoint": "crm_ops.payments",
     "match": ["crm_ops.payments", "crm_ops.payment_new"]},
    {"id": "crm_comms", "label": "Communications", "endpoint": "crm_ops.communications",
     "match": ["crm_ops.communications", "crm_ops.communications_follow_ups", "crm_ops.communication_new"]},
    {"id": "crm_tasks", "label": "Tasks", "endpoint": "crm_ops.tasks",
     "match": ["crm_ops.tasks", "crm_ops.task_new"]},
    {"id": "crm_translations", "label": "Translations", "endpoint": "crm_translations.dashboard",
     "match_blueprint": "crm_translations"},
    {"id": "crm_contracts", "label": "Contracts", "endpoint": "crm_contracts.dashboard",
     "match_blueprint": "crm_contracts"},
    {"id": "financial", "label": "Financial Coaching", "endpoint": "crm_financial.clients_kanban",
     "match_blueprint": "crm_financial"},
    {"id": "planner_week", "label": "Weekly Planner", "endpoint": "planner.planner_week",
     "match": ["planner.planner_week", "planner.planner_team", "planner.projects_list"]},
    {"id": "time_tracking", "label": "Time Tracking", "endpoint": "planner.time_list",
     "match": ["planner.time_list"]},
]
NAV_ITEMS: dict[str, dict] = {item["id"]: item for item in _NAV_ITEMS_LIST}
DEFAULT_LAYOUT: list[dict] = [{"kind": "item", "id": item["id"]} for item in _NAV_ITEMS_LIST]


def validate_layout(raw) -> list[dict] | None:
    """Defensive parse of a layout posted from the "Edit navigation" UI --
    this only ever controls a per-user display preference (never data), so
    unknown/duplicate ids are silently dropped rather than rejecting the
    whole save; returns None only when the overall shape is unusable (not
    a list, or ends up with zero valid slots) so the caller can fall back
    to leaving the previous layout untouched."""
    if not isinstance(raw, list):
        return None
    seen: set[str] = set()
    cleaned: list[dict] = []
    for slot in raw:
        if not isinstance(slot, dict):
            continue
        if slot.get("kind") == "item":
            item_id = slot.get("id")
            if item_id in NAV_ITEMS and item_id not in seen:
                seen.add(item_id)
                cleaned.append({"kind": "item", "id": item_id})
        elif slot.get("kind") == "group":
            label = str(slot.get("label") or "Group").strip()[:40] or "Group"
            items = []
            for item_id in slot.get("items", []):
                if item_id in NAV_ITEMS and item_id not in seen:
                    seen.add(item_id)
                    items.append(item_id)
            if items:
                cleaned.append({"kind": "group", "label": label, "items": items})
    return cleaned or None


def _parse_layout_json(raw_json: str) -> list[dict] | None:
    try:
        parsed = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return validate_layout(parsed)


def _load_raw_layout(user_id: int) -> list[dict]:
    personal = SessionLocal.get(StaffNavLayout, user_id)
    if personal is not None:
        parsed = _parse_layout_json(personal.layout_json)
        if parsed is not None:
            return parsed

    global_row = SessionLocal.get(StaffNavGlobalLayout, GLOBAL_LAYOUT_ID)
    if global_row is not None:
        parsed = _parse_layout_json(global_row.layout_json)
        if parsed is not None:
            return parsed

    return DEFAULT_LAYOUT


def _is_active(item: dict, endpoint: str | None, blueprint: str | None) -> bool:
    if item.get("match_blueprint"):
        return blueprint == item["match_blueprint"]
    return endpoint in item.get("match", [])


def _resolve_item(item_id: str, endpoint: str | None, blueprint: str | None) -> dict | None:
    item = NAV_ITEMS.get(item_id)
    if item is None:
        return None
    return {
        "kind": "item", "id": item_id, "label": item["label"],
        "url": url_for(item["endpoint"]), "active": _is_active(item, endpoint, blueprint),
        "badge_key": item.get("badge"),
    }


def resolve_nav_layout(user_id: int, endpoint: str | None, blueprint: str | None) -> list[dict]:
    """Returns the ordered list of top-nav slots for this user, ready for
    staff_base.html to render -- each slot is either a resolved item dict
    (kind="item") or a resolved group dict (kind="group", its own "items"
    list of resolved item dicts). Any canonical NAV_ITEMS id missing from
    the user's saved layout (e.g. a brand-new tab shipped after they
    customized theirs) is appended at the end automatically, so a future
    feature never silently disappears from a customized nav."""
    raw = _load_raw_layout(user_id)
    slots: list[dict] = []
    seen: set[str] = set()

    for slot in raw:
        if slot.get("kind") == "group":
            resolved_items = [
                r for r in (
                    _resolve_item(item_id, endpoint, blueprint) for item_id in slot.get("items", [])
                ) if r is not None
            ]
            for r in resolved_items:
                seen.add(r["id"])
            if resolved_items:
                slots.append({
                    "kind": "group", "label": slot.get("label") or "Group",
                    "items": resolved_items, "active": any(r["active"] for r in resolved_items),
                })
        else:
            resolved = _resolve_item(slot.get("id"), endpoint, blueprint)
            if resolved is not None:
                slots.append(resolved)
                seen.add(resolved["id"])

    for item_id in NAV_ITEMS:
        if item_id not in seen:
            resolved = _resolve_item(item_id, endpoint, blueprint)
            if resolved is not None:
                slots.append(resolved)

    return slots


def save_layout(user_id: int, raw, scope: str = "personal") -> bool:
    """`scope="personal"` (default) saves only for this collaborator
    (`StaffNavLayout`); `scope="global"` saves it as the org-wide default
    for every collaborator who hasn't personally customized their own
    (`StaffNavGlobalLayout`, a singleton) -- user request 2026-08-02:
    "Salvar para todos colaboradores ou Salvar apenas para mim"."""
    cleaned = validate_layout(raw)
    if cleaned is None:
        return False

    if scope == "global":
        global_row = SessionLocal.get(StaffNavGlobalLayout, GLOBAL_LAYOUT_ID)
        if global_row is None:
            global_row = StaffNavGlobalLayout(
                id=GLOBAL_LAYOUT_ID, layout_json=json.dumps(cleaned), updated_by_user_id=user_id)
            SessionLocal.add(global_row)
        else:
            global_row.layout_json = json.dumps(cleaned)
            global_row.updated_by_user_id = user_id
        return True

    row = SessionLocal.get(StaffNavLayout, user_id)
    if row is None:
        row = StaffNavLayout(user_id=user_id, layout_json=json.dumps(cleaned))
        SessionLocal.add(row)
    else:
        row.layout_json = json.dumps(cleaned)
    return True


def reset_layout(user_id: int) -> None:
    """Reverts THIS collaborator back to whatever the next layer down
    provides (the org-wide global default if one has been saved, else the
    hardcoded DEFAULT_LAYOUT) -- only ever deletes their own personal
    override, never touches the global one."""
    row = SessionLocal.get(StaffNavLayout, user_id)
    if row is not None:
        SessionLocal.delete(row)
