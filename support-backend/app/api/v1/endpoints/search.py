"""Search and saved filters endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_project, get_current_user
from app.schemas.common import build_pagination
from app.schemas.search import SavedFilterCreate
from app.services.search_service import SearchService

router = APIRouter()


@router.get("")
async def search_tickets(
    q: str = Query(..., min_length=2, description="Search query (min 2 chars)"),
    status: Optional[str] = None,
    type: Optional[str] = Query(None),
    priority: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user: dict = Depends(get_current_user),
    project_id: UUID = Depends(get_current_project),
) -> dict:
    """Full-text search across tickets in the current project.

    Uses PostgreSQL ``tsvector`` matching (via SearchService) and returns each
    result with a ``relevance_score`` and a ``highlight`` block of marked terms.
    """
    service = SearchService()
    results, total = await service.search(
        query=q,
        project_id=project_id,
        filters={"status": status, "type": type, "priority": priority},
        page=page,
        page_size=page_size,
        viewer=user,
    )
    return {
        "data": results,
        "pagination": build_pagination(total, page, page_size).model_dump(),
    }


@router.get("/filters")
async def get_saved_filters(
    user: dict = Depends(get_current_user),
) -> dict:
    """Get saved filters for the current user."""
    service = SearchService()
    filters = await service.get_saved_filters(user_id=user["id"])
    return {"data": filters}


@router.post("/filters", status_code=201)
async def save_filter(
    payload: SavedFilterCreate,
    user: dict = Depends(get_current_user),
) -> dict:
    """Save a filter combination for the current user."""
    service = SearchService()
    saved = await service.save_filter(
        user_id=user["id"], name=payload.name, filters=payload.filters
    )
    return {"data": saved, "message": "Filter saved"}


@router.delete("/filters/{filter_id}", status_code=204)
async def delete_filter(
    filter_id: UUID,
    user: dict = Depends(get_current_user),
) -> None:
    """Delete a saved filter owned by the current user."""
    service = SearchService()
    await service.delete_filter(filter_id=filter_id, user_id=user["id"])
    return None
