import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createIncident, getIncident, streamUrl, ApiError } from "@/lib/api";

const originalFetch = global.fetch;

function mockFetch(response: { ok: boolean; status: number; statusText?: string; body?: unknown }) {
  global.fetch = vi.fn(async () => {
    return {
      ok: response.ok,
      status: response.status,
      statusText: response.statusText ?? "",
      json: async () => response.body,
    } as Response;
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("createIncident", () => {
  it("posts JSON body and returns the parsed response", async () => {
    mockFetch({
      ok: true,
      status: 201,
      body: {
        incident_id: "fraud-x-abc12345",
        scenario_id: "fraud-fp-burst",
        severity: "P1",
        title: "fraud",
        started_at: "2026-05-28T00:00:00Z",
      },
    });
    const result = await createIncident("fraud-fp-burst");
    expect(result.incident_id).toBe("fraud-x-abc12345");
    expect(result.severity).toBe("P1");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/incidents"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ scenario_id: "fraud-fp-burst" }),
      })
    );
  });

  it("throws ApiError with detail on 400", async () => {
    mockFetch({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      body: { detail: "Unknown scenario: not-a-real-scenario" },
    });
    await expect(createIncident("not-a-real-scenario")).rejects.toThrow(ApiError);
    await expect(createIncident("not-a-real-scenario")).rejects.toMatchObject({
      status: 400,
      message: expect.stringContaining("Unknown scenario"),
    });
  });
});

describe("getIncident", () => {
  it("returns the parsed completed result on 200", async () => {
    mockFetch({
      ok: true,
      status: 200,
      body: {
        incident_id: "x",
        scenario_id: "fraud-fp-burst",
        succeeded: true,
        total_latency_ms: 12345,
        postmortem: null,
        completeness: null,
        seed_summary: null,
      },
    });
    const result = await getIncident("x");
    expect("succeeded" in result && result.succeeded).toBe(true);
  });

  it("returns the running shape on 202 without throwing", async () => {
    mockFetch({
      ok: true,
      status: 202,
      body: { incident_id: "x", status: "running", scenario_id: "fraud-fp-burst" },
    });
    const result = await getIncident("x");
    expect("status" in result && result.status === "running").toBe(true);
  });

  it("propagates AbortSignal", async () => {
    const ac = new AbortController();
    mockFetch({ ok: true, status: 200, body: {} });
    await getIncident("x", ac.signal);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ signal: ac.signal })
    );
  });
});

describe("streamUrl", () => {
  it("returns the correct SSE endpoint URL", () => {
    expect(streamUrl("abc")).toContain("/incidents/abc/stream");
  });
});
