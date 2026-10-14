"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useUpdateTicket } from "@/hooks/useTickets";
import { useAssignableUsers } from "@/hooks/useUsers";
import { PriorityBadge } from "@/components/ui/Badge";
import { ApprovalBadge } from "@/components/tickets/ApprovalBadge";
import type { TicketSortField } from "@/lib/ticketsApi";
import { cn, formatDateTime, formatStatus } from "@/lib/utils";
import type { Ticket, TicketStatus, TicketType } from "@/types/ticket";

interface TicketTableProps {
  tickets: Ticket[];
  /** Active sort field. */
  sortBy: TicketSortField;
  /** Active sort direction. */
  sortOrder: "asc" | "desc";
  /** Toggle/set sort when a sortable header is clicked. */
  onSort: (field: TicketSortField) => void;
  /** Called when the user requests deletion of a ticket. */
  onDelete: (ticket: Ticket) => void;
  /** IDs of the currently selected tickets (for bulk operations). */
  selectedIds: Set<string>;
  /** Toggle selection of a single ticket. */
  onToggleSelect: (ticketId: string) => void;
  /** Select or clear all tickets on the current page. */
  onToggleSelectAll: (select: boolean) => void;
}

/** Checkbox that supports the indeterminate ("some selected") visual state. */
function SelectCheckbox({
  checked,
  indeterminate,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: (checked: boolean) => void;
  ariaLabel: string;
}) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = Boolean(indeterminate) && !checked;
    }
  }, [indeterminate, checked]);

  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={ariaLabel}
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      className="h-4 w-4 cursor-pointer rounded border-input text-primary focus:ring-ring/50"
    />
  );
}

/** Tint the inline status <select> to match the status badge tones. */
const STATUS_SELECT_STYLES: Record<TicketStatus, string> = {
  pending: "bg-surface-muted text-muted-foreground",
  in_progress: "bg-info-soft text-info",
  paused: "bg-warning-soft text-warning",
  in_review: "bg-primary-soft text-primary-soft-foreground",
  completed: "bg-success-soft text-success",
};

const STATUS_VALUES: TicketStatus[] = [
  "pending",
  "in_progress",
  "paused",
  "in_review",
  "completed",
];

const TYPE_VALUES: TicketType[] = [
  "technical_error",
  "bug",
  "feature",
  "remove",
];

interface ColumnDef {
  label: string;
  field?: TicketSortField;
  align?: "right";
}

const COLUMNS: ColumnDef[] = [
  { label: "Title", field: "title" },
  { label: "Type" },
  { label: "Priority", field: "priority" },
  { label: "Status", field: "status" },
  { label: "Assigned" },
  { label: "Created", field: "created_at" },
  { label: "Actions", align: "right" },
];

function SortIndicator({
  active,
  order,
}: {
  active: boolean;
  order: "asc" | "desc";
}) {
  if (!active)
    return (
      <ChevronsUpDown className="ml-1 inline h-3.5 w-3.5 text-muted-foreground/50" />
    );
  return order === "asc" ? (
    <ArrowUp className="ml-1 inline h-3.5 w-3.5" />
  ) : (
    <ArrowDown className="ml-1 inline h-3.5 w-3.5" />
  );
}

const inlineSelectBase =
  "rounded-md border border-input bg-surface px-2 py-1 text-xs text-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring/40 disabled:opacity-50";

export function TicketTable({
  tickets,
  sortBy,
  sortOrder,
  onSort,
  onDelete,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
}: TicketTableProps) {
  const router = useRouter();
  const { isAdmin } = useAuth();
  const updateTicket = useUpdateTicket();
  // Assignment is admin-only, so only admins load the assignable-users list.
  const { data: assignableUsers, isLoading: usersLoading } =
    useAssignableUsers(isAdmin);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const selectedOnPage = tickets.filter((t) => selectedIds.has(t.id)).length;
  const allSelected = tickets.length > 0 && selectedOnPage === tickets.length;
  const someSelected = selectedOnPage > 0 && !allSelected;

  /** Apply an inline field update, keeping the row disabled while in flight. */
  async function applyUpdate(
    ticket: Ticket,
    payload: Parameters<typeof updateTicket.mutateAsync>[0]["payload"]
  ) {
    setPendingId(ticket.id);
    try {
      await updateTicket.mutateAsync({ ticketId: ticket.id, payload });
    } finally {
      setPendingId(null);
    }
  }

  function handleStatusChange(ticket: Ticket, status: TicketStatus) {
    if (status === ticket.status) return;
    void applyUpdate(ticket, { status });
  }

  function handleTypeChange(ticket: Ticket, type: TicketType) {
    if (type === ticket.type) return;
    void applyUpdate(ticket, { type });
  }

  function handleAssigneeChange(ticket: Ticket, value: string) {
    const nextAssignee = value || null;
    if (nextAssignee === (ticket.assigned_to ?? null)) return;
    void applyUpdate(ticket, { assigned_to: nextAssignee });
  }

  return (
    <table className="w-full min-w-[820px] text-sm">
      <thead className="border-b bg-surface-muted">
        <tr>
          <th className="w-10 px-4 py-3 text-left">
            <SelectCheckbox
              ariaLabel="Select all tickets on this page"
              checked={allSelected}
              indeterminate={someSelected}
              onChange={(checked) => onToggleSelectAll(checked)}
            />
          </th>
          {COLUMNS.map((col) => (
            <th
              key={col.label}
              className={cn(
                "px-4 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                col.align === "right" ? "text-right" : "text-left"
              )}
            >
              {col.field ? (
                <button
                  type="button"
                  onClick={() => onSort(col.field as TicketSortField)}
                  className="font-semibold uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
                >
                  {col.label}
                  <SortIndicator
                    active={sortBy === col.field}
                    order={sortOrder}
                  />
                </button>
              ) : (
                col.label
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y">
        {tickets.map((ticket) => {
          const rowPending = pendingId === ticket.id;
          return (
            <tr
              key={ticket.id}
              onClick={() => router.push(`/tickets/${ticket.id}`)}
              className={cn(
                "cursor-pointer transition-colors hover:bg-surface-muted/60",
                selectedIds.has(ticket.id) && "bg-primary-soft/50"
              )}
            >
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <SelectCheckbox
                  ariaLabel={`Select ticket ${ticket.title}`}
                  checked={selectedIds.has(ticket.id)}
                  onChange={() => onToggleSelect(ticket.id)}
                />
              </td>
              <td className="px-4 py-3">
                <span className="font-medium text-foreground">
                  {ticket.title}
                </span>
              </td>
              {/* Inline type editing (available to all users). */}
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <select
                  value={ticket.type}
                  disabled={rowPending}
                  onChange={(e) =>
                    handleTypeChange(ticket, e.target.value as TicketType)
                  }
                  className={inlineSelectBase}
                >
                  {TYPE_VALUES.map((t) => (
                    <option key={t} value={t}>
                      {formatStatus(t)}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-4 py-3">
                <PriorityBadge priority={ticket.priority} />
              </td>
              {/* Inline status editing (available to all users). */}
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center gap-2">
                  <select
                    value={ticket.status}
                    disabled={rowPending}
                    onChange={(e) =>
                      handleStatusChange(ticket, e.target.value as TicketStatus)
                    }
                    className={cn(
                      "rounded-full border-0 px-2.5 py-1 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-50",
                      STATUS_SELECT_STYLES[ticket.status]
                    )}
                  >
                    {STATUS_VALUES.map((s) => (
                      <option key={s} value={s}>
                        {formatStatus(s)}
                      </option>
                    ))}
                  </select>
                  <ApprovalBadge status={ticket.approval_status} />
                </div>
              </td>
              {/* Inline assignee editing for admins; read-only text otherwise. */}
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                {isAdmin ? (
                  <select
                    value={ticket.assigned_to ?? ""}
                    disabled={rowPending || usersLoading}
                    onChange={(e) =>
                      handleAssigneeChange(ticket, e.target.value)
                    }
                    className={inlineSelectBase}
                  >
                    <option value="">Unassigned</option>
                    {(assignableUsers ?? []).map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="text-muted-foreground">
                    {ticket.assigned_to_user?.name ?? "Unassigned"}
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-muted-foreground">
                {formatDateTime(ticket.created_at)}
              </td>
              <td
                className="px-4 py-3 text-right"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => router.push(`/tickets/${ticket.id}/edit`)}
                  className="mr-3 text-sm font-medium text-primary hover:text-primary-hover"
                >
                  Edit
                </button>
                <button
                  onClick={() => onDelete(ticket)}
                  className="text-sm font-medium text-danger hover:text-danger/80"
                >
                  Delete
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
