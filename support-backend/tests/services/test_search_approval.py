"""Search approval-scoping tests. Feature: ticket-approval-gate."""

from unittest.mock import AsyncMock
from uuid import uuid4

from app.services.search_service import SearchService

PROJECT = uuid4()
OTHER = uuid4()
ADMIN = uuid4()


def _svc() -> SearchService:
    s = SearchService()
    s.repo = AsyncMock()
    s.user_repo = AsyncMock()
    return s


async def test_search_forwards_viewer_scope_for_non_admin():
    s = _svc()
    s.repo.search_fulltext.return_value = ([], 0)
    await s.search(
        query="hello",
        project_id=PROJECT,
        filters={},
        viewer={"id": str(OTHER), "role": "user"},
    )
    kwargs = s.repo.search_fulltext.call_args.kwargs
    assert str(kwargs["viewer_id"]) == str(OTHER)
    assert kwargs["include_all_approval"] is False


async def test_search_admin_sees_all():
    s = _svc()
    s.repo.search_fulltext.return_value = ([], 0)
    await s.search(
        query="hello",
        project_id=PROJECT,
        filters={},
        viewer={"id": str(ADMIN), "role": "admin"},
    )
    assert s.repo.search_fulltext.call_args.kwargs["include_all_approval"] is True
