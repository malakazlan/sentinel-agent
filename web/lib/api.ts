import type { CreateIncidentResponse, IncidentResult } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok && res.status !== 202) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // body may not be JSON; fall through to statusText
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export async function createIncident(scenario_id: string): Promise<CreateIncidentResponse> {
  return fetchJson<CreateIncidentResponse>(`${API_BASE_URL}/incidents`, {
    method: "POST",
    body: JSON.stringify({ scenario_id }),
  });
}

export async function getIncident(incident_id: string): Promise<IncidentResult> {
  return fetchJson<IncidentResult>(`${API_BASE_URL}/incidents/${incident_id}`);
}

export function streamUrl(incident_id: string): string {
  return `${API_BASE_URL}/incidents/${incident_id}/stream`;
}
