"""Attachment approval-scoping tests. Feature: ticket-approval-gate."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import TicketNotFoundError
from app.services.upload_service import UploadService

PROJECT = uuid4()
CREATOR = uuid4()
OTHER = uuid4()


def _svc() -> UploadService:
    s = UploadService()
    s.repo = AsyncMock()
    s.ticket_repo = AsyncMock()
    return s


def _pending_ticket() -> dict:
    return {
        "id": str(uuid4()),
        "project_id": str(PROJECT),
        "created_by": str(CREATOR),
        "approval_status": "pending_approval",
    }


async def test_list_attachments_hides_pending_from_other():
    s = _svc()
    s.ticket_repo.get_by_id.return_value = _pending_ticket()
    with pytest.raises(TicketNotFoundError):
        await s.list_attachments(uuid4(), viewer={"id": str(OTHER), "role": "user"})


async def test_list_attachments_allows_creator():
    s = _svc()
    s.ticket_repo.get_by_id.return_value = _pending_ticket()
    s.repo.list_by_ticket.return_value = []
    out = await s.list_attachments(uuid4(), viewer={"id": str(CREATOR), "role": "user"})
    assert out == []
