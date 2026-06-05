import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PostmortemDocument } from "@/components/postmortem-document";
import type { Postmortem } from "@/lib/types";

const samplePm: Postmortem = {
  title: "False Positive Spike",
  incident_id: "fraud-x-abc12345",
  severity: "P1",
  summary: "A spike of false positives occurred between 13:16 and 13:21 UTC affecting electronics.",
  impact: "12 legitimate transactions blocked, totaling $1,234 in revenue impact.",
  timeline: [
    "13:16 UTC — Onset of spike detected.",
    "13:21 UTC — Final false positive observed.",
  ],
  root_cause: "The model exhibited over-sensitive thresholding for electronics over $800.",
  detection: "Discovered via automated post-hoc verification logs.",
  resolution: "Investigation is ongoing; rollback under evaluation.",
  action_items: [
    {
      description: "Investigate model sensitivity to electronics category.",
      owner_role: "fraud-ml-team",
      severity: "P2",
      due_within_days: 7,
    },
  ],
  lessons_learned: ["High-confidence scores are unreliable during drift events."],
};

describe("PostmortemDocument", () => {
  it("renders the title", () => {
    render(<PostmortemDocument pm={samplePm} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("False Positive Spike");
  });

  it("renders all 8 section labels", () => {
    render(<PostmortemDocument pm={samplePm} />);
    for (const label of [
      "Summary",
      "Impact",
      "Timeline",
      "Root cause",
      "Detection",
      "Resolution",
      "Action items",
      "Lessons learned",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders the severity badge", () => {
    render(<PostmortemDocument pm={samplePm} />);
    expect(screen.getByText("P1")).toBeInTheDocument();
  });

  it("renders timeline entries with time and text columns", () => {
    render(<PostmortemDocument pm={samplePm} />);
    expect(screen.getByText("13:16 UTC")).toBeInTheDocument();
    expect(screen.getByText("Onset of spike detected.")).toBeInTheDocument();
  });

  it("renders each action item with owner role and due days", () => {
    render(<PostmortemDocument pm={samplePm} />);
    expect(screen.getByText("fraud-ml-team")).toBeInTheDocument();
    expect(screen.getByText("7 days")).toBeInTheDocument();
  });

  it("renders lessons learned", () => {
    render(<PostmortemDocument pm={samplePm} />);
    expect(
      screen.getByText("High-confidence scores are unreliable during drift events.")
    ).toBeInTheDocument();
  });

  it("renders the completeness badge when score is provided", () => {
    render(<PostmortemDocument pm={samplePm} completenessScore={0.95} completenessLabel="complete" />);
    expect(screen.getByText(/Validated · 0\.950/)).toBeInTheDocument();
  });

  it("omits the completeness badge when score is undefined", () => {
    render(<PostmortemDocument pm={samplePm} />);
    expect(screen.queryByText(/Validated · /)).not.toBeInTheDocument();
  });

  // ── Phase 8 / ADR-018 — Quantified-impact hero + audit citations ─────

  it("renders the quantified-impact hero when impact_quantified is present", () => {
    const pmWithImpact: Postmortem = {
      ...samplePm,
      impact_quantified: {
        dollars_at_risk_usd: 84293.2,
        customers_affected: 312,
        transactions_affected: 1247,
        estimated_revenue_loss_usd: 13668.18,
        customer_trust_score_delta: -0.281,
        audit_citation_lines: [
          "transactions_affected=1247 [source: scenario.impact_seed.affected_transactions]",
          "avg_transaction_usd=67.60 [source: scenario.impact_seed]",
          "dollars_at_risk_usd=84293.20 [source: derived: 1247 * 67.60]",
        ],
        confidence: "seed_grounded",
        caveats: [],
      },
    };
    render(<PostmortemDocument pm={pmWithImpact} />);
    expect(screen.getByText("Quantified impact")).toBeInTheDocument();
    expect(screen.getByText("Audit citations")).toBeInTheDocument();
    // Dollar figure rendered (rounded to no fractional cents).
    expect(screen.getByText("$84,293")).toBeInTheDocument();
    // Customer + transaction counts as integers.
    expect(screen.getByText("312")).toBeInTheDocument();
    expect(screen.getByText("1,247")).toBeInTheDocument();
    // Confidence badge picked the seed-grounded label.
    expect(screen.getByText("Seed-grounded")).toBeInTheDocument();
    // Each citation line is rendered verbatim.
    expect(
      screen.getByText(
        /transactions_affected=1247 \[source: scenario\.impact_seed\.affected_transactions\]/,
      ),
    ).toBeInTheDocument();
  });

  it("renders caveats when impact_quantified.confidence is degraded", () => {
    const pmWithCaveats: Postmortem = {
      ...samplePm,
      impact_quantified: {
        dollars_at_risk_usd: 0,
        customers_affected: 0,
        transactions_affected: 0,
        estimated_revenue_loss_usd: 0,
        customer_trust_score_delta: 0,
        audit_citation_lines: ["scenario.impact_seed=<empty>"],
        confidence: "default_caveat",
        caveats: [
          "Scenario impact_seed was empty; figures default to zero pending seed authoring.",
        ],
      },
    };
    render(<PostmortemDocument pm={pmWithCaveats} />);
    expect(screen.getByText("Default (caveat)")).toBeInTheDocument();
    expect(screen.getByText("Caveats")).toBeInTheDocument();
    expect(
      screen.getByText(/Scenario impact_seed was empty/),
    ).toBeInTheDocument();
  });

  it("omits the quantified-impact hero when impact_quantified is null/undefined", () => {
    render(<PostmortemDocument pm={samplePm} />);
    expect(screen.queryByText("Quantified impact")).not.toBeInTheDocument();
    expect(screen.queryByText("Audit citations")).not.toBeInTheDocument();
  });
});
