"""Audit event constants."""


class AuditEvents:
    """Constants for audit event action types."""

    TICKET_CREATED = "ticket.created"
    TICKET_UPDATED = "ticket.updated"
    TICKET_DELETED = "ticket.deleted"
    TICKET_STATUS_CHANGED = "ticket.status_changed"
    TICKET_ASSIGNED = "ticket.assigned"
    TICKET_APPROVED = "ticket.approved"
    TICKET_REJECTED = "ticket.rejected"
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    FILE_UPLOADED = "file.uploaded"
    FILE_DELETED = "file.deleted"
    USER_LOGIN = "user.login"
    USER_UPDATED = "user.updated"
    BULK_STATUS_CHANGE = "bulk.status_changed"
    BULK_ASSIGN = "bulk.assigned"
    BULK_DELETE = "bulk.deleted"


class ResourceTypes:
    """Constants for audit resource types."""

    TICKET = "ticket"
    PROJECT = "project"
    USER = "user"
    ATTACHMENT = "attachment"
