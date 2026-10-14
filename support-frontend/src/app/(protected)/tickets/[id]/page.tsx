"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Check, ExternalLink, Trash2, X } from "lucide-react";
import {
  useApproveTicket,
  useDeleteTicket,
  useRejectTicket,
  useTicket,
} from "@/hooks/useTickets";
import { useAuth } from "@/hooks/useAuth";
import { useToast } from "@/providers/ToastProvider";
import { AssigneeControl } from "@/components/tickets/AssigneeControl";
import { ApprovalBadge } from "@/components/tickets/ApprovalBadge";
import { AttachmentList } from "@/components/tickets/AttachmentList";
import { FileUpload } from "@/components/tickets/FileUpload";
import { TicketComments } from "@/components/tickets/TicketComments";
import { TicketTimeline } from "@/components/tickets/TicketTimeline";
import {
  Badge,
  PriorityBadge,
  StatusBadge,
  TypeBadge,
} from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/Spinner";
import { ConfirmDialog } from "@/components/ui/Modal";
import { formatDateTime } from "@/lib/utils";

export default function TicketDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const ticketId = params?.id;

  const { data, isLoading, error } = useTicket(ticketId);
  const { isAdmin } = useAuth();
  const deleteTicket = useDeleteTicket();
  const approveTicket = useApproveTicket();
  const rejectTicket = useRejectTicket();
  const [showDelete, setShowDelete] = useState(false);
  const [showReject, setShowReject] = useState(false);

  const ticket = data?.data;

  async function handleDelete() {
    if (!ticketId) return;
    try {
      await deleteTicket.mutateAsync(ticketId);
      toast.success("Ticket deleted");
      router.push("/tickets");
    } catch {
      toast.error("Delete failed", "Please try again.");
    }
  }

  async function handleApprove() {
    if (!ticketId) return;
    try {
      await approveTicket.mutateAsync(ticketId);
      toast.success("Ticket approved");
    } catch {
      toast.error("Approve failed", "Please try again.");
    }
  }

  async function handleReject() {
    if (!ticketId) return;
    try {
      await rejectTicket.mutateAsync(ticketId);
      toast.success("Ticket rejected");
      router.push("/tickets");
    } catch {
      toast.error("Reject failed", "Please try again.");
    }
  }

  if (isLoading) {
    return <LoadingState label="Loading ticket..." />;
  }

  if (error || !ticket) {
    return (
      <EmptyState
        title="Ticket not found"
        description="This ticket could not be loaded. It may have been deleted."
        action={
          <Button
            variant="outline"
            leftIcon={<ArrowLeft className="h-4 w-4" />}
            onClick={() => router.push("/tickets")}
          >
            Back to tickets
          </Button>
        }
      />
    );
  }

  const creatorName = ticket.created_by_user?.name ?? "Unknown";

  return (
    <div className="space-y-6">
      <div>
        <button
          onClick={() => router.push("/tickets")}
          className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to tickets
        </button>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {ticket.title}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Created by{" "}
              <span className="font-medium text-foreground">{creatorName}</span>{" "}
              · {formatDateTime(ticket.created_at)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {isAdmin && ticket.approval_status === "pending_approval" && (
              <>
                <Button
                  variant="primary"
                  leftIcon={<Check className="h-4 w-4" />}
                  onClick={handleApprove}
                  isLoading={approveTicket.isPending}
                >
                  Approve
                </Button>
                <Button
                  variant="danger"
                  leftIcon={<X className="h-4 w-4" />}
                  onClick={() => setShowReject(true)}
                >
                  Reject
                </Button>
              </>
            )}
            <Button
              variant="outline"
              onClick={() => router.push(`/tickets/${ticketId}/edit`)}
            >
              Edit
            </Button>
            <Button
              variant="danger"
              leftIcon={<Trash2 className="h-4 w-4" />}
              onClick={() => setShowDelete(true)}
            >
              <span className="hidden sm:inline">Delete</span>
            </Button>
          </div>
        </div>
      </div>

      {/* Two-column layout: ticket details on the left, activity timeline on the right. */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left / main column */}
        <div className="space-y-6 lg:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={ticket.status} />
            <ApprovalBadge status={ticket.approval_status} />
            <PriorityBadge priority={ticket.priority} />
            <TypeBadge type={ticket.type} />
            {ticket.jira_key && (
              <Badge tone="primary">
                <ExternalLink className="h-3 w-3" />
                {ticket.jira_key}
              </Badge>
            )}
          </div>

          <Card className="p-6">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Description
            </h2>
            <p className="mt-2 whitespace-pre-wrap text-foreground">
              {ticket.description}
            </p>
          </Card>

          <Card className="p-6">
            <dl className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Created by
                </dt>
                <dd className="mt-1 text-sm text-foreground">{creatorName}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Assigned to
                </dt>
                <dd className="mt-1">
                  <AssigneeControl ticket={ticket} />
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Created
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {formatDateTime(ticket.created_at)}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Last updated
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {formatDateTime(ticket.updated_at)}
                </dd>
              </div>
            </dl>
          </Card>

          <Card className="space-y-4 p-6">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Attachments
            </h2>
            <FileUpload ticketId={ticket.id} />
            <AttachmentList ticketId={ticket.id} />
          </Card>
        </div>

        {/* Right column: activity timeline (events only) */}
        <div className="lg:col-span-1">
          <div className="lg:sticky lg:top-24">
            <TicketTimeline ticketId={ticket.id} />
          </div>
        </div>
      </div>

      {/* Comments — a separate section at the bottom of the page. */}
      <TicketComments ticketId={ticket.id} />

      <ConfirmDialog
        open={showDelete}
        onClose={() => setShowDelete(false)}
        onConfirm={handleDelete}
        title="Delete ticket?"
        description={`This will permanently delete "${ticket.title}". This action cannot be undone.`}
        confirmLabel="Delete"
        destructive
        isLoading={deleteTicket.isPending}
      />

      <ConfirmDialog
        open={showReject}
        onClose={() => setShowReject(false)}
        onConfirm={handleReject}
        title="Reject ticket?"
        description={`This will permanently delete "${ticket.title}". This action cannot be undone.`}
        confirmLabel="Reject"
        destructive
        isLoading={rejectTicket.isPending}
      />
    </div>
  );
}
