/**
 * Ticket-related TypeScript types.
 */

export type TicketStatus = "pending" | "in_progress" | "paused" | "in_review" | "completed";
export type TicketType = "technical_error" | "bug" | "feature" | "remove";
export type Priority = "critical" | "high" | "medium" | "low";
export type ApprovalStatus = "pending_approval" | "approved";

export interface Ticket {
  id: string;
  project_id: string;
  title: string;
  description: string;
  type: TicketType;
  priority: Priority;
  status: TicketStatus;
  approval_status: ApprovalStatus;
  approved_by: string | null;
  approved_at: string | null;
  jira_key: string | null;
  /** Bare FK column: the creator's user id. */
  created_by: string;
  /** Bare FK column: the assignee's user id (null if unassigned). */
  assigned_to: string | null;
  /** Nested creator user object (embedded by the API via a join). */
  created_by_user: UserSummary | null;
  /** Nested assignee user object (embedded by the API via a join). */
  assigned_to_user: UserSummary | null;
  attachments_count: number;
  activities_count: number;
  created_at: string;
  updated_at: string;
}

export interface TicketCreate {
  title: string;
  description: string;
  type: TicketType;
  priority: Priority;
  assigned_to?: string;
}

export interface TicketUpdate {
  title?: string;
  description?: string;
  type?: TicketType;
  priority?: Priority;
  status?: TicketStatus;
  assigned_to?: string | null;
}

export interface UserSummary {
  id: string;
  name: string;
  email: string;
}

export interface Attachment {
  id: string;
  ticket_id: string;
  file_name: string;
  s3_key: string;
  content_type: string;
  file_size: number;
  download_url: string | null;
  uploaded_by_user?: UserSummary | null;
  uploaded_at: string;
}

export type ActivityActionType =
  | "created"
  | "status_changed"
  | "updated"
  | "commented"
  | "file_uploaded"
  | "file_deleted"
  | "assigned";

export interface Activity {
  id: string;
  ticket_id: string;
  action_type: ActivityActionType;
  actor: UserSummary | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  comment: string | null;
  created_at: string;
}
