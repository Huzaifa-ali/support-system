/**
 * Ticket API functions.
 *
 * All ticket endpoints are scoped to the currently selected project. The
 * shared api client attaches the X-Project-ID header automatically.
 */

import { api } from "@/lib/api";
import type { PaginationMeta } from "@/types/project";
import type {
  Priority,
  Ticket,
  TicketCreate,
  TicketStatus,
  TicketType,
  TicketUpdate,
} from "@/types/ticket";

export interface TicketListResponse {
  data: Ticket[];
  pagination: PaginationMeta;
}

export interface TicketResponse {
  data: Ticket;
  message: string;
}

export type TicketSortField =
  | "created_at"
  | "updated_at"
  | "priority"
  | "status"
  | "title";

export interface TicketFilters {
  page?: number;
  pageSize?: number;
  status?: TicketStatus;
  type?: TicketType;
  priority?: Priority;
  assignedTo?: string;
  createdBy?: string;
  /** ISO datetime lower bound on created_at. */
  dateFrom?: string;
  /** ISO datetime upper bound on created_at. */
  dateTo?: string;
  sortBy?: TicketSortField;
  sortOrder?: "asc" | "desc";
}

export async function listTickets(
  filters: TicketFilters = {}
): Promise<TicketListResponse> {
  const params: Record<string, string> = {
    page: String(filters.page ?? 1),
    page_size: String(filters.pageSize ?? 20),
  };
  if (filters.status) params.status = filters.status;
  if (filters.type) params.type = filters.type;
  if (filters.priority) params.priority = filters.priority;
  if (filters.assignedTo) params.assigned_to = filters.assignedTo;
  if (filters.createdBy) params.created_by = filters.createdBy;
  if (filters.dateFrom) params.date_from = filters.dateFrom;
  if (filters.dateTo) params.date_to = filters.dateTo;
  if (filters.sortBy) params.sort_by = filters.sortBy;
  if (filters.sortOrder) params.sort_order = filters.sortOrder;

  return api.get<TicketListResponse>("/tickets", params);
}

export async function getTicket(ticketId: string): Promise<TicketResponse> {
  return api.get<TicketResponse>(`/tickets/${ticketId}`);
}

export async function createTicket(
  payload: TicketCreate
): Promise<TicketResponse> {
  return api.post<TicketResponse>("/tickets", payload);
}

export async function updateTicket(
  ticketId: string,
  payload: TicketUpdate
): Promise<TicketResponse> {
  return api.patch<TicketResponse>(`/tickets/${ticketId}`, payload);
}

export async function deleteTicket(ticketId: string): Promise<void> {
  return api.delete(`/tickets/${ticketId}`);
}

/** List tickets awaiting approval (admin only). */
export async function listPendingTickets(
  page = 1,
  pageSize = 20
): Promise<TicketListResponse> {
  return api.get<TicketListResponse>("/tickets/pending-approval", {
    page: String(page),
    page_size: String(pageSize),
  });
}

/** Approve a pending ticket (admin only). */
export async function approveTicket(ticketId: string): Promise<TicketResponse> {
  return api.post<TicketResponse>(`/tickets/${ticketId}/approve`, {});
}

/**
 * Reject a pending ticket (admin only). This is a POST on the backend that
 * returns 204 No Content, so we use api.post typed to void — the shared client
 * returns undefined for 204 responses.
 */
export async function rejectTicket(ticketId: string): Promise<void> {
  return api.post<void>(`/tickets/${ticketId}/reject`, {});
}

/** A single ticket that failed within a bulk operation. */
export interface BulkFailure {
  ticket_id: string;
  reason: string;
}

/** Result summary returned by every bulk operation. */
export interface BulkResult {
  success_count: number;
  failure_count: number;
  failures: BulkFailure[];
}

interface BulkResponse {
  data: BulkResult;
}

/** Change the status of multiple tickets in the current project. */
export async function bulkStatusChange(
  ticketIds: string[],
  status: TicketStatus
): Promise<BulkResult> {
  const res = await api.post<BulkResponse>("/tickets/bulk/status", {
    ticket_ids: ticketIds,
    status,
  });
  return res.data;
}

/** Assign multiple tickets to a user (admin only). */
export async function bulkAssign(
  ticketIds: string[],
  assignedTo: string
): Promise<BulkResult> {
  const res = await api.post<BulkResponse>("/tickets/bulk/assign", {
    ticket_ids: ticketIds,
    assigned_to: assignedTo,
  });
  return res.data;
}

/** Delete multiple tickets (admin only). */
export async function bulkDelete(ticketIds: string[]): Promise<BulkResult> {
  const res = await api.post<BulkResponse>("/tickets/bulk/delete", {
    ticket_ids: ticketIds,
  });
  return res.data;
}
