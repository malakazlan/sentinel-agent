import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentStepper, type AgentStep } from "@/components/agent-stepper";

const baseSteps: AgentStep[] = [
  { name: "Coordinator", status: "done", action: "Synthesized", meta: "+0s" },
  { name: "Trace analyzer", status: "running", action: "Pulling traces", meta: "+5s" },
  { name: "Root cause", status: "queued", action: "Awaiting", meta: "queued" },
  { name: "Eval runner", status: "skipped", action: "Skipped per directive", meta: "—" },
];

describe("AgentStepper", () => {
  it("renders every step", () => {
    render(<AgentStepper steps={baseSteps} />);
    expect(screen.getByText("Coordinator")).toBeInTheDocument();
    expect(screen.getByText("Trace analyzer")).toBeInTheDocument();
    expect(screen.getByText("Root cause")).toBeInTheDocument();
    expect(screen.getByText("Eval runner")).toBeInTheDocument();
  });

  it("renders the action text for each step", () => {
    render(<AgentStepper steps={baseSteps} />);
    expect(screen.getByText("Synthesized")).toBeInTheDocument();
    expect(screen.getByText("Pulling traces")).toBeInTheDocument();
  });

  it("renders the meta column", () => {
    render(<AgentStepper steps={baseSteps} />);
    expect(screen.getByText("+0s")).toBeInTheDocument();
    expect(screen.getByText("+5s")).toBeInTheDocument();
  });

  it("renders a model badge when provided", () => {
    const stepsWithModel: AgentStep[] = [
      { name: "Coordinator", model: "gemini-3.1-pro", status: "done", action: "x", meta: "y" },
    ];
    render(<AgentStepper steps={stepsWithModel} />);
    expect(screen.getByText("gemini-3.1-pro")).toBeInTheDocument();
  });

  it("renders no steps when array is empty", () => {
    const { container } = render(<AgentStepper steps={[]} />);
    expect(container.querySelectorAll("[role]").length).toBeLessThanOrEqual(1);
  });
});
