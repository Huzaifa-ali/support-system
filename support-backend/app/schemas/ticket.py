"""Ticket request/response schemas with full validation."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """Ticket status enum."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"


class ApprovalStatus(str, Enum):
    """Approval gate status (orthogonal to the work-lifecycle status)."""

    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"


class TicketType(str, Enum):
    """Ticket type enum."""

    TECHNICAL_ERROR = "technical_error"
    BUG = "bug"
    FEATURE = "feature"
    REMOVE = "remove"


class Priority(str, Enum):
    """Priority level enum."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class UserSummary(BaseModel):
    """Minimal user info for embedded responses."""

    id: UUID
    name: str
    email: str


class TicketCreate(BaseModel):
    """Schema for creating a new ticket."""

    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    type: TicketType
    priority: Priority
    assigned_to: Optional[UUID] = None


class TicketUpdate(BaseModel):
    """Schema for updating a ticket (partial update)."""

    title: Optional[str] = Field(None, min_length=5, max_length=200)
    description: Optional[str] = Field(None, min_length=10)
    type: Optional[TicketType] = None
    priority: Optional[Priority] = None
    status: Optional[TicketStatus] = None
    assigned_to: Optional[UUID] = None


class TicketResponse(BaseModel):
    """Schema for ticket in API responses."""

    id: UUID
    project_id: UUID
    title: str
    description: str
    type: TicketType
    priority: Priority
    status: TicketStatus
    jira_key: Optional[str] = None
    created_by: Optional[UserSummary] = None
    assigned_to: Optional[UserSummary] = None
    attachments_count: int = 0
    activities_count: int = 0
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TicketListResponse(BaseModel):
    """Schema for ticket list item (lighter than full response)."""

    id: UUID
    project_id: UUID
    title: str
    type: TicketType
    priority: Priority
    status: TicketStatus
    jira_key: Optional[str] = None
    created_by: Optional[UserSummary] = None
    assigned_to: Optional[UserSummary] = None
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class BulkStatusChange(BaseModel):
    """Schema for bulk status change operation."""

    ticket_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    status: TicketStatus


class BulkAssign(BaseModel):
    """Schema for bulk assign operation."""

    ticket_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    assigned_to: UUID


class BulkDelete(BaseModel):
    """Schema for bulk delete operation."""

    ticket_ids: list[UUID] = Field(..., min_length=1, max_length=100)