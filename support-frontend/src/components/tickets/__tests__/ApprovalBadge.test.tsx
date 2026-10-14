import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApprovalBadge } from "@/components/tickets/ApprovalBadge";

describe("ApprovalBadge", () => {
  it("shows pending label when pending_approval", () => {
    render(<ApprovalBadge status="pending_approval" />);
    expect(screen.getByText(/pending approval/i)).toBeInTheDocument();
  });

  it("renders nothing when approved", () => {
    const { container } = render(<ApprovalBadge status="approved" />);
    expect(container).toBeEmptyDOMElement();
  });
});
