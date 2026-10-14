# Requirements Document

## Introduction

This feature adds an **admin approval gate** to ticket creation. Today any
authenticated user who can see a project can see every ticket in that project
the moment it is created. This feature introduces a review step: a newly created
ticket is held in a `pending_approval` state and is visible only to its creator
and to admins. An admin must explicitly **approve** the ticket before it becomes
visible to everyone else who can see the project, or **reject** it, which
permanently deletes the ticket. Rejection is recorded in the audit log before
the row is removed, so the action remains traceable even though the ticket data
is gone.

The feature builds on the existing two-role RBAC model (`admin` / `user`), the
project-scoped visibility model, the layered backend architecture
(endpoint → service → repository), and the existing audit trail. It does **not**
introduce an organization/tenant concept; "everyone" means "everyone who can
already see the ticket's project" (all authenticated users for a public project,
admins for a private one), consistent with the current visibility rules in
`app/dependencies.py::get_current_project`.

## Glossary

- **Creator**: The authenticated user who created the ticket (`tickets.created_by`).
- **Admin**: A user whose `users.role` is `admin`. Enforced by the
  `get_admin_user` dependency in `app/dependencies.py`.
- **Approval_Status**: A new ticket field with two persisted values —
  `pending_approval` (awaiting review) and `approved` (visible to everyone who
  can see the project). A rejected ticket is deleted and therefore never
  persists a third value.
- **Approval_Service**: The ticket service layer (`app/services/ticket_service.py`)
  responsible for setting the initial approval status on creation, filtering
  reads by approval status, and executing approve/reject.
- **Visible_Audience**: The set of users who may see an approved ticket — i.e.
  everyone the existing project-visibility rules already grant access to the
  ticket's project.
- **Pending_Ticket**: A ticket whose `Approval_Status` is `pending_approval`.
- **Approval_Queue**: The list of `Pending_Ticket`s in the current project,
  available to admins for review.

## Requirements

### Requirement 1: Tickets Are Created Pending Approval

**User Story:** As any authenticated user, I want the tickets I create to enter
a review step, so that an admin can approve them before the wider audience sees
them.

#### Acceptance Criteria

1. WHEN any authenticated user creates a ticket, THE Approval_Service SHALL set
   the new ticket's `Approval_Status` to `pending_approval`.
2. WHEN a ticket is created, THE Approval_Service SHALL record the Creator as
   `tickets.created_by` and SHALL NOT require any approval field in the
   creation request payload.
3. THE Approval_Service SHALL continue to set the work-lifecycle `status` to
   `pending` on creation, independently of `Approval_Status` (the two fields are
   orthogonal).
4. WHEN a ticket is created, THE Approval_Service SHALL NOT notify the
   Visible_Audience; instead it SHALL notify admins that a ticket is awaiting
   approval and send the Creator their creation confirmation.

### Requirement 2: Pending Tickets Are Visible Only to Creator and Admins

**User Story:** As a Creator, I want my pending ticket to be visible to me and to
admins only, so that unreviewed content is not exposed to the whole project.

#### Acceptance Criteria

1. WHILE a ticket's `Approval_Status` is `pending_approval`, THE Approval_Service
   SHALL include that ticket in list, search, and detail results for the Creator.
2. WHILE a ticket's `Approval_Status` is `pending_approval`, THE Approval_Service
   SHALL include that ticket in list, search, and detail results for any Admin.
3. WHILE a ticket's `Approval_Status` is `pending_approval`, THE Approval_Service
   SHALL exclude that ticket from list, search, and detail results for every
   authenticated user who is neither the Creator nor an Admin.
4. WHEN a non-Creator, non-Admin requests a `Pending_Ticket` by id, THE
   Approval_Service SHALL respond as though the ticket does not exist (the same
   not-found response used for cross-project access), so pending tickets are not
   enumerable.
5. THE Approval_Service SHALL apply the same visibility rule to ticket counts and
   dashboard aggregations so a non-Creator, non-Admin's totals do not include
   pending tickets.

### Requirement 3: Tickets Visible to Everyone After Approval

**User Story:** As an admin, I want to approve a pending ticket, so that it
becomes visible to everyone who can see the project.

#### Acceptance Criteria

1. WHEN an Admin approves a `Pending_Ticket`, THE Approval_Service SHALL set its
   `Approval_Status` to `approved`.
2. WHEN an Admin approves a `Pending_Ticket`, THE Approval_Service SHALL record
   the approving Admin and the approval timestamp on the ticket.
3. WHILE a ticket's `Approval_Status` is `approved`, THE Approval_Service SHALL
   include that ticket in list, search, and detail results for the entire
   Visible_Audience.
4. WHEN an Admin approves a ticket that is already `approved`, THE
   Approval_Service SHALL return a success response without changing the existing
   approver or approval timestamp (idempotent).
5. WHEN approval succeeds, THE Approval_Service SHALL send the "new ticket"
   notifications that were deferred at creation time (admins and, if assigned,
   the assignee).

### Requirement 4: Rejecting a Ticket Deletes It

**User Story:** As an admin, I want to reject a pending ticket, so that
inappropriate or invalid tickets are permanently removed from the system.

#### Acceptance Criteria

1. WHEN an Admin rejects a `Pending_Ticket`, THE Approval_Service SHALL
   permanently delete the ticket and its cascading records (attachments,
   activities) via a hard delete.
2. BEFORE deleting the ticket, THE Approval_Service SHALL write an audit log
   entry capturing the rejecting Admin, the ticket id, the project id, the
   ticket title, and the Creator id, so the rejection remains traceable after
   deletion.
3. WHEN an Admin attempts to reject a ticket that is already `approved`, THE
   Approval_Service SHALL reject the request with a 409 Conflict response and
   SHALL NOT delete the ticket.
4. WHEN a reject request targets a ticket that does not exist or belongs to
   another project, THE Approval_Service SHALL return a 404 Not Found response.

### Requirement 5: Authorization — Approve and Reject Are Admin-Only

**User Story:** As a system operator, I want only admins to approve or reject
tickets, so that the review gate cannot be bypassed by regular users.

#### Acceptance Criteria

1. WHEN a non-Admin sends an approve request, THE Approval_Service SHALL return a
   403 Forbidden response and SHALL NOT change the ticket's `Approval_Status`.
2. WHEN a non-Admin sends a reject request, THE Approval_Service SHALL return a
   403 Forbidden response and SHALL NOT delete the ticket.
3. THE approve and reject endpoints SHALL use the existing `get_admin_user`
   dependency to enforce the admin role.
4. THE approve and reject endpoints SHALL remain scoped to the current project
   (via the existing `get_current_project` dependency), so an admin cannot act on
   a ticket outside the project context.

### Requirement 6: Approval Queue for Admins

**User Story:** As an admin, I want to see the list of tickets awaiting approval
in the current project, so that I can review them efficiently.

#### Acceptance Criteria

1. WHEN an Admin requests the Approval_Queue for the current project, THE
   Approval_Service SHALL return only tickets whose `Approval_Status` is
   `pending_approval`, scoped to that project, with pagination.
2. WHEN a non-Admin requests the Approval_Queue, THE Approval_Service SHALL
   return a 403 Forbidden response.
3. THE Approval_Queue SHALL support the same ordering guarantees as the existing
   ticket list (newest first by default).

### Requirement 7: Audit Logging of Approval Decisions

**User Story:** As a system operator, I want approval and rejection decisions
recorded in the audit log, so that there is a trail of who reviewed each ticket.

#### Acceptance Criteria

1. WHEN an Admin approves a ticket, THE Approval_Service SHALL write an audit log
   entry with a `ticket.approved` action, the Admin's id, the project id, the
   ticket id, and the ticket title.
2. WHEN an Admin rejects a ticket, THE Approval_Service SHALL write an audit log
   entry with a `ticket.rejected` action, the Admin's id, the project id, the
   (now-deleted) ticket id, the ticket title, and the Creator id.
3. THE audit writes SHALL follow the existing best-effort pattern (a logging
   failure SHALL NOT fail the approve/reject request).

### Requirement 8: Backward Compatibility for Existing Tickets

**User Story:** As a system operator, I want existing tickets to remain visible
after this feature ships, so that the approval gate does not retroactively hide
historical data.

#### Acceptance Criteria

1. WHEN the database migration runs, THE migration SHALL add the
   `Approval_Status` column with a default of `approved` for all pre-existing
   rows, so historical tickets stay visible to their current audience.
2. THE migration SHALL set the column default for NEW inserts in a way that does
   not conflict with the Approval_Service forcing `pending_approval` at the
   application layer on creation.
3. THE migration SHALL add the approver and approval-timestamp columns as
   nullable, so existing rows (and application inserts) are valid without them.

### Requirement 9: Frontend Surfacing of Approval State

**User Story:** As a user and as an admin, I want the UI to reflect approval
state, so that I can tell pending tickets apart and act on them.

#### Acceptance Criteria

1. WHERE a ticket is `pending_approval` and the viewer is its Creator or an
   Admin, THE ticket list and detail views SHALL display a clear "Pending
   approval" indicator.
2. WHERE the viewer is an Admin looking at a `Pending_Ticket`, THE ticket detail
   view SHALL present "Approve" and "Reject" actions.
3. WHEN an Admin triggers "Reject", THE UI SHALL require an explicit confirmation
   that warns the deletion is permanent before calling the API.
4. WHEN an approve or reject action succeeds, THE UI SHALL refresh the affected
   ticket list/detail so the change is reflected without a manual reload.
5. WHERE the viewer is an Admin, THE UI SHALL provide access to the
   Approval_Queue (the pending-tickets list) for the current project.
