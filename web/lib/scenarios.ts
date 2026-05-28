import type { Severity } from "@/lib/types";

export interface Scenario {
  id: string;
  title: string;
  workflow: string;
  severity: Severity;
  watched_project: string;
  short_description: string;
  seeded_spans: number;
}

export const SCENARIOS: Scenario[] = [
  {
    id: "fraud-fp-burst",
    title: "False-positive burst on transaction classifier",
    workflow: "Fraud detection",
    severity: "P1",
    watched_project: "fraud-detector-prod",
    short_description:
      "FP rate spiked 3× in 90 seconds on the electronics merchant category. 1,247 legitimate transactions blocked, 312 customer accounts frozen, $84.3k in revenue at risk.",
    seeded_spans: 42,
  },
  {
    id: "kyc-sanctions-hallucination",
    title: "Sanctions-list hallucination on PEP screener",
    workflow: "KYC / AML",
    severity: "P0",
    watched_project: "kyc-screener-prod",
    short_description:
      "LLM-based PEP screener returned 7 fabricated OFAC matches in 120 seconds, 0 real matches in the same window. Regulatory disclosure threshold breached (FCA SUP 15.3, EU 5MLD Art. 33).",
    seeded_spans: 32,
  },
  {
    id: "lending-latency-regression",
    title: "Latency regression after model deploy",
    workflow: "Lending / underwriting",
    severity: "P2",
    watched_project: "underwriting-prod",
    short_description:
      "Underwriting model p99 jumped 280ms to 4,234ms within 8 minutes of deploy. 89 underwriting decisions delayed, 12 user-facing timeouts, SLA breached (target 800ms).",
    seeded_spans: 48,
  },
];

export function getScenario(id: string): Scenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}
