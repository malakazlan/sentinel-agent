/**
 * Wire schema mirror of sentinel/events.py.
 *
 * If the backend's event schema changes, this file MUST update in lockstep.
 * The unit tests in tests/unit/api/test_events.py and the contract doc at
 * docs/api-contract.md are the source of truth.
 */

export type Severity = "P0" | "P1" | "P2" | "P3";
export type StageName = "investigate" | "root_cause" | "remediation" | "postmortem";

export interface IncidentStartedEvent {
  type: "incident_started";
  incident_id: string;
  elapsed_ms: number;
  scenario_id: string;
  severity: Severity;
  title: string;
  watched_project: string;
}

export interface SeedCompletedEvent {
  type: "seed_completed";
  incident_id: string;
  elapsed_ms: number;
  project: string;
  spans_written: number;
  n_ok: number;
  n_error: number;
}

export interface StageStartedEvent {
  type: "stage_started";
  incident_id: string;
  elapsed_ms: number;
  stage: StageName;
  prompt_preview: string;
}

export interface StageCompletedEvent {
  type: "stage_completed";
  incident_id: string;
  elapsed_ms: number;
  stage: StageName;
  latency_ms: number;
  authors: string[];
  final_text: string;
}

export interface PostmortemValidatedEvent {
  type: "postmortem_validated";
  incident_id: string;
  elapsed_ms: number;
  completeness_score: number;
  completeness_label: string;
  postmortem_json: string;
}

export interface IncidentCompletedEvent {
  type: "incident_completed";
  incident_id: string;
  elapsed_ms: number;
  total_latency_ms: number;
}

export interface IncidentFailedEvent {
  type: "incident_failed";
  incident_id: string;
  elapsed_ms: number;
  error: string;
}

export type IncidentEvent =
  | IncidentStartedEvent
  | SeedCompletedEvent
  | StageStartedEvent
  | StageCompletedEvent
  | PostmortemValidatedEvent
  | IncidentCompletedEvent
  | IncidentFailedEvent;

// ── REST response shapes ──────────────────────────────────────────────────

export interface CreateIncidentResponse {
  incident_id: string;
  scenario_id: string;
  severity: Severity;
  title: string;
  started_at: string;
}

export interface ActionItem {
  description: string;
  owner_role: string;
  severity: Severity;
  due_within_days: number;
}

export interface Postmortem {
  title: string;
  incident_id: string;
  severity: Severity;
  summary: string;
  impact: string;
  timeline: string[];
  root_cause: string;
  detection: string;
  resolution: string;
  action_items: ActionItem[];
  lessons_learned: string[];
}

export interface SeedSummary {
  project: string;
  spans_written: number;
  n_ok: number;
  n_error: number;
}

export interface CompletenessReport {
  score: number;
  label: string;
}

export interface IncidentResultCompleted {
  incident_id: string;
  scenario_id: string;
  succeeded: true;
  total_latency_ms: number;
  postmortem: Postmortem | null;
  completeness: CompletenessReport | null;
  seed_summary: SeedSummary | null;
}

export interface IncidentResultFailed {
  incident_id: string;
  succeeded: false;
  error: string;
}

export interface IncidentResultRunning {
  incident_id: string;
  status: "running";
  scenario_id: string;
}

export type IncidentResult =
  | IncidentResultCompleted
  | IncidentResultFailed
  | IncidentResultRunning;
