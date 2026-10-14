"""Ticket business logic service."""

from typing import Any, Optional
from uuid import UUID

from fastapi import BackgroundTasks

from app.audit import AuditEvents, ResourceTypes, audit_logger
from app.core.exceptions import (
    ForbiddenError,
    TicketAlreadyApprovedError,
    TicketNotFoundError,
)
from app.core.logging import get_logger
from app.db.repositories.ticket_repo import TicketRepo
from app.db.repositories.user_repo import UserRepo
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services.activity_service import ActivityService
from app.services.notification_service import NotificationService

logger = get_logger(__name__)


class TicketService:
    """Business logic for ticket operations.

    Tickets are always scoped to a project. Every read/update/delete verifies
    the target ticket belongs to the caller's current project to prevent
    cross-project data leaks.

    Side effects such as email notifications run via FastAPI ``BackgroundTasks``
    so they never block or fail the originating request.
    """

    def __init__(self) -> None:
        self.repo = TicketRepo()
        self.user_repo = UserRepo()
        self.activity = ActivityService()
        self.notifications = NotificationService()

    async def create(
        self,
        data: TicketCreate,
        user_id: UUID,
        project_id: UUID,
        background_tasks: Optional[BackgroundTasks] = None,
        ip_address: Optional[str] = None,
    ) -> dict:
        """Create a new ticket in the given project.

        Args:
            data: Validated ticket creation payload.
            user_id: UUID of the authenticated creator (the actor).
            project_id: UUID of the current project (from context).
            background_tasks: Optional queue; when provided, a "new ticket"
                email is sent to all admins (except the creator).

        Returns:
            The created ticket with related user data.
        """
        record: dict[str, Any] = data.model_dump(exclude_none=True)
        record["project_id"] = str(project_id)
        record["created_by"] = str(user_id)
        record["status"] = "pending"  # New tickets always start as pending.
        # Approval is orthogonal to workflow status: every new ticket must be
        # approved by an admin before it becomes visible to other users. The
        # "new ticket" broadcast is deferred until approval (see ``approve``).
        record["approval_status"] = "pending_approval"

        # Enum fields serialize to their string values for storage.
        record["type"] = data.type.value
        record["priority"] = data.priority.value
        if data.assigned_to is not None:
            record["assigned_to"] = str(data.assigned_to)

        created = await self.repo.create(record)
        ticket_id = created.get("id")
        logger.info(
            "ticket_created",
            extra={"resource": {"ticket_id": ticket_id, "project_id": str(project_id)}},
        )

        # Record the creation on the activity timeline.
        if ticket_id:
            await self.activity.log_activity(
                ticket_id=UUID(str(ticket_id)),
                actor_id=user_id,
                action_type="created",
                new_value={
                    "title": created.get("title"),
                    "type": created.get("type"),
                    "priority": created.get("priority"),
                    "status": created.get("status"),
                },
            )
            await audit_logger.log(
                actor_id=user_id,
                action=AuditEvents.TICKET_CREATED,
                resource_type=ResourceTypes.TICKET,
                resource_id=UUID(str(ticket_id)),
                project_id=project_id,
                metadata={
                    "title": created.get("title"),
                    "type": created.get("type"),
                    "priority": created.get("priority"),
                },
                ip_address=ip_address,
            )

        # The "new ticket" broadcast is deferred to approval. If the ticket was
        # created already assigned to someone else, notify that assignee now;
        # that runs in the background so the create request returns immediately.
        if ticket_id and background_tasks is not None:
            tid = UUID(str(ticket_id))
            if data.assigned_to is not None and str(data.assigned_to) != str(user_id):
                background_tasks.add_task(
                    self.notifications.notify_ticket_assigned,
                    tid,
                    data.assigned_to,
                    user_id,
                )

        # Re-fetch with related user data for a complete response.
        if ticket_id:
            full = await self.repo.get_with_relations(UUID(str(ticket_id)))
            if full:
                return full
        return created

    async def get_by_id(
        self, ticket_id: UUID, project_id: UUID, viewer: Optional[dict] = None
    ) -> dict:
        """Get a single ticket by ID, scoped to the current project.

        Args:
            ticket_id: UUID of the ticket.
            project_id: UUID of the current project (from context).
            viewer: Optional acting user (``id`` and ``role``). When provided,
                a ``pending_approval`` ticket is hidden (raised as not-found)
                from anyone who is neither an admin nor the ticket's creator.

        Returns:
            The ticket record with related user data.

        Raises:
            TicketNotFoundError: If the ticket does not exist, belongs to
                another project, or is a pending ticket hidden from ``viewer``.
        """
        ticket = await self.repo.get_with_relations(ticket_id)
        if not ticket or str(ticket.get("project_id")) != str(project_id):
            raise TicketNotFoundError(ticket_id=str(ticket_id))
        if viewer is not None:
            is_admin = viewer.get("role") == "admin"
            is_creator = str(ticket.get("created_by")) == str(viewer.get("id"))
            if (
                ticket.get("approval_status") == "pending_approval"
                and not is_admin
                and not is_creator
            ):
                raise TicketNotFoundError(ticket_id=str(ticket_id))
        return ticket

    async def add_comment(
        self,
        ticket_id: UUID,
        comment: str,
        user_id: UUID,
        project_id: UUID,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> dict:
        """Add a comment to a ticket and notify stakeholders + mentioned users.

        Verifies the ticket belongs to the current project, records a
        ``commented`` activity attributed to the caller, then (in the
        background) emails the creator, assignee, and anyone @mentioned in the
        comment body. Email sending runs on ``background_tasks`` so the
        response is not delayed by SES.

        Args:
            ticket_id: The ticket being commented on.
            comment: The comment text (validated by the schema layer).
            user_id: UUID of the authenticated commenter (the actor).
            project_id: UUID of the current project (from context).
            background_tasks: Optional queue for the notification email.

        Returns:
            The created activity record.

        Raises:
            TicketNotFoundError: If the ticket is missing or in another project.
        """
        # Raises TicketNotFoundError if the ticket is missing or cross-project.
        # Pass a conservative viewer so a non-creator cannot comment on a
        # hidden pending ticket. The endpoint supplies only ``user_id`` (no
        # role), so we assume a non-admin viewer here. See the service note on
        # the admin-commenting limitation this introduces.
        await self.get_by_id(
            ticket_id,
            project_id=project_id,
            viewer={"id": str(user_id), "role": "user"},
        )

        activity = await self.activity.add_comment(
            ticket_id=ticket_id, actor_id=user_id, comment=comment
        )

        if background_tasks is not None:
            background_tasks.add_task(
                self.notifications.notify_comment_added,
                ticket_id,
                user_id,
                comment,
            )

        return activity

    async def list_by_project(
        self,
        project_id: UUID,
        viewer: dict,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        ticket_type: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[UUID] = None,
        created_by: Optional[UUID] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[dict], int]:
        """List tickets for a project with filters, pagination, and sorting.

        Args:
            project_id: UUID of the current project.
            viewer: Acting user (``id`` and ``role``). Non-admins only see
                approved tickets plus their own; admins see every ticket.
            page: Page number (1-indexed).
            page_size: Items per page (capped at 100).
            status: Optional status filter.
            ticket_type: Optional type filter.
            priority: Optional priority filter.
            assigned_to: Optional assignee filter.
            created_by: Optional creator filter.
            date_from: Optional ISO datetime lower bound on created_at.
            date_to: Optional ISO datetime upper bound on created_at.
            sort_by: Sort column (whitelisted).
            sort_order: 'asc' or 'desc'.

        Returns:
            Tuple of (tickets list, total count).
        """
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)

        # Whitelist sort columns to avoid arbitrary column ordering.
        allowed_sort = {"created_at", "updated_at", "priority", "status", "title"}
        if sort_by not in allowed_sort:
            sort_by = "created_at"

        # Admins see everything; everyone else is scoped to approved tickets
        # plus the ones they created (the repo enforces this via viewer_id).
        is_admin = viewer.get("role") == "admin"
        viewer_id = None if is_admin else viewer.get("id")

        return await self.repo.list_by_project(
            project_id=project_id,
            page=page,
            page_size=page_size,
            status=status,
            ticket_type=ticket_type,
            priority=priority,
            assigned_to=assigned_to,
            created_by=created_by,
            date_from=date_from,
            date_to=date_to,
            order_by=sort_by,
            order_desc=sort_order.lower() != "asc",
            viewer_id=UUID(str(viewer_id)) if viewer_id else None,
            include_all_approval=is_admin,
        )

    async def update(
        self,
        ticket_id: UUID,
        data: TicketUpdate,
        user: dict,
        project_id: UUID,
        background_tasks: Optional[BackgroundTasks] = None,
        ip_address: Optional[str] = None,
    ) -> dict:
        """Update a ticket (partial), scoped to the current project.

        Only admins may change the assignee (assign to another admin or a
        user). Non-admins attempting to set ``assigned_to`` are rejected.

        Args:
            ticket_id: UUID of the ticket to update.
            data: Validated partial update payload.
            user: The acting user record (needs ``id`` and ``role``).
            project_id: UUID of the current project.
            background_tasks: Optional FastAPI background-task queue. When
                provided, email notifications for status/assignment/completion
                changes are scheduled on it (non-blocking, best-effort).

        Returns:
            The updated ticket with related user data.

        Raises:
            TicketNotFoundError: If the ticket does not exist or belongs to
                another project.
            ForbiddenError: If a non-admin attempts to change the assignee.
        """
        user_id = user["id"]
        is_admin = user.get("role") == "admin"

        existing = await self.repo.get_by_id(ticket_id)
        if not existing or str(existing.get("project_id")) != str(project_id):
            raise TicketNotFoundError(ticket_id=str(ticket_id))

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_by_id(ticket_id, project_id)

        # Assignment is admin-only. Reject non-admins that attempt to change
        # the assignee (an explicit null to unassign also counts as a change).
        assignment_changed = "assigned_to" in update_data and str(
            existing.get("assigned_to")
        ) != str(update_data["assigned_to"])
        if assignment_changed and not is_admin:
            raise ForbiddenError(
                message="Only an admin can assign or reassign a ticket."
            )

        # Serialize enum values to their string form.
        if data.type is not None:
            update_data["type"] = data.type.value
        if data.priority is not None:
            update_data["priority"] = data.priority.value
        if data.status is not None:
            update_data["status"] = data.status.value
        if "assigned_to" in update_data and data.assigned_to is not None:
            update_data["assigned_to"] = str(data.assigned_to)

        # BaseRepository.update strips None, so an unassign (assigned_to=None)
        # would be silently dropped. Persist it explicitly when needed.
        unassigning = "assigned_to" in update_data and update_data["assigned_to"] is None
        persisted = {k: v for k, v in update_data.items() if v is not None}
        if persisted:
            await self.repo.update(ticket_id, persisted)
        if unassigning:
            await self.repo.set_unassigned(ticket_id)

        logger.info(
            "ticket_updated",
            extra={
                "resource": {"ticket_id": str(ticket_id), "project_id": str(project_id)}
            },
        )

        await self._log_update_activities(
            ticket_id=ticket_id,
            actor_id=user_id,
            existing=existing,
            update_data=update_data,
            background_tasks=background_tasks,
        )

        # Audit the mutation. A status transition is recorded as a dedicated
        # status-change event; otherwise it is a generic update event. The
        # changed fields (old→new) are captured in the audit metadata.
        changed_fields = {
            field: {"old": existing.get(field), "new": value}
            for field, value in update_data.items()
            if existing.get(field) != value
        }
        status_changed = "status" in update_data and existing.get(
            "status"
        ) != update_data.get("status")
        await audit_logger.log(
            actor_id=user_id,
            action=(
                AuditEvents.TICKET_STATUS_CHANGED
                if status_changed
                else AuditEvents.TICKET_UPDATED
            ),
            resource_type=ResourceTypes.TICKET,
            resource_id=ticket_id,
            project_id=project_id,
            metadata={"changes": changed_fields},
            ip_address=ip_address,
        )

        return await self.get_by_id(ticket_id, project_id)

    async def _resolve_user_name(self, user_id: Optional[Any]) -> Optional[str]:
        """Resolve a user id to their display name (None if unset/not found)."""
        if not user_id:
            return None
        try:
            user = await self.user_repo.get_by_id(UUID(str(user_id)))
        except (ValueError, TypeError):
            return None
        return user.get("name") if user else None

    async def _log_update_activities(
        self,
        ticket_id: UUID,
        actor_id: UUID,
        existing: dict,
        update_data: dict[str, Any],
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> None:
        """Emit timeline activities for a ticket update.

        A single update can change several fields. Status and assignment
        changes are recorded as dedicated ``status_changed`` / ``assigned``
        activities (so the timeline can render them distinctly); any remaining
        changed fields are grouped into one ``updated`` activity.

        When ``background_tasks`` is provided, the same status/assignment
        changes also schedule email notifications (best-effort, non-blocking).

        Args:
            ticket_id: The updated ticket.
            actor_id: The acting user.
            existing: The ticket record prior to the update.
            update_data: The persisted update payload (serialized values).
            background_tasks: Optional queue for scheduling notification emails.
        """
        # Status change → dedicated activity with old→new status.
        if "status" in update_data:
            old_status = existing.get("status")
            new_status = update_data["status"]
            if old_status != new_status:
                await self.activity.log_activity(
                    ticket_id=ticket_id,
                    actor_id=actor_id,
                    action_type="status_changed",
                    old_value={"status": old_status},
                    new_value={"status": new_status},
                )
                self._schedule_status_notification(
                    background_tasks, ticket_id, old_status, new_status, actor_id
                )

        # Assignment change → dedicated activity with old→new assignee,
        # storing human-readable names (resolved now) alongside the ids so the
        # timeline can render "assigned to Jane Smith" without a later lookup.
        if "assigned_to" in update_data:
            old_assignee = existing.get("assigned_to")
            new_assignee = update_data["assigned_to"]
            if str(old_assignee) != str(new_assignee):
                await self.activity.log_activity(
                    ticket_id=ticket_id,
                    actor_id=actor_id,
                    action_type="assigned",
                    old_value={
                        "assigned_to": old_assignee,
                        "assigned_to_name": await self._resolve_user_name(old_assignee),
                    },
                    new_value={
                        "assigned_to": new_assignee,
                        "assigned_to_name": await self._resolve_user_name(new_assignee),
                    },
                )
                # Notify only when a ticket gains an assignee (not on unassign).
                if new_assignee and background_tasks is not None:
                    background_tasks.add_task(
                        self.notifications.notify_ticket_assigned,
                        ticket_id,
                        UUID(str(new_assignee)),
                        actor_id,
                    )
                # Keep the owner in the loop on any assignee change (assign,
                # reassign, or unassign), showing readable names. Best-effort.
                if background_tasks is not None:
                    background_tasks.add_task(
                        self.notifications.notify_owner_assignee_changed,
                        ticket_id,
                        await self._resolve_user_name(old_assignee),
                        await self._resolve_user_name(new_assignee),
                        actor_id,
                    )

        # Any other changed fields → a single grouped "updated" activity.
        # ``tags`` is included here so that, once the tickets table/schema
        # gains a tags column, tag edits automatically notify the owner too.
        tracked_separately = {"status", "assigned_to"}
        other_old: dict[str, Any] = {}
        other_new: dict[str, Any] = {}
        for field, new_val in update_data.items():
            if field in tracked_separately:
                continue
            old_val = existing.get(field)
            if old_val != new_val:
                other_old[field] = old_val
                other_new[field] = new_val

        if other_new:
            await self.activity.log_activity(
                ticket_id=ticket_id,
                actor_id=actor_id,
                action_type="updated",
                old_value=other_old,
                new_value=other_new,
            )
            # Keep the owner informed of every other field change (title,
            # description, type, priority, tags, ...), even when they made it.
            if background_tasks is not None:
                changes = {
                    field: {"old": other_old[field], "new": other_new[field]}
                    for field in other_new
                }
                background_tasks.add_task(
                    self.notifications.notify_ticket_updated,
                    ticket_id,
                    changes,
                    actor_id,
                )

    def _schedule_status_notification(
        self,
        background_tasks: Optional[BackgroundTasks],
        ticket_id: UUID,
        old_status: Optional[str],
        new_status: str,
        actor_id: UUID,
    ) -> None:
        """Queue the right email for a status change (no-op without a queue).

        A move to ``completed`` uses the dedicated completion email; every
        other transition uses the generic status-changed email. Both are
        attributed to ``actor_id`` and run in the background so the request
        returns immediately.
        """
        if background_tasks is None:
            return

        if new_status == "completed":
            background_tasks.add_task(
                self.notifications.notify_ticket_completed, ticket_id, actor_id
            )
        else:
            background_tasks.add_task(
                self.notifications.notify_status_changed,
                ticket_id,
                old_status or "",
                new_status,
                actor_id,
            )

    async def delete(
        self,
        ticket_id: UUID,
        user: dict,
        project_id: UUID,
        ip_address: Optional[str] = None,
    ) -> None:
        """Delete a ticket, scoped to the current project.

        Only the creator or an admin may delete a ticket.

        Args:
            ticket_id: UUID of the ticket to delete.
            user: The acting user record.
            project_id: UUID of the current project.

        Raises:
            TicketNotFoundError: If the ticket does not exist or belongs to
                another project.
            ForbiddenError: If the user is neither the creator nor an admin.
        """
        existing = await self.repo.get_by_id(ticket_id)
        if not existing or str(existing.get("project_id")) != str(project_id):
            raise TicketNotFoundError(ticket_id=str(ticket_id))

        is_admin = user.get("role") == "admin"
        is_creator = str(existing.get("created_by")) == str(user.get("id"))
        if not (is_admin or is_creator):
            raise ForbiddenError(
                message="Only the ticket creator or an admin can delete this ticket."
            )

        await self.repo.delete(ticket_id)
        logger.info(
            "ticket_deleted",
            extra={
                "resource": {"ticket_id": str(ticket_id), "project_id": str(project_id)}
            },
        )
        await audit_logger.log(
            actor_id=UUID(str(user.get("id"))),
            action=AuditEvents.TICKET_DELETED,
            resource_type=ResourceTypes.TICKET,
            resource_id=ticket_id,
            project_id=project_id,
            metadata={"title": existing.get("title")},
            ip_address=ip_address,
        )

    async def list_pending(
        self, project_id: UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        """List tickets awaiting approval in the given project (admin view).

        Args:
            project_id: UUID of the current project.
            page: Page number (1-indexed).
            page_size: Items per page (capped at 100).

        Returns:
            Tuple of (pending tickets, total count).
        """
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        return await self.repo.list_pending(
            project_id=project_id, page=page, page_size=page_size
        )

    async def approve(
        self,
        ticket_id: UUID,
        user: dict,
        project_id: UUID,
        background_tasks: Optional[BackgroundTasks] = None,
        ip_address: Optional[str] = None,
    ) -> dict:
        """Approve a pending ticket, then fire the deferred "new ticket" email.

        Approval is idempotent: re-approving an already-approved ticket is a
        no-op that simply returns the current record. On the first approval the
        ticket is marked approved (approver + timestamp recorded via the repo),
        an audit event is written, and the deferred "new ticket" broadcast —
        suppressed at creation — is scheduled on ``background_tasks``.

        Args:
            ticket_id: UUID of the ticket to approve.
            user: The acting admin (needs ``id``).
            project_id: UUID of the current project.
            background_tasks: Optional queue for the deferred notifications.
            ip_address: Optional client IP for the audit record.

        Returns:
            The approved ticket with related user data.

        Raises:
            TicketNotFoundError: If the ticket is missing or in another project.
        """
        existing = await self.repo.get_by_id(ticket_id)
        if not existing or str(existing.get("project_id")) != str(project_id):
            raise TicketNotFoundError(ticket_id=str(ticket_id))
        if existing.get("approval_status") == "approved":
            return await self.get_by_id(ticket_id, project_id)
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

    async def reject(
        self,
        ticket_id: UUID,
        user: dict,
        project_id: UUID,
        ip_address: Optional[str] = None,
    ) -> None:
        """Reject a pending ticket: audit it, then hard-delete it.

        The rejection audit entry is written BEFORE the delete so the record of
        who rejected what (and the original creator) survives the deletion. An
        already-approved ticket cannot be rejected.

        Args:
            ticket_id: UUID of the ticket to reject.
            user: The acting admin (needs ``id``).
            project_id: UUID of the current project.
            ip_address: Optional client IP for the audit record.

        Raises:
            TicketNotFoundError: If the ticket is missing or in another project.
            TicketAlreadyApprovedError: If the ticket is already approved.
        """
        existing = await self.repo.get_by_id(ticket_id)
        if not existing or str(existing.get("project_id")) != str(project_id):
            raise TicketNotFoundError(ticket_id=str(ticket_id))
        if existing.get("approval_status") == "approved":
            raise TicketAlreadyApprovedError(ticket_id=str(ticket_id))
        await audit_logger.log(
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
