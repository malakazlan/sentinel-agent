import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useIncidentStream } from "@/lib/sse";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
  readyState = 0;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  emit(data: object) {
    if (this.onmessage) {
      this.onmessage.call(this as unknown as EventSource, { data: JSON.stringify(data) } as MessageEvent);
    }
  }

  emitOpen() {
    if (this.onopen) {
      this.onopen.call(this as unknown as EventSource, new Event("open"));
    }
  }

  emitError() {
    if (this.onerror) {
      this.onerror.call(this as unknown as EventSource, new Event("error"));
    }
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  // @ts-expect-error — replacing global
  global.EventSource = MockEventSource;
});

afterEach(() => {
  MockEventSource.instances = [];
});

describe("useIncidentStream", () => {
  it("starts in connecting state", () => {
    const { result } = renderHook(() => useIncidentStream("incident-1"));
    expect(result.current.status).toBe("connecting");
    expect(result.current.events).toEqual([]);
  });

  it("flips to open when onopen fires", () => {
    const { result } = renderHook(() => useIncidentStream("incident-1"));
    const source = MockEventSource.instances[0]!;
    act(() => source.emitOpen());
    expect(result.current.status).toBe("open");
  });

  it("accumulates events as they arrive", () => {
    const { result } = renderHook(() => useIncidentStream("incident-1"));
    const source = MockEventSource.instances[0]!;
    act(() => source.emitOpen());
    act(() =>
      source.emit({
        type: "incident_started",
        incident_id: "incident-1",
        elapsed_ms: 0,
        scenario_id: "fraud-fp-burst",
        severity: "P1",
        title: "x",
        watched_project: "fraud-detector-prod",
      })
    );
    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0]!.type).toBe("incident_started");
  });

  it("closes the source on incident_completed", () => {
    const { result } = renderHook(() => useIncidentStream("incident-1"));
    const source = MockEventSource.instances[0]!;
    act(() =>
      source.emit({
        type: "incident_completed",
        incident_id: "incident-1",
        elapsed_ms: 100,
        total_latency_ms: 100,
      })
    );
    expect(source.closed).toBe(true);
    expect(result.current.status).toBe("closed");
  });

  it("closes the source on incident_failed", () => {
    const { result } = renderHook(() => useIncidentStream("incident-1"));
    const source = MockEventSource.instances[0]!;
    act(() =>
      source.emit({
        type: "incident_failed",
        incident_id: "incident-1",
        elapsed_ms: 50,
        error: "boom",
      })
    );
    expect(source.closed).toBe(true);
    expect(result.current.status).toBe("closed");
  });

  it("cleans up the source on unmount", () => {
    const { unmount } = renderHook(() => useIncidentStream("incident-1"));
    const source = MockEventSource.instances[0]!;
    unmount();
    expect(source.closed).toBe(true);
  });

  it("opens a new source when incident_id changes", () => {
    const { rerender } = renderHook(({ id }: { id: string }) => useIncidentStream(id), {
      initialProps: { id: "incident-1" },
    });
    rerender({ id: "incident-2" });
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[0]!.closed).toBe(true);
    expect(MockEventSource.instances[1]!.url).toContain("incident-2");
  });

  it("does not connect when incident_id is null", () => {
    renderHook(() => useIncidentStream(null));
    expect(MockEventSource.instances).toHaveLength(0);
  });
});
