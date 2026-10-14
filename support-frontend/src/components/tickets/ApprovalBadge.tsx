import { Badge } from "@/components/ui/Badge";
import type { ApprovalStatus } from "@/types/ticket";

interface ApprovalBadgeProps {
  status: ApprovalStatus;
}

/** Shows a "Pending approval" indicator; renders nothing for approved tickets. */
export function ApprovalBadge({ status }: ApprovalBadgeProps) {
  if (status !== "pending_approval") return null;
  return <Badge tone="warning">Pending approval</Badge>;
}
