"use client";

import { useEffect, useState } from "react";
import type { IncidentEvent } from "@/lib/types";
import { streamUrl } from "@/lib/api";

export type IncidentStreamStatus = "connecting" | "open" | "closed" | "error";

export interface IncidentStreamState {
  events: IncidentEvent[];
  status: IncidentStreamStatus;
  error: string | null;
}

/**
 * Subscribe to /incidents/{id}/stream via EventSource.
 *
 * - Auto-cleans up on unmount or incident_id change
 * - Closes the stream when an incident_completed or incident_failed event
 *   is received (matches backend contract; native EventSource would
 *   reconnect on close otherwise)
 */
export function useIncidentStream(incident_id: string | null): IncidentStreamState {
  const [state, setState] = useState<IncidentStreamState>({
    events: [],
    status: "connecting",
    error: null,
  });

  useEffect(() => {
    if (!incident_id) return;

    setState({ events: [], status: "connecting", error: null });
    const source = new EventSource(streamUrl(incident_id));

    source.onopen = () => {
      setState((prev) => ({ ...prev, status: "open" }));
    };

    source.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as IncidentEvent;
        setState((prev) => {
          const events = [...prev.events, event];
          const isTerminal = event.type === "incident_completed" || event.type === "incident_failed";
          if (isTerminal) source.close();
          return {
            ...prev,
            events,
            status: isTerminal ? "closed" : prev.status,
          };
        });
      } catch (err) {
        setState((prev) => ({
          ...prev,
          status: "error",
          error: `Failed to parse SSE event: ${err instanceof Error ? err.message : String(err)}`,
        }));
      }
    };

    source.onerror = () => {
      setState((prev) => {
        // EventSource fires onerror on normal close too. Only escalate if we
        // haven't already received a terminal event.
        if (prev.status === "closed") return prev;
        source.close();
        return { ...prev, status: "error", error: "SSE connection error" };
      });
    };

    return () => {
      source.close();
    };
  }, [incident_id]);

  return state;
}
