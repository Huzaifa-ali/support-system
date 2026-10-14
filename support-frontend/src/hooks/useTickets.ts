/**
 * Ticket data hooks using React Query.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveTicket,
  bulkAssign,
  bulkDelete,
  bulkStatusChange,
  createTicket,
  deleteTicket,
  getTicket,
  listPendingTickets,
  listTickets,
  rejectTicket,
  updateTicket,
  type TicketFilters,
} from "@/lib/ticketsApi";
import { useProjectContext } from "@/providers/ProjectProvider";
import type { TicketCreate, TicketStatus, TicketUpdate } from "@/types/ticket";

export function useTickets(filters: TicketFilters = {}) {
  const { selectedProjectId } = useProjectContext();
  return useQuery({
    queryKey: ["tickets", selectedProjectId, filters],
    queryFn: () => listTickets(filters),
    enabled: Boolean(selectedProjectId),
  });
}

export function useTicket(ticketId: string | undefined) {
  const { selectedProjectId } = useProjectContext();
  return useQuery({
    queryKey: ["ticket", selectedProjectId, ticketId],
    queryFn: () => getTicket(ticketId as string),
    enabled: Boolean(ticketId) && Boolean(selectedProjectId),
  });
}

export function useCreateTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { entity: "Ticket", action: "create" },
    mutationFn: (payload: TicketCreate) => createTicket(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}

export function useUpdateTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      ticketId,
      payload,
    }: {
      ticketId: string;
      payload: TicketUpdate;
    }) => updateTicket(ticketId, payload),
    meta: { entity: "Ticket", action: "update" },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
      void queryClient.invalidateQueries({ queryKey: ["ticket"] });
    },
  });
}

export function useDeleteTicket() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { entity: "Ticket", action: "delete" },
    mutationFn: (ticketId: string) => deleteTicket(ticketId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}

/** Invalidate ticket queries so lists and detail views refetch. */
function useInvalidateTickets() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    void queryClient.invalidateQueries({ queryKey: ["ticket"] });
    void queryClient.invalidateQueries({ queryKey: ["search"] });
  };
}

export function useBulkStatusChange() {
  const invalidate = useInvalidateTickets();
  return useMutation({
    mutationFn: ({
      ticketIds,
      status,
    }: {
      ticketIds: string[];
      status: TicketStatus;
    }) => bulkStatusChange(ticketIds, status),
    meta: { entity: "Tickets", successMessage: "Ticket statuses updated" },
    onSuccess: invalidate,
  });
}

export function useBulkAssign() {
  const invalidate = useInvalidateTickets();
  return useMutation({
    mutationFn: ({
      ticketIds,
      assignedTo,
    }: {
      ticketIds: string[];
      assignedTo: string;
    }) => bulkAssign(ticketIds, assignedTo),
    meta: { entity: "Tickets", successMessage: "Tickets assigned" },
    onSuccess: invalidate,
  });
}

export function useBulkDelete() {
  const invalidate = useInvalidateTickets();
  return useMutation({
    meta: { entity: "Tickets", successMessage: "Tickets deleted" },
    mutationFn: (ticketIds: string[]) => bulkDelete(ticketIds),
    onSuccess: invalidate,
  });
}

/** List tickets awaiting approval in the current project (admin only). */
export function usePendingTickets(page = 1, pageSize = 20) {
  const { selectedProjectId } = useProjectContext();
  return useQuery({
    queryKey: ["tickets", "pending", selectedProjectId, page, pageSize],
    queryFn: () => listPendingTickets(page, pageSize),
    enabled: Boolean(selectedProjectId),
  });
}

export function useApproveTicket() {
  const invalidate = useInvalidateTickets();
  return useMutation({
    meta: { entity: "Ticket", successMessage: "Ticket approved" },
    mutationFn: (ticketId: string) => approveTicket(ticketId),
    onSuccess: invalidate,
  });
}

export function useRejectTicket() {
  const invalidate = useInvalidateTickets();
  return useMutation({
    meta: { entity: "Ticket", successMessage: "Ticket rejected" },
    mutationFn: (ticketId: string) => rejectTicket(ticketId),
    onSuccess: invalidate,
  });
}
