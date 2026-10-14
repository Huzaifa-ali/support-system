# Support System - API Specification

## Base URL

```
Development: http://localhost:8000/api/v1
Production:  https://api.yourdomain.com/api/v1
```

## Authentication

All protected endpoints require a Bearer token in the Authorization header:

```
Authorization: Bearer <cognito_access_token>
```

## Common Response Format

### Success Response

```json
{
  "data": { ... },
  "message": "Success"
}
```

### List Response (Paginated)

```json
{
  "data": [ ... ],
  "pagination": {
    "total": 150,
    "page": 1,
    "page_size": 20,
    "total_pages": 8
  }
}
```

### Error Response

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Title is required",
  "details": {
    "field": "title",
    "constraint": "min_length:5"
  }
}
```

### HTTP Status Codes

| Code | Usage |
|------|-------|
| 200 | Successful GET, PUT, PATCH, DELETE |
| 201 | Successful POST (resource created) |
| 204 | Successful DELETE (no content) |
| 400 | Validation error, bad request |
| 401 | Missing or invalid auth token |
| 403 | Insufficient permissions |
| 404 | Resource not found |
| 409 | Conflict (duplicate resource, or `TICKET_ALREADY_APPROVED` on reject) |
| 422 | Unprocessable entity |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

---

## Endpoints

### Health Check

#### `GET /health`

**Auth:** None

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2024-01-15T10:00:00Z"
}
```

---

### Authentication

#### `POST /api/v1/auth/me`

Get current user profile (creates user in DB on first call).

**Auth:** Required

**Response:**
```json
{
  "data": {
    "id": "uuid",
    "cognito_sub": "cognito-sub-id",
    "email": "user@example.com",
    "name": "John Doe",
    "role": "user",
    "email_notifications": true,
    "saved_filters": [],
    "created_at": "2024-01-15T10:00:00Z"
  }
}
```

#### `PATCH /api/v1/auth/me`

Update current user profile.

**Auth:** Required

**Request Body:**
```json
{
  "name": "John Updated",
  "email_notifications": false
}
```

**Response:** Updated user object.

---

### Projects

#### `GET /api/v1/projects`

List all projects (users see assigned projects, admins see all).

**Auth:** Required

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | Page number |
| page_size | int | 20 | Items per page |
| is_public | bool | - | Filter by public status |

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Project Alpha",
      "description": "Main product support",
      "jira_project_key": "ALPHA",
      "discord_webhook_url": "https://discord.com/api/webhooks/...",
      "is_public": true,
      "email_enabled": true,
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-15T10:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

#### `POST /api/v1/projects`

Create a new project.

**Auth:** Required (Admin only)

**Request Body:**
```json
{
  "name": "Project Beta",
  "description": "New product support channel",
  "jira_project_key": "BETA",
  "discord_webhook_url": "https://discord.com/api/webhooks/...",
  "is_public": true,
  "email_enabled": true
}
```

**Response:** `201 Created` with project object.

#### `GET /api/v1/projects/{project_id}`

Get project by ID.

**Auth:** Required

**Response:** Single project object.

#### `PUT /api/v1/projects/{project_id}`

Update a project.

**Auth:** Required (Admin only)

**Request Body:** Same as create (all fields optional).

**Response:** Updated project object.

#### `DELETE /api/v1/projects/{project_id}`

Delete a project (cascades to tickets).

**Auth:** Required (Admin only)

**Response:** `204 No Content`

---

### Tickets

#### `GET /api/v1/tickets`

List tickets for current project.

**Auth:** Required

**Headers:**
```
X-Project-ID: uuid
```

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | Page number |
| page_size | int | 20 | Items per page (max 100) |
| status | string | - | Filter: pending, in_progress, paused, in_review, completed |
| type | string | - | Filter: technical_error, bug, feature, remove |
| priority | string | - | Filter: critical, high, medium, low |
| assigned_to | uuid | - | Filter by assignee |
| created_by | uuid | - | Filter by creator |
| date_from | datetime | - | Created after this date |
| date_to | datetime | - | Created before this date |
| sort_by | string | created_at | Sort field: created_at, updated_at, priority, status |
| sort_order | string | desc | asc or desc |

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "title": "Login page not loading",
      "description": "The login page shows a blank screen on Chrome...",
      "type": "bug",
      "priority": "high",
      "status": "in_progress",
      "approval_status": "approved",
      "approved_by": "uuid",
      "approved_at": "2024-01-15T10:02:00Z",
      "jira_key": "ALPHA-123",
      "created_by": {
        "id": "uuid",
        "name": "John Doe",
        "email": "john@example.com"
      },
      "assigned_to": {
        "id": "uuid",
        "name": "Jane Smith",
        "email": "jane@example.com"
      },
      "attachments_count": 2,
      "activities_count": 5,
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-16T14:30:00Z"
    }
  ],
  "pagination": { ... }
}
```

#### `POST /api/v1/tickets`

Create a new ticket.

**Auth:** Required

**Headers:**
```
X-Project-ID: uuid
```

**Request Body:**
```json
{
  "title": "Login page not loading",
  "description": "The login page shows a blank screen on Chrome v120...",
  "type": "bug",
  "priority": "high",
  "assigned_to": "uuid (optional)"
}
```

**Validation:**
- `title`: required, min 5 chars, max 200 chars
- `description`: required, min 10 chars
- `type`: required, one of enum values
- `priority`: required, one of enum values

**Response:** `201 Created` with ticket object.

A newly created ticket is set to `approval_status: "pending_approval"` and is
visible only to its creator and to admins until an admin approves it (see the
approval endpoints below). The "new ticket" notification is **deferred** and
sent when the ticket is approved, not on creation.

**Side Effects (Background):**
- Creates activity log (ticket.created)
- Creates audit log
- Creates Jira issue (if project configured)
- Sends Discord notification (if project configured)
- Sends confirmation email to creator (if enabled)

#### `GET /api/v1/tickets/{ticket_id}`

Get ticket by ID with full details.

**Auth:** Required

**Response:**
```json
{
  "data": {
    "id": "uuid",
    "project_id": "uuid",
    "title": "Login page not loading",
    "description": "The login page shows a blank screen...",
    "type": "bug",
    "priority": "high",
    "status": "in_progress",
    "approval_status": "approved",
    "approved_by": "uuid",
    "approved_at": "2024-01-15T10:02:00Z",
    "jira_key": "ALPHA-123",
    "created_by": { "id": "uuid", "name": "John Doe", "email": "..." },
    "assigned_to": { "id": "uuid", "name": "Jane Smith", "email": "..." },
    "attachments": [
      {
        "id": "uuid",
        "file_name": "screenshot.png",
        "s3_key": "project-id/ticket-id/uuid/screenshot.png",
        "content_type": "image/png",
        "file_size": 245000,
        "download_url": "https://s3.presigned.url...",
        "uploaded_at": "2024-01-15T10:05:00Z"
      }
    ],
    "recent_activities": [
      {
        "id": "uuid",
        "action_type": "status_changed",
        "actor": { "id": "uuid", "name": "Jane Smith" },
        "old_value": { "status": "pending" },
        "new_value": { "status": "in_progress" },
        "created_at": "2024-01-16T14:30:00Z"
      }
    ],
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-01-16T14:30:00Z"
  }
}
```

#### `PATCH /api/v1/tickets/{ticket_id}`

Update a ticket (partial update).

**Auth:** Required

**Request Body:**
```json
{
  "title": "Updated title (optional)",
  "description": "Updated description (optional)",
  "type": "technical_error (optional)",
  "priority": "critical (optional)",
  "status": "in_review (optional)",
  "assigned_to": "uuid (optional, null to unassign)"
}
```

**Response:** Updated ticket object.

**Side Effects (Background):**
- Creates activity log (status_changed / updated / assigned)
- Creates audit log
- Transitions Jira issue (if status changed)
- Sends Discord notification (if status changed)
- Sends email to creator (if status changed)

#### `DELETE /api/v1/tickets/{ticket_id}`

Delete a ticket (cascades to attachments and activities).

**Auth:** Required (creator or admin)

**Response:** `204 No Content`

**Side Effects:**
- Deletes S3 files
- Creates audit log (ticket.deleted)

#### `GET /api/v1/tickets/pending-approval`

List tickets awaiting approval in the current project.

**Auth:** Required (Admin only)

**Headers:**
```
X-Project-ID: uuid
```

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | Page number |
| page_size | int | 20 | Items per page |

**Response:** Paginated list of ticket objects (same shape as `GET /api/v1/tickets`),
scoped to tickets with `approval_status: "pending_approval"`.
```json
{
  "data": [ { "id": "uuid", "approval_status": "pending_approval", ... } ],
  "pagination": { ... }
}
```

**Status Codes:**
- `200 OK` — list returned
- `403 Forbidden` — caller is not an admin

#### `POST /api/v1/tickets/{ticket_id}/approve`

Approve a pending ticket. Makes it visible to everyone who can see the project
and sends the deferred "new ticket" notification.

**Auth:** Required (Admin only)

**Headers:**
```
X-Project-ID: uuid
```

**Response:** `200 OK`
```json
{
  "data": { "id": "uuid", "approval_status": "approved", "approved_by": "uuid", "approved_at": "2024-01-15T10:02:00Z", ... },
  "message": "Ticket approved"
}
```

Idempotent: approving an already-approved ticket returns `200` with the ticket
unchanged.

**Status Codes:**
- `200 OK` — ticket approved (or already approved)
- `403 Forbidden` — caller is not an admin
- `404 Not Found` — ticket does not exist or belongs to another project

**Side Effects (Background):**
- Sets `approved_by` / `approved_at`
- Creates audit log (ticket.approved)
- Sends the deferred "new ticket" notification (Discord / email, if configured)

#### `POST /api/v1/tickets/{ticket_id}/reject`

Reject a pending ticket. The ticket is **permanently hard-deleted**. A
`ticket.rejected` audit entry (capturing the title and `created_by`) is written
before deletion.

**Auth:** Required (Admin only)

**Headers:**
```
X-Project-ID: uuid
```

**Response:** `204 No Content`

**Status Codes:**
- `204 No Content` — ticket rejected and deleted
- `403 Forbidden` — caller is not an admin
- `404 Not Found` — ticket does not exist or belongs to another project
- `409 Conflict` — ticket is already approved (`TICKET_ALREADY_APPROVED`)

**Side Effects:**
- Creates audit log (ticket.rejected) **before** deletion
- Permanently deletes the ticket (cascades to attachments and activities)

---

### File Uploads

#### `POST /api/v1/uploads/presigned-url`

Generate a presigned S3 upload URL.

**Auth:** Required

**Request Body:**
```json
{
  "ticket_id": "uuid",
  "file_name": "screenshot.png",
  "content_type": "image/png",
  "file_size": 245000
}
```

**Validation:**
- `content_type`: must be image/jpeg, image/png, image/gif, image/webp, video/mp4, video/webm
- `file_size`: max 52428800 (50MB)

**Response:**
```json
{
  "data": {
    "upload_url": "https://s3.amazonaws.com/bucket/...?X-Amz-Signature=...",
    "s3_key": "project-id/ticket-id/uuid/screenshot.png",
    "expires_in": 900
  }
}
```

#### `POST /api/v1/uploads/confirm`

Confirm upload completion (creates attachment record).

**Auth:** Required

**Request Body:**
```json
{
  "ticket_id": "uuid",
  "s3_key": "project-id/ticket-id/uuid/screenshot.png",
  "file_name": "screenshot.png",
  "content_type": "image/png",
  "file_size": 245000
}
```

**Response:** `201 Created` with attachment object.

**Side Effects:**
- Creates activity log (file_uploaded)

#### `GET /api/v1/uploads/{ticket_id}`

List all attachments for a ticket.

**Auth:** Required

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "file_name": "screenshot.png",
      "s3_key": "...",
      "content_type": "image/png",
      "file_size": 245000,
      "download_url": "https://s3.presigned.download.url...",
      "uploaded_by": { "id": "uuid", "name": "John" },
      "uploaded_at": "2024-01-15T10:05:00Z"
    }
  ]
}
```

#### `DELETE /api/v1/uploads/{attachment_id}`

Delete an attachment.

**Auth:** Required (uploader or admin)

**Response:** `204 No Content`

**Side Effects:**
- Deletes from S3
- Creates activity log (file_deleted)

---

### Activities / Timeline

#### `GET /api/v1/tickets/{ticket_id}/activities`

Get activity timeline for a ticket.

**Auth:** Required

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | Page number |
| page_size | int | 50 | Items per page |

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "ticket_id": "uuid",
      "action_type": "created",
      "actor": { "id": "uuid", "name": "John Doe", "email": "..." },
      "old_value": null,
      "new_value": { "title": "Login page not loading", "status": "pending" },
      "comment": null,
      "created_at": "2024-01-15T10:00:00Z"
    },
    {
      "id": "uuid",
      "ticket_id": "uuid",
      "action_type": "commented",
      "actor": { "id": "uuid", "name": "Jane Smith", "email": "..." },
      "old_value": null,
      "new_value": null,
      "comment": "I can reproduce this on Chrome 120. Looking into it.",
      "created_at": "2024-01-15T11:00:00Z"
    },
    {
      "id": "uuid",
      "ticket_id": "uuid",
      "action_type": "status_changed",
      "actor": { "id": "uuid", "name": "Jane Smith", "email": "..." },
      "old_value": { "status": "pending" },
      "new_value": { "status": "in_progress" },
      "comment": null,
      "created_at": "2024-01-15T11:05:00Z"
    }
  ],
  "pagination": { ... }
}
```

#### `POST /api/v1/tickets/{ticket_id}/comments`

Add a comment to a ticket.

**Auth:** Required

**Request Body:**
```json
{
  "comment": "I can reproduce this on Chrome 120. Looking into it."
}
```

**Validation:**
- `comment`: required, min 1 char, max 5000 chars

**Response:** `201 Created` with activity object.

---

### Search

#### `GET /api/v1/search`

Full-text search across tickets.

**Auth:** Required

**Headers:**
```
X-Project-ID: uuid
```

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| q | string | - | Search query (required, min 2 chars) |
| status | string | - | Filter by status |
| type | string | - | Filter by type |
| priority | string | - | Filter by priority |
| page | int | 1 | Page number |
| page_size | int | 20 | Items per page |

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "Login page not loading",
      "description": "The login page shows a blank screen...",
      "type": "bug",
      "priority": "high",
      "status": "in_progress",
      "relevance_score": 0.95,
      "highlight": {
        "title": "<mark>Login</mark> page not <mark>loading</mark>",
        "description": "The <mark>login</mark> page shows a blank..."
      },
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

#### `GET /api/v1/search/filters`

Get saved filters for current user.

**Auth:** Required

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Critical Bugs",
      "filters": {
        "type": "bug",
        "priority": "critical",
        "status": "pending"
      },
      "created_at": "2024-01-15T10:00:00Z"
    }
  ]
}
```

#### `POST /api/v1/search/filters`

Save a filter combination.

**Auth:** Required

**Request Body:**
```json
{
  "name": "Critical Bugs",
  "filters": {
    "type": "bug",
    "priority": "critical",
    "status": "pending"
  }
}
```

**Response:** `201 Created` with saved filter object.

#### `DELETE /api/v1/search/filters/{filter_id}`

Delete a saved filter.

**Auth:** Required

**Response:** `204 No Content`

---

### Bulk Operations

#### `POST /api/v1/tickets/bulk/status`

Change status of multiple tickets.

**Auth:** Required

**Request Body:**
```json
{
  "ticket_ids": ["uuid1", "uuid2", "uuid3"],
  "status": "in_progress"
}
```

**Validation:**
- `ticket_ids`: required, min 1, max 100
- `status`: required, valid enum value

**Response:**
```json
{
  "data": {
    "success_count": 3,
    "failure_count": 0,
    "failures": []
  }
}
```

**Side Effects:**
- Creates activity log per ticket
- Triggers Jira transitions per ticket
- Sends Discord notifications
- Sends emails to creators

#### `POST /api/v1/tickets/bulk/assign`

Assign multiple tickets to a user.

**Auth:** Required

**Request Body:**
```json
{
  "ticket_ids": ["uuid1", "uuid2"],
  "assigned_to": "uuid"
}
```

**Response:** Same format as bulk status.

#### `POST /api/v1/tickets/bulk/delete`

Delete multiple tickets.

**Auth:** Required (Admin only)

**Request Body:**
```json
{
  "ticket_ids": ["uuid1", "uuid2"]
}
```

**Response:**
```json
{
  "data": {
    "success_count": 2,
    "failure_count": 0,
    "failures": []
  }
}
```

---

### Dashboard (Public)

#### `GET /api/v1/dashboard/public`

Get public KPI metrics.

**Auth:** None (public endpoint)

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| project_id | uuid | - | Filter by project (only public projects) |
| date_from | date | 30 days ago | Start date |
| date_to | date | today | End date |

**Response:**
```json
{
  "data": {
    "summary": {
      "total_tickets": 150,
      "pending": 20,
      "in_progress": 35,
      "paused": 8,
      "in_review": 12,
      "completed": 75,
      "avg_resolution_hours": 48.5
    },
    "by_type": [
      { "type": "bug", "count": 60 },
      { "type": "feature", "count": 45 },
      { "type": "technical_error", "count": 30 },
      { "type": "remove", "count": 15 }
    ],
    "by_priority": [
      { "priority": "critical", "count": 10 },
      { "priority": "high", "count": 40 },
      { "priority": "medium", "count": 65 },
      { "priority": "low", "count": 35 }
    ],
    "over_time": [
      { "date": "2024-01-08", "created": 5, "completed": 3 },
      { "date": "2024-01-09", "created": 8, "completed": 6 },
      { "date": "2024-01-10", "created": 3, "completed": 4 }
    ],
    "by_project": [
      { "project_id": "uuid", "project_name": "Alpha", "total": 80, "completed": 45 },
      { "project_id": "uuid", "project_name": "Beta", "total": 70, "completed": 30 }
    ]
  }
}
```

**Rate Limit:** 60 requests/minute per IP

#### `GET /api/v1/dashboard/insights`

Get detailed analytics (protected).

**Auth:** Required

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| project_id | uuid | - | Filter by project |
| date_from | date | 30 days ago | Start date |
| date_to | date | today | End date |

**Response:**
```json
{
  "data": {
    "velocity": {
      "current_period": { "created": 45, "completed": 38 },
      "previous_period": { "created": 40, "completed": 35 },
      "trend": { "created_change": 12.5, "completed_change": 8.6 }
    },
    "avg_time_per_status": {
      "pending": 4.2,
      "in_progress": 18.5,
      "paused": 12.0,
      "in_review": 6.8
    },
    "team_workload": [
      {
        "user_id": "uuid",
        "name": "Jane Smith",
        "assigned": 12,
        "completed": 8,
        "completion_rate": 66.7
      }
    ],
    "busiest_days": [
      { "day": "Monday", "avg_created": 8.5 },
      { "day": "Tuesday", "avg_created": 7.2 }
    ],
    "top_types": [
      { "type": "bug", "count": 25, "percentage": 55.6 }
    ]
  }
}
```

---

### Audit Logs (Admin)

#### `GET /api/v1/audit-logs`

Get audit log entries.

**Auth:** Required (Admin only)

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | Page number |
| page_size | int | 50 | Items per page |
| actor_id | uuid | - | Filter by user |
| action | string | - | Filter by action type (e.g. `ticket.created`, `ticket.approved`, `ticket.rejected`) |
| resource_type | string | - | Filter: ticket, project, user |
| project_id | uuid | - | Filter by project |
| date_from | datetime | - | Start date |
| date_to | datetime | - | End date |

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "actor": { "id": "uuid", "name": "John Doe", "email": "..." },
      "action": "ticket.status_changed",
      "resource_type": "ticket",
      "resource_id": "uuid",
      "project_id": "uuid",
      "metadata": {
        "old_status": "pending",
        "new_status": "in_progress",
        "ticket_title": "Login page not loading"
      },
      "ip_address": "192.168.1.1",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### Users (Admin)

> **Authentication model: Admin-only user creation.**
> Public self-signup is disabled in Cognito (`AllowAdminCreateUserOnly = true`).
> Only admins create users through these endpoints. The very first admin is
> created out-of-band via the `bootstrap_admin.py` script.

#### `GET /api/v1/admin/users`

List all users.

**Auth:** Required (Admin only)

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | Page number |
| page_size | int | 20 | Items per page |

**Response:**
```json
{
  "data": [
    {
      "id": "uuid",
      "cognito_sub": "cognito-sub",
      "email": "user@example.com",
      "name": "John Doe",
      "role": "user",
      "email_notifications": true,
      "saved_filters": [],
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-15T10:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

#### `POST /api/v1/admin/users`

Create a new user (admin or regular user). Creates the user in AWS Cognito
(which emails a temporary password) and inserts the matching DB record with
the assigned role.

**Auth:** Required (Admin only)

**Request Body:**
```json
{
  "email": "jane@example.com",
  "name": "Jane Doe",
  "role": "admin"
}
```

**Validation:**
- `email`: required, valid email
- `name`: required, 1-100 chars
- `role`: `admin` or `user` (default `user`)

**Response:** `201 Created`
```json
{
  "data": { "id": "uuid", "email": "jane@example.com", "role": "admin", ... },
  "message": "User created. An invite email was sent."
}
```

**Errors:** `409 Conflict` if a user with the email already exists.

**Side Effects:**
- Cognito `admin_create_user` sends an invite email with a temporary password
- On first login the new user is challenged to set a permanent password
  (`CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED`)

#### `PATCH /api/v1/admin/users/{user_id}/role`

Update a user's role.

**Auth:** Required (Admin only)

**Request Body:**
```json
{
  "role": "admin"
}
```

**Response:** Updated user object.

---

## Schemas Summary

### Enums

```python
class TicketStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"

class TicketApprovalStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"

class TicketType(str, Enum):
    TECHNICAL_ERROR = "technical_error"
    BUG = "bug"
    FEATURE = "feature"
    REMOVE = "remove"

class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"

class ActivityActionType(str, Enum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    UPDATED = "updated"
    COMMENTED = "commented"
    FILE_UPLOADED = "file_uploaded"
    FILE_DELETED = "file_deleted"
    ASSIGNED = "assigned"
```

### Request Schemas

```python
class TicketCreate(BaseModel):
    title: str  # min 5, max 200
    description: str  # min 10
    type: TicketType
    priority: Priority
    assigned_to: Optional[UUID] = None

class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[TicketType] = None
    priority: Optional[Priority] = None
    status: Optional[TicketStatus] = None
    assigned_to: Optional[UUID] = None

class ProjectCreate(BaseModel):
    name: str  # min 2, max 100
    description: Optional[str] = None
    jira_project_key: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    is_public: bool = False
    email_enabled: bool = True

class BulkStatusChange(BaseModel):
    ticket_ids: List[UUID]  # min 1, max 100
    status: TicketStatus

class BulkAssign(BaseModel):
    ticket_ids: List[UUID]  # min 1, max 100
    assigned_to: UUID

class BulkDelete(BaseModel):
    ticket_ids: List[UUID]  # min 1, max 100

class CommentCreate(BaseModel):
    comment: str  # min 1, max 5000

class PresignedUrlRequest(BaseModel):
    ticket_id: UUID
    file_name: str
    content_type: str
    file_size: int  # max 52428800

class SavedFilterCreate(BaseModel):
    name: str  # min 1, max 50
    filters: dict
```

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| `GET /api/v1/dashboard/public` | 60/min per IP |
| `POST /api/v1/tickets` | 30/min per user |
| `POST /api/v1/uploads/presigned-url` | 20/min per user |
| `POST /api/v1/tickets/bulk/*` | 10/min per user |
| All other authenticated endpoints | 120/min per user |

---

## Webhook Payloads (Outgoing)

### Discord Embed (Ticket Created)

```json
{
  "embeds": [
    {
      "title": "New Ticket: Login page not loading",
      "description": "The login page shows a blank screen on Chrome...",
      "color": 16744448,
      "fields": [
        { "name": "Type", "value": "Bug", "inline": true },
        { "name": "Priority", "value": "High", "inline": true },
        { "name": "Status", "value": "Pending", "inline": true },
        { "name": "Created By", "value": "John Doe", "inline": true },
        { "name": "Project", "value": "Alpha", "inline": true }
      ],
      "url": "https://app.yourdomain.com/tickets/uuid",
      "timestamp": "2024-01-15T10:00:00Z"
    }
  ]
}
```

### Discord Embed (Status Changed)

```json
{
  "embeds": [
    {
      "title": "Status Updated: Login page not loading",
      "description": "Pending → In Progress",
      "color": 16776960,
      "fields": [
        { "name": "Changed By", "value": "Jane Smith", "inline": true },
        { "name": "Project", "value": "Alpha", "inline": true }
      ],
      "url": "https://app.yourdomain.com/tickets/uuid",
      "timestamp": "2024-01-16T14:30:00Z"
    }
  ]
}
```
