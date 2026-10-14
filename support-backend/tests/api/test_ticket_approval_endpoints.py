"""Approval-gate endpoint auth tests. Feature: ticket-approval-gate."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_project, get_current_user
from app.main import app

PID = uuid4()


def _override(user_role: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": str(uuid4()),
        "role": user_role,
    }
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
