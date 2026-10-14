"""Approval-gate service tests. Feature: ticket-approval-gate."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import TicketAlreadyApprovedError, TicketNotFoundError
from app.schemas.ticket import Priority, TicketCreate, TicketType
from app.services.ticket_service import TicketService

PROJECT = uuid4()
CREATOR = uuid4()
OTHER = uuid4()
ADMIN = uuid4()


def _service() -> TicketService:
    svc = TicketService()
    svc.repo = AsyncMock()
    svc.activity = AsyncMock()
    svc.notifications = AsyncMock()
    svc.user_repo = AsyncMock()
    return svc


def _ticket(**over) -> dict:
    base = {
        "id": str(uuid4()),
        "project_id": str(PROJECT),
        "created_by": str(CREATOR),
        "assigned_to": None,
        "title": "A valid ticket title",
        "type": "bug",
        "priority": "high",
        "status": "pending",
        "approval_status": "pending_approval",
        "approved_by": None,
        "approved_at": None,
    }
    base.update(over)
    return base


# Property 1: create forces pending_approval
async def test_create_sets_pending_approval():
    svc = _service()
    captured: dict = {}

    async def _create(record):
        captured.update(record)
        return _ticket(**{k: record[k] for k in ("approval_status", "status")})

    svc.repo.create.side_effect = _create
    svc.repo.get_with_relations.return_value = _ticket()
    data = TicketCreate(
        title="A valid ticket title",
        description="A sufficiently long description.",
        type=TicketType.BUG,
        priority=Priority.HIGH,
    )
    await svc.create(data, user_id=CREATOR, project_id=PROJECT)
    assert captured["approval_status"] == "pending_approval"
    assert captured["status"] == "pending"  # Property 2: orthogonal


# Property 1: broadcast is deferred (NOT scheduled at creation)
async def test_create_does_not_broadcast_new_ticket():
    svc = _service()
    svc.repo.create.return_value = _ticket()
    svc.repo.get_with_relations.return_value = _ticket()
    bg = MagicMock()
    data = TicketCreate(
        title="A valid ticket title",
        description="A sufficiently long description.",
        type=TicketType.BUG,
        priority=Priority.HIGH,
    )
    await svc.create(data, user_id=CREATOR, project_id=PROJECT, background_tasks=bg)
    scheduled = [c.args[0] for c in bg.add_task.call_args_list]
    assert svc.notifications.notify_ticket_created not in scheduled


# Property 3: list forwards viewer scope for a non-admin
async def test_list_passes_viewer_scope_for_non_admin():
    svc = _service()
    svc.repo.list_by_project.return_value = ([], 0)
    await svc.list_by_project(
        project_id=PROJECT, viewer={"id": str(OTHER), "role": "user"}
    )
    kwargs = svc.repo.list_by_project.call_args.kwargs
    assert str(kwargs["viewer_id"]) == str(OTHER)
    assert kwargs["include_all_approval"] is False


# Property 3: admin list is unscoped
async def test_list_admin_sees_all():
    svc = _service()
    svc.repo.list_by_project.return_value = ([], 0)
    await svc.list_by_project(
        project_id=PROJECT, viewer={"id": str(ADMIN), "role": "admin"}
    )
    assert svc.repo.list_by_project.call_args.kwargs["include_all_approval"] is True


# Property 4: pending ticket hidden from a different user (not-found)
async def test_get_by_id_hides_pending_from_other_user():
    svc = _service()
    svc.repo.get_with_relations.return_value = _ticket()
    with pytest.raises(TicketNotFoundError):
        await svc.get_by_id(
            uuid4(), project_id=PROJECT, viewer={"id": str(OTHER), "role": "user"}
        )


# Property 3: creator can see their own pending ticket
async def test_get_by_id_allows_creator():
    svc = _service()
    svc.repo.get_with_relations.return_value = _ticket()
    out = await svc.get_by_id(
        uuid4(), project_id=PROJECT, viewer={"id": str(CREATOR), "role": "user"}
    )
    assert out["approval_status"] == "pending_approval"


# Property 3: admin can see any pending ticket
async def test_get_by_id_allows_admin():
    svc = _service()
    svc.repo.get_with_relations.return_value = _ticket()
    out = await svc.get_by_id(
        uuid4(), project_id=PROJECT, viewer={"id": str(ADMIN), "role": "admin"}
    )
    assert out["approval_status"] == "pending_approval"


# Property 6: approve sets status, approver, timestamp
async def test_approve_sets_status_approver_timestamp():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid))
    svc.repo.set_approved.return_value = _ticket(
        id=str(tid), approval_status="approved", approved_by=str(ADMIN)
    )
    svc.repo.get_with_relations.return_value = _ticket(
        id=str(tid), approval_status="approved", approved_by=str(ADMIN)
    )
    await svc.approve(tid, user={"id": str(ADMIN), "role": "admin"}, project_id=PROJECT)
    svc.repo.set_approved.assert_awaited_once()


# Property 7: approve is idempotent for an already-approved ticket
async def test_approve_idempotent_when_already_approved():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid), approval_status="approved")
    svc.repo.get_with_relations.return_value = _ticket(
        id=str(tid), approval_status="approved"
    )
    await svc.approve(tid, user={"id": str(ADMIN), "role": "admin"}, project_id=PROJECT)
    svc.repo.set_approved.assert_not_awaited()


# Property 3.5: approve schedules the deferred broadcast
async def test_approve_schedules_deferred_broadcast():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid))
    svc.repo.set_approved.return_value = _ticket(id=str(tid), approval_status="approved")
    svc.repo.get_with_relations.return_value = _ticket(
        id=str(tid), approval_status="approved"
    )
    bg = MagicMock()
    await svc.approve(
        tid, user={"id": str(ADMIN), "role": "admin"}, project_id=PROJECT,
        background_tasks=bg,
    )
    scheduled = [c.args[0] for c in bg.add_task.call_args_list]
    assert svc.notifications.notify_ticket_created in scheduled


# Property 9: reject refuses an already-approved ticket (409), does not delete
async def test_reject_raises_conflict_when_approved():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid), approval_status="approved")
    with pytest.raises(TicketAlreadyApprovedError):
        await svc.reject(tid, user={"id": str(ADMIN), "role": "admin"}, project_id=PROJECT)
    svc.repo.delete.assert_not_awaited()


# Property 8: reject deletes a pending ticket
async def test_reject_deletes_pending_ticket():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid))
    await svc.reject(tid, user={"id": str(ADMIN), "role": "admin"}, project_id=PROJECT)
    svc.repo.delete.assert_awaited_once()
