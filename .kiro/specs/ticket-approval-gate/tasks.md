# Implementation Plan: Ticket Approval Gate

> **For agentic workers:** implement task-by-task, top to bottom. Steps use
> checkbox (`- [ ]`) syntax. This feature changes **access control**, so the
> tests in each task are **mandatory** — write the test, watch it fail, then
> implement (TDD). Do not mark a task done until its tests pass.

**Goal:** Hold new tickets in `pending_approval` (visible only to creator +
admins); admins approve (visible to everyone who can see the project) or reject
(hard delete, after an audit record).

**Architecture:** New `approval_status` column orthogonal to the work `status`;
a viewer-aware approval predicate in the read paths; admin-only approve/reject
endpoints. Layered endpoint → service → repository, matching existing patterns.

**Tech Stack:** FastAPI, Pydantic v2, supabase-py, pytest + pytest-asyncio +
`unittest.mock.AsyncMock` (NO Hypothesis — not a project dependency). Frontend:
Next.js/TypeScript, verified via `tsc` + `next lint` (no test runner exists).

---

## Testing conventions for this plan

- Backend tests live under `support-backend/tests/services/` and
  `support-backend/tests/api/` (dirs already exist with `__init__.py`).
- `asyncio_mode = "auto"` is set, so `async def test_*` needs no decorator.
- Service tests replace `service.repo`, `service.activity`,
  `service.notifications` with `AsyncMock()`. No live database.
- Run backend tests from `support-backend/`: `python -m pytest -q`.

---

## Tasks

### Task 1: Database migration

**Files:**
- Create: `support-backend/migrations/002_add_ticket_approval.sql`

- [ ] **Step 1.1: Write the migration SQL**

```sql
-- ============================================================
-- SUPPORT SYSTEM - 002 ADD TICKET APPROVAL GATE
-- Run this in Supabase SQL Editor AFTER 001_initial_schema.sql
-- ============================================================

ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS approval_status text NOT NULL DEFAULT 'approved'
        CHECK (approval_status IN ('pending_approval', 'approved')),
    ADD COLUMN IF NOT EXISTS approved_by uuid REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS approved_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_tickets_project_approval
    ON tickets(project_id, approval_status);
```

- [ ] **Step 1.2: Validate against a Postgres/Supabase instance**

Apply in the Supabase SQL editor (or `psql`). Confirm:
- Existing rows now have `approval_status = 'approved'` (backfill).
- `approved_by` / `approved_at` are nullable.
- Re-running the file is a no-op (idempotent `IF NOT EXISTS`).

_Requirements: 8.1, 8.2, 8.3_

---

### Task 2: Schema enum + response fields

**Files:**
- Modify: `support-backend/app/schemas/ticket.py`

- [ ] **Step 2.1: Add the `ApprovalStatus` enum**

```python
class ApprovalStatus(str, Enum):
    """Approval gate status (orthogonal to the work-lifecycle status)."""

    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
```

- [ ] **Step 2.2: Add fields to `TicketResponse` and `TicketListResponse`**

Add to both models (defaulting to `APPROVED` so pre-column rows deserialize):

```python
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
```

Leave `TicketCreate` and `TicketUpdate` unchanged (approval is server-controlled).

- [ ] **Step 2.3: Verify it imports**

Run (from `support-backend/`): `python -c "import app.schemas.ticket"`
Expected: no error.

_Requirements: 1.2, 3.2_

---

### Task 3: Audit events + exception

**Files:**
- Modify: `support-backend/app/audit/events.py`
- Modify: `support-backend/app/core/exceptions.py`

- [ ] **Step 3.1: Add audit constants** to `AuditEvents`

```python
    TICKET_APPROVED = "ticket.approved"
    TICKET_REJECTED = "ticket.rejected"
```

- [ ] **Step 3.2: Add the conflict exception** to `app/core/exceptions.py`

The base is `AppException.__init__(self, message=None, details=None)` with
`status_code`/`error_code` as class attributes (confirmed — mirror
`TicketNotFoundError`):

```python
class TicketAlreadyApprovedError(AppException):
    status_code = 409
    error_code = "TICKET_ALREADY_APPROVED"
    message = "Ticket has already been approved"

    def __init__(self, ticket_id: str) -> None:
        super().__init__(
            message=f"Ticket '{ticket_id}' has already been approved",
            details={"ticket_id": ticket_id},
        )
```

_Requirements: 4.3, 7.1, 7.2_

---

### Task 4: Repository — viewer scoping, pending list, set_approved

**Files:**
- Modify: `support-backend/app/db/repositories/ticket_repo.py`

- [ ] **Step 4.1: Add viewer scoping params to `list_by_project`**

Add to the signature: `viewer_id: Optional[UUID] = None`,
`include_all_approval: bool = False`. After the existing `.eq("project_id", ...)`
and the optional filters, before `.order(...)`, add:

```python
        if not include_all_approval and viewer_id is not None:
            query = query.or_(
                f"approval_status.eq.approved,created_by.eq.{viewer_id}"
            )
```

- [ ] **Step 4.2: Add the same scoping to `search_fulltext`**

Add the same two params. Append the predicate in the **filter** position
(after `.text_search(...)`, alongside the `.eq` filters — NOT before `.range()`,
per the existing supabase-py ordering comment):

```python
        if not include_all_approval and viewer_id is not None:
            db_query = db_query.or_(
                f"approval_status.eq.approved,created_by.eq.{viewer_id}"
            )
```

- [ ] **Step 4.3: Add the same scoping to `fetch_for_aggregation` and `count_by_status`**

`fetch_for_aggregation`: add `viewer_id`/`include_all_approval`; when not
`include_all_approval`, append
`query = query.or_(f"approval_status.eq.approved,created_by.eq.{viewer_id}")`
(when `viewer_id` is None this collapses to `approval_status.eq.approved` — write
that branch explicitly). `count_by_status`: add the same optional scoping to each
per-status query.

- [ ] **Step 4.4: Add `list_pending`**

```python
    async def list_pending(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> tuple[list[dict], int]:
        """List tickets awaiting approval in a project (admin queue)."""
        offset = (page - 1) * page_size
        query = (
            self._table()
            .select(
                "*, "
                "created_by_user:users!tickets_created_by_fkey(id, name, email), "
                "assigned_to_user:users!tickets_assigned_to_fkey(id, name, email)",
                count="exact",
            )
            .eq("project_id", str(project_id))
            .eq("approval_status", "pending_approval")
            .order(order_by, desc=order_desc)
            .range(offset, offset + page_size - 1)
        )
        response = query.execute()
        total = response.count if response.count is not None else 0
        return response.data or [], total
```

- [ ] **Step 4.5: Add `set_approved`**

```python
    async def set_approved(self, ticket_id: UUID, approved_by: UUID) -> dict:
        """Mark a ticket approved, recording the approver and timestamp."""
        from datetime import datetime, timezone

        response = (
            self._table()
            .update(
                {
                    "approval_status": "approved",
                    "approved_by": str(approved_by),
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", str(ticket_id))
            .execute()
        )
        return response.data[0] if response.data else {}
```

- [ ] **Step 4.6: Verify import**

Run: `python -c "import app.db.repositories.ticket_repo"` → no error.

_Requirements: 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 3.3, 6.1, 6.3_

---

### Task 5: Service tests (write first — RED)

**Files:**
- Create: `support-backend/tests/services/test_ticket_approval.py`

- [ ] **Step 5.1: Write the failing service tests**

```python
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
    captured = {}

    async def _create(record):
        captured.update(record)
        return _ticket(id=str(uuid4()), **{k: record[k] for k in ("approval_status",)})

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
    scheduled = [c.args[0].__name__ for c in bg.add_task.call_args_list]
    assert "notify_ticket_created" not in scheduled


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
    t = _ticket()
    svc.repo.get_with_relations.return_value = t
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
    assert str(svc.repo.set_approved.call_args.kwargs.get("approved_by") or
               svc.repo.set_approved.call_args.args[1]) == str(ADMIN)


# Property 7: approve is idempotent for an already-approved ticket
async def test_approve_idempotent_when_already_approved():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid), approval_status="approved")
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
    scheduled = [c.args[0].__name__ for c in bg.add_task.call_args_list]
    assert "notify_ticket_created" in scheduled


# Property 8/9: reject audits before delete; refuses an approved ticket
async def test_reject_raises_conflict_when_approved():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid), approval_status="approved")
    with pytest.raises(TicketAlreadyApprovedError):
        await svc.reject(tid, user={"id": str(ADMIN), "role": "admin"}, project_id=PROJECT)
    svc.repo.delete.assert_not_awaited()


async def test_reject_deletes_pending_ticket():
    svc = _service()
    tid = uuid4()
    svc.repo.get_by_id.return_value = _ticket(id=str(tid))
    await svc.reject(tid, user={"id": str(ADMIN), "role": "admin"}, project_id=PROJECT)
    svc.repo.delete.assert_awaited_once()
```

- [ ] **Step 5.2: Run the tests — expect FAIL (RED)**

Run (from `support-backend/`): `python -m pytest tests/services/test_ticket_approval.py -q`
Expected: failures/errors (methods `approve`, `reject`, `list_pending`, the
`viewer`/scoping params, and `TicketAlreadyApprovedError` do not exist yet).

_Requirements: 1.1, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.4, 3.5, 4.1, 4.3, 7.2_

---

### Task 6: Service — implement to pass the tests (GREEN)

**Files:**
- Modify: `support-backend/app/services/ticket_service.py`

- [ ] **Step 6.1: `create` sets pending_approval and defers the broadcast**

In `create`, after `record["status"] = "pending"`, add:
`record["approval_status"] = "pending_approval"`. Remove the
`background_tasks.add_task(self.notifications.notify_ticket_created, ...)` call
from `create` (keep the pre-assigned-assignee notification only if desired, but
do NOT broadcast the new ticket). The admin "awaiting approval" nudge can reuse
`notify_ticket_created` semantics later at approval time.

- [ ] **Step 6.2: `get_by_id` becomes viewer-aware**

Change signature to
`async def get_by_id(self, ticket_id, project_id, viewer: Optional[dict] = None)`.
After the existing project check, add:

```python
        if viewer is not None:
            is_admin = viewer.get("role") == "admin"
            is_creator = str(ticket.get("created_by")) == str(viewer.get("id"))
            if (
                ticket.get("approval_status") == "pending_approval"
                and not is_admin
                and not is_creator
            ):
                raise TicketNotFoundError(ticket_id=str(ticket_id))
```

- [ ] **Step 6.3: `list_by_project` forwards viewer scope**

Add required `viewer: dict` param; compute and forward:

```python
        is_admin = viewer.get("role") == "admin"
        viewer_id = None if is_admin else viewer.get("id")
        return await self.repo.list_by_project(
            ...,
            viewer_id=UUID(str(viewer_id)) if viewer_id else None,
            include_all_approval=is_admin,
        )
```

- [ ] **Step 6.4: Add `list_pending`**

```python
    async def list_pending(
        self, project_id: UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        return await self.repo.list_pending(
            project_id=project_id, page=page, page_size=page_size
        )
```

- [ ] **Step 6.5: Add `approve`**

```python
    async def approve(
        self, ticket_id, user, project_id,
        background_tasks=None, ip_address=None,
    ) -> dict:
        existing = await self.repo.get_by_id(ticket_id)
        if not existing or str(existing.get("project_id")) != str(project_id):
            raise TicketNotFoundError(ticket_id=str(ticket_id))
        if existing.get("approval_status") == "approved":
            return await self.get_by_id(ticket_id, project_id)  # idempotent
        await self.repo.set_approved(ticket_id, UUID(str(user["id"])))
        await audit_logger.log(
            actor_id=UUID(str(user["id"])),
            action=AuditEvents.TICKET_APPROVED,
            resource_type=ResourceTypes.TICKET,
            resource_id=ticket_id,
            project_id=project_id,
            metadata={"title": existing.get("title")},
            ip_address=ip_address,
        )
        if background_tasks is not None:
            background_tasks.add_task(
                self.notifications.notify_ticket_created,
                ticket_id,
                UUID(str(existing.get("created_by"))),
            )
            if existing.get("assigned_to"):
                background_tasks.add_task(
                    self.notifications.notify_ticket_assigned,
                    ticket_id,
                    UUID(str(existing["assigned_to"])),
                    UUID(str(user["id"])),
                )
        return await self.get_by_id(ticket_id, project_id)
```

- [ ] **Step 6.6: Add `reject`**

```python
    async def reject(self, ticket_id, user, project_id, ip_address=None) -> None:
        existing = await self.repo.get_by_id(ticket_id)
        if not existing or str(existing.get("project_id")) != str(project_id):
            raise TicketNotFoundError(ticket_id=str(ticket_id))
        if existing.get("approval_status") == "approved":
            raise TicketAlreadyApprovedError(ticket_id=str(ticket_id))
        await audit_logger.log(  # BEFORE delete so it is traceable
            actor_id=UUID(str(user["id"])),
            action=AuditEvents.TICKET_REJECTED,
            resource_type=ResourceTypes.TICKET,
            resource_id=ticket_id,
            project_id=project_id,
            metadata={
                "title": existing.get("title"),
                "created_by": existing.get("created_by"),
            },
            ip_address=ip_address,
        )
        await self.repo.delete(ticket_id)
```

Add `TicketAlreadyApprovedError` to the imports from `app.core.exceptions`.

- [ ] **Step 6.7: Thread `viewer` into the comment path**

In `add_comment`, change the guard call to
`await self.get_by_id(ticket_id, project_id=project_id, viewer={"id": user_id, "role": ...})`.
Since `add_comment` only receives `user_id` today, pass the creator-or-not check
by fetching the role, OR accept the acting `user` dict — simplest: have the
endpoint pass `user` and forward it. (Keep the change minimal and consistent
with how the endpoint calls it.)

- [ ] **Step 6.8: Run service tests — expect PASS (GREEN)**

Run: `python -m pytest tests/services/test_ticket_approval.py -q`
Expected: all pass. Fix implementation (not tests) until green.

_Requirements: 1.1, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 7.1, 7.2, 7.3_

---

### Task 7: Endpoint tests (write first — RED)

**Files:**
- Create: `support-backend/tests/api/test_ticket_approval_endpoints.py`

- [ ] **Step 7.1: Write failing endpoint tests**

```python
"""Approval-gate endpoint auth tests. Feature: ticket-approval-gate."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_project, get_current_user
from app.main import app

PID = uuid4()


def _override(user_role: str):
    app.dependency_overrides[get_current_user] = lambda: {"id": str(uuid4()), "role": user_role}
    app.dependency_overrides[get_current_project] = lambda: PID


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# Property 10: approve is admin-only
async def test_approve_forbidden_for_non_admin():
    _override("user")
    async with await _client() as ac:
        r = await ac.post(f"/api/v1/tickets/{uuid4()}/approve")
    assert r.status_code == 403


# Property 10: reject is admin-only
async def test_reject_forbidden_for_non_admin():
    _override("user")
    async with await _client() as ac:
        r = await ac.post(f"/api/v1/tickets/{uuid4()}/reject")
    assert r.status_code == 403


# Property 6.2: approval queue is admin-only
async def test_pending_queue_forbidden_for_non_admin():
    _override("user")
    async with await _client() as ac:
        r = await ac.get("/api/v1/tickets/pending-approval")
    assert r.status_code == 403
```

Note: the API prefix is `/api/v1` (confirmed: `main.py` mounts `api_router` with
`prefix="/api/v1"`, tickets router at `/tickets`). These tests exercise the
`get_admin_user` gate; they do not need a stubbed service because authorization
fails before the service runs.

- [ ] **Step 7.2: Run — expect FAIL (RED)**

Run: `python -m pytest tests/api/test_ticket_approval_endpoints.py -q`
Expected: 404s (routes don't exist yet) → tests fail.

_Requirements: 5.1, 5.2, 6.2_

---

### Task 8: Endpoints — implement (GREEN)

**Files:**
- Modify: `support-backend/app/api/v1/endpoints/tickets.py`

- [ ] **Step 8.1: Thread viewer into read endpoints**

`list_tickets` → `service.list_by_project(..., viewer=user)`.
`get_ticket` → `service.get_by_id(ticket_id, project_id=project_id, viewer=user)`.

- [ ] **Step 8.2: Add the admin-only queue (declare BEFORE `/{ticket_id}` routes)**

```python
@router.get("/pending-approval")
async def list_pending_tickets(
    page: int = 1,
    page_size: int = 20,
    user: dict = Depends(get_admin_user),
    project_id: UUID = Depends(get_current_project),
) -> dict:
    """List tickets awaiting approval in the current project (admin only)."""
    service = TicketService()
    tickets, total = await service.list_pending(project_id, page, page_size)
    return {
        "data": tickets,
        "pagination": build_pagination(total, page, page_size).model_dump(),
    }
```

Add `get_admin_user` to the imports from `app.dependencies`.

- [ ] **Step 8.3: Add approve / reject**

```python
@router.post("/{ticket_id}/approve")
async def approve_ticket(
    ticket_id: UUID,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_admin_user),
    project_id: UUID = Depends(get_current_project),
    ip_address: Optional[str] = Depends(get_client_ip),
) -> dict:
    """Approve a pending ticket (admin only)."""
    service = TicketService()
    ticket = await service.approve(
        ticket_id, user=user, project_id=project_id,
        background_tasks=background_tasks, ip_address=ip_address,
    )
    return {"data": ticket, "message": "Ticket approved"}


@router.post("/{ticket_id}/reject", status_code=204)
async def reject_ticket(
    ticket_id: UUID,
    user: dict = Depends(get_admin_user),
    project_id: UUID = Depends(get_current_project),
    ip_address: Optional[str] = Depends(get_client_ip),
) -> None:
    """Reject (permanently delete) a pending ticket (admin only)."""
    service = TicketService()
    await service.reject(
        ticket_id, user=user, project_id=project_id, ip_address=ip_address
    )
    return None
```

- [ ] **Step 8.4: Run endpoint tests — expect PASS (GREEN)**

Run: `python -m pytest tests/api/test_ticket_approval_endpoints.py -q`
Expected: all pass (403s now come from `get_admin_user`, routes resolve).

_Requirements: 2.1, 2.3, 2.4, 3.1, 4.1, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2_

---

### Task 9: Backend checkpoint

- [ ] **Step 9.1:** Run the full backend suite + linters from `support-backend/`:
  `python -m pytest -q && ruff check . && mypy app`
  Expected: tests pass, no lint errors, mypy clean (strict mode). Fix any issue
  before continuing. Ask the user if a design question arises.

---

### Task 10: Frontend test harness (Vitest scaffold)

**Files:**
- Modify: `support-frontend/package.json`
- Create: `support-frontend/vitest.config.ts`
- Create: `support-frontend/vitest.setup.ts`
- Create: `support-frontend/src/lib/__tests__/sanity.test.ts` (proves the harness runs)

> This stands up the test runner the project lacks so the approval-gate UI can
> have real unit tests (Task 11). Pin exact versions per `tech-stack.md`.

- [ ] **Step 10.1: Add dev dependencies and scripts to `package.json`**

Add to `devDependencies` (exact versions, compatible with Next 14 / React 18):

```json
    "vitest": "2.1.9",
    "@vitest/coverage-v8": "2.1.9",
    "jsdom": "25.0.1",
    "@testing-library/react": "16.1.0",
    "@testing-library/jest-dom": "6.6.3",
    "@testing-library/user-event": "14.5.2",
    "@vitejs/plugin-react": "4.3.4"
```

Add to `scripts`:

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 10.2: Create `vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
  resolve: {
    alias: { "@": resolve(__dirname, "./src") },
  },
});
```

- [ ] **Step 10.3: Create `vitest.setup.ts`**

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 10.4: Create a sanity test and watch it pass**

```typescript
// src/lib/__tests__/sanity.test.ts
import { describe, expect, it } from "vitest";

describe("vitest harness", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 10.5: Install and run**

Run (from `support-frontend/`): `npm install` then `npm test`
Expected: the sanity test passes; the runner is operational.

_Requirements: (enabler for 9.x testing)_

---

### Task 11: Frontend — types, API, hooks, UI (with tests)

**Files:**
- Modify: `support-frontend/src/types/ticket.ts`
- Modify: `support-frontend/src/lib/ticketsApi.ts`
- Modify: `support-frontend/src/hooks/useTickets.ts`
- Modify: `support-frontend/src/components/tickets/TicketTable.tsx`
- Modify: ticket detail view under `support-frontend/src/app/(protected)/tickets/[id]/`
- Create: `support-frontend/src/components/tickets/__tests__/ApprovalBadge.test.tsx`

- [ ] **Step 11.1: Types** — in `ticket.ts`:

```typescript
export type ApprovalStatus = "pending_approval" | "approved";
```

Add to `interface Ticket`:

```typescript
  approval_status: ApprovalStatus;
  approved_by: string | null;
  approved_at: string | null;
```

- [ ] **Step 11.2: API client** — in `ticketsApi.ts`, mirror existing functions:

```typescript
export async function listPendingTickets(params?: { page?: number; page_size?: number }) { /* GET /tickets/pending-approval */ }
export async function approveTicket(id: string) { /* POST /tickets/{id}/approve */ }
export async function rejectTicket(id: string) { /* POST /tickets/{id}/reject */ }
```

(Match the exact signature/return conventions of the existing `createTicket` /
`deleteTicket` in the same file.)

- [ ] **Step 11.3: Hooks** — in `useTickets.ts`:
  `usePendingTickets()` (query), `useApproveTicket()` and `useRejectTicket()`
  (mutations that `queryClient.invalidateQueries` the tickets + detail keys on
  success), matching the existing `useDeleteTicket` pattern.

- [ ] **Step 11.4: Badge component + test (TDD)** — extract a small
  `ApprovalBadge` component that renders when `approval_status === "pending_approval"`.
  Write the test FIRST:

```tsx
// src/components/tickets/__tests__/ApprovalBadge.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApprovalBadge } from "@/components/tickets/ApprovalBadge";

describe("ApprovalBadge", () => {
  it("shows pending label when pending_approval", () => {
    render(<ApprovalBadge status="pending_approval" />);
    expect(screen.getByText(/pending approval/i)).toBeInTheDocument();
  });

  it("renders nothing when approved", () => {
    const { container } = render(<ApprovalBadge status="approved" />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

Run `npm test` → fails (component missing) → implement `ApprovalBadge` → passes.
Then use the badge in `TicketTable` and the detail header.

- [ ] **Step 11.5: Admin actions** — on the detail page, when the user is admin
  and the ticket is pending, show "Approve" and "Reject". "Reject" opens the
  existing `ConfirmDialog` warning the deletion is permanent, then calls
  `useRejectTicket`. Surface the pending queue via `usePendingTickets()`.

- [ ] **Step 11.6: Verify frontend** — from `support-frontend/`:
  `npm test && npx tsc --noEmit && npm run lint`
  Expected: tests pass, no type errors, no lint errors.

_Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

---

### Task 12: Documentation

**Files:**
- Modify: `docs/DATABASE_SCHEMA.md`, `docs/API_SPEC.md`, `README.md`

- [ ] **Step 12.1:** Document the new `tickets` columns + index in
  `DATABASE_SCHEMA.md`; the three new endpoints and the new response fields in
  `API_SPEC.md`; and the approval gate in the `README.md` ticket-lifecycle
  section.

_Requirements: documentation for 8.1, 3.x, 4.x, 6.x_

---

### Task 13: Final checkpoint

- [ ] **Step 13.1:** Full verification:
  - Backend (`support-backend/`): `python -m pytest -q && ruff check . && mypy app`
  - Frontend (`support-frontend/`): `npm test && npx tsc --noEmit && npm run lint`
- [ ] **Step 13.2:** Confirm migration `002` has been applied to the target
  Supabase instance before deploying the backend.
- [ ] **Step 13.3:** Commit, push the branch to `origin`, and open the PR to
  `Tayyab16203/support-system`. Ask the user before opening the PR.

## Notes

- **Tests are mandatory** (not `*`-optional) — this feature changes access
  control. Each service/endpoint task follows RED → GREEN.
- No new dependencies: tests use stdlib `unittest.mock` + the installed pytest.
- `approval_status` is **separate** from the work `status` enum — never add
  approval values to the `status` CHECK constraint.
- Visibility denial reuses `TicketNotFoundError` so pending tickets are not
  enumerable (Property 4).
- S3 objects for a rejected ticket's attachments are not swept by the DB cascade
  (same as existing delete) — out of scope, noted in design.
