"""Ticket repository for data access."""

from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

from app.db.repositories.base_repo import BaseRepository
from app.integrations.supabase.client import get_supabase_client


class TicketRepo(BaseRepository):
    """Data access layer for tickets with project scoping and full-text search."""

    table_name = "tickets"

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        ticket_type: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[UUID] = None,
        created_by: Optional[UUID] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        viewer_id: Optional[UUID] = None,
        include_all_approval: bool = False,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> tuple[list[dict], int]:
        """List tickets filtered by project with optional additional filters.

        Args:
            project_id: Project UUID to filter by.
            page: Page number.
            page_size: Items per page.
            status: Optional status filter.
            ticket_type: Optional type filter.
            priority: Optional priority filter.
            assigned_to: Optional assignee filter.
            created_by: Optional creator filter.
            date_from: Optional ISO datetime; include tickets created at/after it.
            date_to: Optional ISO datetime; include tickets created at/before it.
            order_by: Sort column.
            order_desc: Sort direction.

        Returns:
            Tuple of (tickets list, total count).
        """
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
        )

        if status:
            query = query.eq("status", status)
        if ticket_type:
            query = query.eq("type", ticket_type)
        if priority:
            query = query.eq("priority", priority)
        if assigned_to:
            query = query.eq("assigned_to", str(assigned_to))
        if created_by:
            query = query.eq("created_by", str(created_by))
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)

        if include_all_approval:
            pass
        elif viewer_id is not None:
            query = query.or_(f"approval_status.eq.approved,created_by.eq.{viewer_id}")
        else:
            query = query.eq("approval_status", "approved")

        query = query.order(order_by, desc=order_desc)
        query = query.range(offset, offset + page_size - 1)

        response = query.execute()
        total = response.count if response.count is not None else 0
        return response.data or [], total

    async def set_unassigned(self, ticket_id: UUID) -> dict:
        """Clear a ticket's assignee (set assigned_to to NULL).

        BaseRepository.update strips None values, so unassigning must be done
        with an explicit update that writes NULL.

        Args:
            ticket_id: UUID of the ticket to unassign.

        Returns:
            The updated ticket record.
        """
        response = (
            self._table()
            .update({"assigned_to": None})
            .eq("id", str(ticket_id))
            .execute()
        )
        return response.data[0] if response.data else {}

    async def get_with_relations(self, ticket_id: UUID) -> Optional[dict]:
        """Get a ticket with related user data.

        Args:
            ticket_id: UUID of the ticket.

        Returns:
            Ticket dict with nested user info, or None.
        """
        response = (
            self._table()
            .select(
                "*, "
                "created_by_user:users!tickets_created_by_fkey(id, name, email), "
                "assigned_to_user:users!tickets_assigned_to_fkey(id, name, email)"
            )
            .eq("id", str(ticket_id))
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    async def search_fulltext(
        self,
        query: str,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        ticket_type: Optional[str] = None,
        priority: Optional[str] = None,
        viewer_id: Optional[UUID] = None,
        include_all_approval: bool = False,
    ) -> tuple[list[dict], int]:
        """Full-text search on tickets using PostgreSQL tsvector.

        Args:
            query: Search query string.
            project_id: Project to search within.
            page: Page number.
            page_size: Items per page.
            status: Optional status filter.
            ticket_type: Optional type filter.
            priority: Optional priority filter.

        Returns:
            Tuple of (matching tickets, total count).
        """
        offset = (page - 1) * page_size

        # Apply pagination (.range) on the select builder BEFORE filter methods,
        # since filter methods return a different builder type in supabase-py.
        db_query = (
            self._table()
            .select("*", count="exact")
            .range(offset, offset + page_size - 1)
            .eq("project_id", str(project_id))
            .text_search("search_vector", query, options={"config": "english"})
        )

        if status:
            db_query = db_query.eq("status", status)
        if ticket_type:
            db_query = db_query.eq("type", ticket_type)
        if priority:
            db_query = db_query.eq("priority", priority)

        if include_all_approval:
            pass
        elif viewer_id is not None:
            db_query = db_query.or_(
                f"approval_status.eq.approved,created_by.eq.{viewer_id}"
            )
        else:
            db_query = db_query.eq("approval_status", "approved")

        response = db_query.execute()
        total = response.count if response.count is not None else 0
        return response.data or [], total

    async def count_active_assignments(self, user_id: UUID) -> int:
        """Count tickets currently assigned to a user (active work).

        Args:
            user_id: The user UUID to check.

        Returns:
            The number of tickets where the user is the current assignee.
        """
        response = (
            self._table()
            .select("id", count="exact")
            .eq("assigned_to", str(user_id))
            .execute()
        )
        return response.count or 0

    async def reassign_created_by(self, from_user_id: UUID, to_user_id: UUID) -> None:
        """Repoint the creator of a user's tickets to another user.

        Used when hard-deleting a user: their created tickets are inherited by
        the placeholder so the NOT NULL ``created_by`` foreign key stays valid.

        Args:
            from_user_id: The departing user whose tickets are moved.
            to_user_id: The user (placeholder) to inherit them.
        """
        self._table().update({"created_by": str(to_user_id)}).eq(
            "created_by", str(from_user_id)
        ).execute()

    async def count_by_project(self, project_id: UUID) -> int:
        """Count all tickets belonging to a project.

        Used to warn an admin how many tickets a project delete would cascade.

        Args:
            project_id: The project UUID.

        Returns:
            The number of tickets in the project.
        """
        response = (
            self._table()
            .select("id", count="exact")
            .eq("project_id", str(project_id))
            .execute()
        )
        return response.count or 0

    async def fetch_for_aggregation(
        self,
        project_ids: Optional[list[UUID]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        involving_user_id: Optional[UUID] = None,
        viewer_id: Optional[UUID] = None,
        include_all_approval: bool = False,
    ) -> list[dict]:
        """Fetch lightweight ticket rows for dashboard aggregation.

        Selects only the columns needed to compute KPIs (status, type,
        priority, timestamps, creator, assignee, project) and lets the service
        do the grouping in Python. This avoids one round-trip per bucket while
        keeping the query simple, since PostgREST has no native GROUP BY.

        Args:
            project_ids: Optional list of project UUIDs to restrict to. When
                provided but empty, returns ``[]`` without querying (no
                project is in scope, e.g. no public projects exist).
            date_from: Optional ISO datetime; include tickets created at/after.
            date_to: Optional ISO datetime; include tickets created at/before.
            involving_user_id: Optional user filter for the personal dashboard.
                When set, only tickets the user created *or* is assigned to are
                returned (so their created / assigned / completed counts can be
                derived in the service).

        Returns:
            List of ticket dicts with keys: id, project_id, status, type,
            priority, created_by, assigned_to, created_at, updated_at.
        """
        if project_ids is not None and len(project_ids) == 0:
            return []

        query = self._table().select(
            "id, project_id, status, type, priority, created_by, assigned_to, "
            "created_at, updated_at"
        )

        if project_ids:
            query = query.in_("project_id", [str(pid) for pid in project_ids])
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)
        if involving_user_id is not None:
            uid = str(involving_user_id)
            # Tickets the user created OR is currently assigned to.
            query = query.or_(f"created_by.eq.{uid},assigned_to.eq.{uid}")

        if include_all_approval:
            pass
        elif viewer_id is not None:
            query = query.or_(f"approval_status.eq.approved,created_by.eq.{viewer_id}")
        else:
            query = query.eq("approval_status", "approved")

        response = query.execute()
        return response.data or []

    async def count_by_status(
        self,
        project_id: Optional[UUID] = None,
        viewer_id: Optional[UUID] = None,
        include_all_approval: bool = False,
    ) -> dict[str, int]:
        """Count tickets grouped by status.

        Args:
            project_id: Optional project filter. If None, counts across all projects.

        Returns:
            Dict of status -> count.
        """
        statuses = ["pending", "in_progress", "paused", "in_review", "completed"]
        counts: dict[str, int] = {}

        for status in statuses:
            query = self._table().select("id", count="exact").eq("status", status)
            if project_id:
                query = query.eq("project_id", str(project_id))
            if include_all_approval:
                pass
            elif viewer_id is not None:
                query = query.or_(
                    f"approval_status.eq.approved,created_by.eq.{viewer_id}"
                )
            else:
                query = query.eq("approval_status", "approved")
            response = query.execute()
            counts[status] = response.count if response.count is not None else 0

        return counts

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

    async def set_approved(self, ticket_id: UUID, approved_by: UUID) -> dict:
        """Mark a ticket approved, recording the approver and timestamp."""
        response = (
            self._table()
            .update(
                {
                    "approval_status": "approved",
                    "approved_by": str(approved_by),
                    "approved_at": datetime.now(UTC).isoformat(),
                }
            )
            .eq("id", str(ticket_id))
            .execute()
        )
        return response.data[0] if response.data else {}
