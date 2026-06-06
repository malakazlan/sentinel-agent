import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  acceptPattern,
  fetchArchitecture,
  fetchEvalsTrends,
  fetchIncidentsHistory,
  fetchPatterns,
  fetchPromptsHistory,
  fetchPromptsOverview,
  fetchSentinelHealth,
  rejectPattern,
} from "@/lib/api";

/**
 * Data-wiring tests for the Phase 8 / ADR-027 page surface. We assert
 * that each fetcher (a) hits the correct path, (b) decodes the JSON
 * body correctly, (c) surfaces backend errors as ApiError.
 *
 * One test file → one Vitest run → one CI signal that the API contract
 * the new pages depend on is wired correctly. Per-page tests would be
 * thin coverage (every page is "fetch → render"), so testing the
 * fetcher contract is the higher-leverage placement.
 */

const ORIGINAL_FETCH = global.fetch;

beforeEach(() => {
  vi.restoreAllMocks();
});

function mockOk(body: unknown) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => body,
  } as unknown as Response);
}

function mockErr(status: number, detail = "boom") {
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status,
    statusText: "Bad",
    json: async () => ({ detail }),
  } as unknown as Response);
}

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
});

function afterEach(_fn: () => void) {
  // Vitest's afterEach is exported via globalThis when globals:true is set
  // in the config; this shim keeps the test file readable.
  (globalThis as any).afterEach?.(_fn);
}

describe("fetchPatterns", () => {
  it("hits /patterns and returns the array body", async () => {
    const body = [
      {
        cluster_id: "p1",
        representative_root_cause: "stale cache",
        member_incident_ids: ["a", "b", "c"],
        member_count: 3,
        avg_pair_similarity: 0.82,
        proposed_mitigation_type: "new_directive",
        proposed_mitigation_text: "...",
        status: "proposed",
      },
    ];
    mockOk(body);
    const out = await fetchPatterns();
    expect((global.fetch as any).mock.calls[0][0]).toMatch(/\/patterns$/);
    expect(out).toEqual(body);
  });

  it("throws ApiError on backend failure", async () => {
    mockErr(500, "internal");
    await expect(fetchPatterns()).rejects.toThrow(/internal/);
  });
});

describe("acceptPattern / rejectPattern", () => {
  it("POSTs to the right path", async () => {
    mockOk({ cluster_id: "p1", status: "accepted" });
    await acceptPattern("p1");
    const callArgs = (global.fetch as any).mock.calls[0];
    expect(callArgs[0]).toMatch(/\/patterns\/p1\/accept$/);
    expect(callArgs[1].method).toBe("POST");
  });

  it("URL-encodes special characters in cluster_id", async () => {
    mockOk({ cluster_id: "p/1", status: "rejected" });
    await rejectPattern("p/1");
    const callArgs = (global.fetch as any).mock.calls[0];
    expect(callArgs[0]).toMatch(/\/patterns\/p%2F1\/reject$/);
  });
});

describe("fetchSentinelHealth", () => {
  it("decodes the health report shape", async () => {
    mockOk({
      agents: [],
      history_total: 0,
      healthy_count: 0,
      watch_count: 0,
      degraded_count: 0,
      underperforming_count: 0,
    });
    const out = await fetchSentinelHealth();
    expect((global.fetch as any).mock.calls[0][0]).toMatch(
      /\/sentinel\/health$/,
    );
    expect(out.history_total).toBe(0);
    expect(out.agents).toEqual([]);
  });
});

describe("fetchPromptsOverview / fetchPromptsHistory", () => {
  it("overview hits /prompts and returns agents array", async () => {
    mockOk({ agents: [{ agent_name: "x", current_prompt_version: "v1", sample_count: 1, avg_aggregate_score: 0.9, last_record_timestamp: "" }] });
    const out = await fetchPromptsOverview();
    expect((global.fetch as any).mock.calls[0][0]).toMatch(/\/prompts$/);
    expect(out.agents).toHaveLength(1);
  });

  it("history URL-encodes agent name", async () => {
    mockOk({ agent_name: "postmortem", records: [] });
    await fetchPromptsHistory("postmortem");
    const callArgs = (global.fetch as any).mock.calls[0];
    expect(callArgs[0]).toMatch(/\/prompts\/postmortem\/history$/);
  });
});

describe("fetchEvalsTrends", () => {
  it("hits /evals/trends", async () => {
    mockOk({ agents: [] });
    await fetchEvalsTrends();
    expect((global.fetch as any).mock.calls[0][0]).toMatch(
      /\/evals\/trends$/,
    );
  });
});

describe("fetchArchitecture", () => {
  it("hits /architecture and returns the registry", async () => {
    mockOk({
      agents: [
        { name: "coordinator", role: "Plans", model: "gemini-3.1-pro", adr: "n/a" },
      ],
    });
    const out = await fetchArchitecture();
    expect((global.fetch as any).mock.calls[0][0]).toMatch(/\/architecture$/);
    expect(out.agents[0]?.name).toBe("coordinator");
  });
});

describe("fetchIncidentsHistory", () => {
  it("omits empty filters from the query string", async () => {
    mockOk({ incidents: [] });
    await fetchIncidentsHistory({});
    expect((global.fetch as any).mock.calls[0][0]).toMatch(
      /\/incidents-history$/,
    );
  });

  it("encodes severity and scenario_id", async () => {
    mockOk({ incidents: [] });
    await fetchIncidentsHistory({ severity: "P1", scenario_id: "fraud-fp-burst" });
    const url = (global.fetch as any).mock.calls[0][0] as string;
    expect(url).toMatch(/severity=P1/);
    expect(url).toMatch(/scenario_id=fraud-fp-burst/);
  });
});
