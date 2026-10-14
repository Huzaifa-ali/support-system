"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Ticket as TicketIcon } from "lucide-react";
import {
  useBulkDelete,
  useDeleteTicket,
  usePendingTickets,
  useTickets,
} from "@/hooks/useTickets";
import { useSearch } from "@/hooks/useSearch";
import { useAuth } from "@/hooks/useAuth";
import { useProjectContext } from "@/providers/ProjectProvider";
import { useToast } from "@/providers/ToastProvider";
import { BulkActionBar } from "@/components/tickets/BulkActionBar";
import { FilterBar } from "@/components/tickets/FilterBar";
import { TicketTable } from "@/components/tickets/TicketTable";
import { SearchBar } from "@/components/search/SearchBar";
import { SavedFilters } from "@/components/search/SavedFilters";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { TableSkeleton } from "@/components/ui/Skeleton";
import { ConfirmDialog } from "@/components/ui/Modal";
import type { TicketFilters, TicketSortField } from "@/lib/ticketsApi";
import type { SavedFilterValues } from "@/types/search";
import type { Ticket } from "@/types/ticket";

const PAGE_SIZE = 20;

/** Filter fields the FilterBar controls (everything except pagination/sort). */
type FilterState = Omit<
  TicketFilters,
  "page" | "pageSize" | "sortBy" | "sortOrder"
>;

export default function TicketsPage() {
  const { selectedProject } = useProjectContext();
  const { isAdmin } = useAuth();
  const toast = useToast();

  const [filters, setFilters] = useState<FilterState>({});
  const [sortBy, setSortBy] = useState<TicketSortField>("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [showPending, setShowPending] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Ticket | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);

  // A search is "active" once the debounced query passes the backend minimum.
  const isSearching = searchQuery.trim().length >= 2;

  const query = useMemo<TicketFilters>(
    () => ({ ...filters, page, pageSize: PAGE_SIZE, sortBy, sortOrder }),
    [filters, page, sortBy, sortOrder]
  );

  const ticketsQuery = useTickets(query);
  // Admin-only view of tickets awaiting approval.
  const pendingQuery = usePendingTickets(page, PAGE_SIZE);
  // Search reuses the same status/type/priority filters as the list view.
  const searchResultsQuery = useSearch({
    q: searchQuery,
    status: filters.status,
    type: filters.type,
    priority: filters.priority,
    page,
    pageSize: PAGE_SIZE,
  });
  const deleteTicket = useDeleteTicket();
  const bulkDelete = useBulkDelete();

  // Swap the data source: search takes precedence, then the admin pending
  // queue toggle, otherwise the standard filtered list.
  const active = isSearching
    ? searchResultsQuery
    : showPending
      ? pendingQuery
      : ticketsQuery;
  // Memoized so its reference is stable across renders (the effect below and
  // select-all depend on it).
  const tickets = useMemo(() => active.data?.data ?? [], [active.data]);
  const pagination = active.data?.pagination;
  const isLoading = active.isLoading;
  const error = active.error;

  // Drop selections for tickets no longer present in the current view (e.g.
  // after paging, filtering, or a delete). Keeps the selection consistent
  // with what the user can actually see and act on.
  useEffect(() => {
    const visible = new Set(tickets.map((t) => t.id));
    setSelectedIds((prev) => {
      const next = new Set(Array.from(prev).filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [tickets]);

  function toggleSelect(ticketId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(ticketId)) {
        next.delete(ticketId);
      } else {
        next.add(ticketId);
      }
      return next;
    });
  }

  function toggleSelectAll(select: boolean) {
    setSelectedIds(select ? new Set(tickets.map((t) => t.id)) : new Set());
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function handleBulkDelete() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    try {
      await bulkDelete.mutateAsync(ids);
      toast.success(
        `Deleted ${ids.length} ${ids.length === 1 ? "ticket" : "tickets"}`
      );
      setBulkDeleteOpen(false);
      clearSelection();
    } catch {
      toast.error("Bulk delete failed", "Please try again.");
    }
  }

  function handleFilterChange(patch: Partial<FilterState>) {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1); // Any filter change resets to the first page.
  }

  function handleReset() {
    setFilters({});
    setPage(1);
  }

  function handleSearchChange(q: string) {
    setSearchQuery(q);
    setPage(1); // New query starts from the first page.
  }

  function handleTogglePending() {
    setShowPending((prev) => !prev);
    setPage(1); // Switching data source resets to the first page.
  }

  function handleApplySavedFilter(saved: SavedFilterValues) {
    setFilters((prev) => ({
      ...prev,
      status: saved.status,
      type: saved.type,
      priority: saved.priority,
    }));
    setPage(1);
  }

  function handleSort(field: TicketSortField) {
    if (field === sortBy) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(field);
      setSortOrder("desc");
    }
    setPage(1);
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteTicket.mutateAsync(deleteTarget.id);
      toast.success("Ticket deleted");
      setDeleteTarget(null);
    } catch {
      toast.error("Delete failed", "Please try again.");
    }
  }

  const currentFilterValues: SavedFilterValues = {
    status: filters.status,
    type: filters.type,
    priority: filters.priority,
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Tickets
          </h1>
          {selectedProject && (
            <p className="text-sm text-muted-foreground">
              {selectedProject.name}
            </p>
          )}
        </div>
        <Link href="/tickets/new">
          <Button leftIcon={<Plus className="h-4 w-4" />}>New Ticket</Button>
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <SearchBar value={searchQuery} onDebouncedChange={handleSearchChange} />
        <SavedFilters
          currentFilters={currentFilterValues}
          onApply={handleApplySavedFilter}
        />
        {isAdmin && (
          <Button
            variant={showPending ? "primary" : "outline"}
            size="sm"
            onClick={handleTogglePending}
          >
            {showPending ? "Showing pending approval" : "Show pending approval"}
          </Button>
        )}
      </div>

      <FilterBar
        filters={filters}
        onChange={handleFilterChange}
        onReset={handleReset}
      />

      {isSearching && (
        <p className="text-sm text-muted-foreground">
          Showing results for{" "}
          <span className="font-medium text-foreground">
            &ldquo;{searchQuery}&rdquo;
          </span>
        </p>
      )}

      {isLoading ? (
        <TableSkeleton rows={8} />
      ) : error ? (
        <EmptyState
          icon={TicketIcon}
          title={isSearching ? "Search failed" : "Failed to load tickets"}
          description="Something went wrong. Please try again in a moment."
        />
      ) : tickets.length === 0 ? (
        <EmptyState
          icon={TicketIcon}
          title={isSearching ? "No matching tickets" : "No tickets yet"}
          description={
            isSearching
              ? "No tickets match your search. Try a different term or clear your filters."
              : "Create your first ticket to start tracking issues for this project."
          }
          action={
            !isSearching ? (
              <Link href="/tickets/new">
                <Button leftIcon={<Plus className="h-4 w-4" />}>
                  New Ticket
                </Button>
              </Link>
            ) : undefined
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border bg-surface shadow-soft">
          <div className="overflow-x-auto">
            <TicketTable
              tickets={tickets}
              sortBy={sortBy}
              sortOrder={sortOrder}
              onSort={handleSort}
              onDelete={setDeleteTarget}
              selectedIds={selectedIds}
              onToggleSelect={toggleSelect}
              onToggleSelectAll={toggleSelectAll}
            />
          </div>
        </div>
      )}

      {selectedIds.size > 0 && (
        <BulkActionBar
          selectedIds={Array.from(selectedIds)}
          onClear={clearSelection}
          onRequestDelete={() => setBulkDeleteOpen(true)}
        />
      )}

      {pagination && pagination.total_pages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Page {pagination.page} of {pagination.total_pages} ·{" "}
            {pagination.total} tickets
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setPage((p) => Math.min(pagination.total_pages, p + 1))
              }
              disabled={page >= pagination.total_pages}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="Delete ticket?"
        description={
          deleteTarget
            ? `This will permanently delete "${deleteTarget.title}". This action cannot be undone.`
            : undefined
        }
        confirmLabel="Delete"
        destructive
        isLoading={deleteTicket.isPending}
      />

      <ConfirmDialog
        open={bulkDeleteOpen}
        onClose={() => setBulkDeleteOpen(false)}
        onConfirm={handleBulkDelete}
        title={`Delete ${selectedIds.size} ${
          selectedIds.size === 1 ? "ticket" : "tickets"
        }?`}
        description="This will permanently delete the selected tickets. This action cannot be undone."
        confirmLabel="Delete"
        destructive
        isLoading={bulkDelete.isPending}
      />
    </div>
  );
}
