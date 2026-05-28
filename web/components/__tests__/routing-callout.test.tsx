import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RoutingCallout } from "@/components/routing-callout";

describe("RoutingCallout", () => {
  it("renders body and source", () => {
    render(<RoutingCallout body="Skip eval_runner on first turn" source="Phoenix MCP" />);
    expect(screen.getByText(/Skip eval_runner on first turn/)).toBeInTheDocument();
    expect(screen.getByText("Phoenix MCP")).toBeInTheDocument();
  });

  it("renders default label 'Learned routing'", () => {
    render(<RoutingCallout body="x" source="y" />);
    expect(screen.getByText("Learned routing")).toBeInTheDocument();
  });

  it("renders custom label when provided", () => {
    render(<RoutingCallout label="Custom hint" body="x" source="y" />);
    expect(screen.getByText("Custom hint")).toBeInTheDocument();
    expect(screen.queryByText("Learned routing")).not.toBeInTheDocument();
  });
});
