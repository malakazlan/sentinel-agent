import { describe, it, expect } from "vitest";
import { SCENARIOS, getScenario } from "@/lib/scenarios";

describe("SCENARIOS", () => {
  it("contains exactly 3 scenarios", () => {
    expect(SCENARIOS).toHaveLength(3);
  });

  it("includes fraud, kyc, and lending scenarios", () => {
    const ids = SCENARIOS.map((s) => s.id);
    expect(ids).toContain("fraud-fp-burst");
    expect(ids).toContain("kyc-sanctions-hallucination");
    expect(ids).toContain("lending-latency-regression");
  });

  it("each scenario has valid severity", () => {
    for (const s of SCENARIOS) {
      expect(["P0", "P1", "P2", "P3"]).toContain(s.severity);
    }
  });

  it("each scenario has a non-empty title and description", () => {
    for (const s of SCENARIOS) {
      expect(s.title.length).toBeGreaterThan(10);
      expect(s.short_description.length).toBeGreaterThan(30);
    }
  });
});

describe("getScenario", () => {
  it("returns the matching scenario by id", () => {
    expect(getScenario("fraud-fp-burst")?.severity).toBe("P1");
    expect(getScenario("kyc-sanctions-hallucination")?.severity).toBe("P0");
    expect(getScenario("lending-latency-regression")?.severity).toBe("P2");
  });

  it("returns undefined for unknown id", () => {
    expect(getScenario("not-a-scenario")).toBeUndefined();
  });
});
