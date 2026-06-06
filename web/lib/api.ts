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
  if (!res.ok) {
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

export async function getIncident(incident_id: string, signal?: AbortSignal): Promise<IncidentResult> {
  return fetchJson<IncidentResult>(
    `${API_BASE_URL}/incidents/${incident_id}`,
    signal ? { signal } : undefined
  );
}

export function streamUrl(incident_id: string): string {
  return `${API_BASE_URL}/incidents/${incident_id}/stream`;
}


// ── Phase 8 / ADR-027 — read-only fetchers for the new pages ─────────────


async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return fetchJson<T>(`${API_BASE_URL}${path}`, signal ? { signal } : undefined);
}

async function post<T>(path: string): Promise<T> {
  return fetchJson<T>(`${API_BASE_URL}${path}`, { method: "POST" });
}

export interface PatternProposalDto {
  cluster_id: string;
  representative_root_cause: string;
  member_incident_ids: string[];
  member_count: number;
  avg_pair_similarity: number;
  proposed_mitigation_type: string;
  proposed_mitigation_text: string;
  status: string;
}

export const fetchPatterns = (signal?: AbortSignal) =>
  get<PatternProposalDto[]>("/patterns", signal);
export const acceptPattern = (cluster_id: string) =>
  post<{ cluster_id: string; status: string }>(
    `/patterns/${encodeURIComponent(cluster_id)}/accept`,
  );
export const rejectPattern = (cluster_id: string) =>
  post<{ cluster_id: string; status: string }>(
    `/patterns/${encodeURIComponent(cluster_id)}/reject`,
  );

export interface SentinelHealthAgent {
  agent_name: string;
  sample_count: number;
  avg_aggregate_score: number;
  avg_rubric_scores: Record<string, number>;
  trend_slope: number;
  health_flag: string;
  last_record_timestamp: string;
  insufficient_history: boolean;
}
export interface SentinelHealthReport {
  agents: SentinelHealthAgent[];
  history_total: number;
  healthy_count: number;
  watch_count: number;
  degraded_count: number;
  underperforming_count: number;
}
export const fetchSentinelHealth = (signal?: AbortSignal) =>
  get<SentinelHealthReport>("/sentinel/health", signal);

export interface PromptRollup {
  agent_name: string;
  current_prompt_version: string;
  sample_count: number;
  avg_aggregate_score: number;
  last_record_timestamp: string;
}
export const fetchPromptsOverview = (signal?: AbortSignal) =>
  get<{ agents: PromptRollup[] }>("/prompts", signal);

export interface PromptHistoryRecord {
  agent_name: string;
  prompt_version: string;
  prompt_hash: string;
  incident_id: string;
  scenario_id: string;
  aggregate_critic_score: number;
  rubric_scores: Record<string, number>;
  timestamp_iso: string;
}
export const fetchPromptsHistory = (agent_name: string, signal?: AbortSignal) =>
  get<{ agent_name: string; records: PromptHistoryRecord[] }>(
    `/prompts/${encodeURIComponent(agent_name)}/history`,
    signal,
  );

export interface EvalTrendAgent {
  agent_name: string;
  point_count: number;
  avg_aggregate: number;
  avg_rubric: Record<string, number>;
  points: Array<{
    timestamp_iso: string;
    aggregate: number;
    rubric_scores: Record<string, number>;
  }>;
}
export const fetchEvalsTrends = (signal?: AbortSignal) =>
  get<{ agents: EvalTrendAgent[] }>("/evals/trends", signal);

export interface ArchitectureAgent {
  name: string;
  role: string;
  model: string;
  adr: string;
}
export const fetchArchitecture = (signal?: AbortSignal) =>
  get<{ agents: ArchitectureAgent[] }>("/architecture", signal);

export interface PastIncident {
  incident_id: string | null;
  scenario_id: string | null;
  title: string | null;
  severity: string | null;
  completeness_score: number | null;
  timestamp_iso: string | null;
}
export const fetchIncidentsHistory = (
  filters: { severity?: string; scenario_id?: string },
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams();
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.scenario_id) params.set("scenario_id", filters.scenario_id);
  const q = params.toString();
  return get<{ incidents: PastIncident[] }>(
    `/incidents-history${q ? "?" + q : ""}`,
    signal,
  );
};
