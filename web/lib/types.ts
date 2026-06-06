/**
 * Wire schema mirror of sentinel/events.py.
 *
 * If the backend's event schema changes, this file MUST update in lockstep.
 * The unit tests in tests/unit/api/test_events.py and the contract doc at
 * docs/api-contract.md are the source of truth.
 */

export type Severity = "P0" | "P1" | "P2" | "P3";
export type StageName =
  | "investigate"
  | "eval_fanout"        // Phase 7 / ADR-012 — ParallelEvalRunner fan-out
  | "deploy_correlation" // Phase 7 / ADR-014 — GitHub MCP / DeployCorrelator
  | "root_cause"
  | "remediation"
  | "customer_impact"    // Phase 8 / ADR-018 — CustomerImpactQuantifier
  | "postmortem"
  | "compliance";        // Phase 8 / ADR-019 — ComplianceOfficer

export interface IncidentStartedEvent {
  type: "incident_started";
  incident_id: string;
  elapsed_ms: number;
  scenario_id: string;
  severity: Severity;
  title: string;
  watched_project: string;
}

/**
 * One past incident the briefing recalled (wire-compact shape).
 * Phase 7 / ADR-013. Mirrors sentinel.events.SimilarIncidentSummary.
 */
export interface SimilarIncidentSummary {
  incident_id: string;
  scenario_id: string;
  title: string;
  similarity: number;
}

/**
 * Coordinator's self-introspection briefing — emitted once per incident
 * before any agent stage runs. Carries the directives the Coordinator
 * will honor and the precedent list the UI renders.
 * Phase 7 / ADR-013.
 */
export interface BriefingResolvedEvent {
  type: "briefing_resolved";
  incident_id: string;
  elapsed_ms: number;
  cold_start: boolean;
  first_route: string | null;
  skip_routes: string[];
  must_eval_after: boolean;
  default_hours_back: number;
  similar_past_incidents: SimilarIncidentSummary[];
  evidence: Record<string, string>;
  stats: Record<string, number>;
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

/**
 * A prompt-evolution proposal — Phase 8 / ADR-020.
 * Emitted by the background routine after it scores variants.
 */
export interface PromptEvolvedEvent {
  type: "prompt_evolved";
  incident_id: string;
  elapsed_ms: number;
  target_agent: string;
  current_prompt_version: string;
  baseline_avg_score: number;
  winner_variant_id: string | null;
  winner_score: number | null;
  score_delta_over_baseline: number;
  promotion_recommended: boolean;
  decision_rationale: string;
}

/** SLO fast-burn / slow-burn alert — Phase 8 / ADR-024. */
export interface SLOBurnDetectedEvent {
  type: "slo_burn_detected";
  incident_id: string;
  elapsed_ms: number;
  slo_name: string;
  target: number;
  fast_burn_pct: number;
  slow_burn_pct: number;
  severity: string;
}

/** Human-approval gate awaiting decision — Phase 8 / ADR-025. */
export interface HumanGateAwaitingEvent {
  type: "human_gate_awaiting";
  incident_id: string;
  elapsed_ms: number;
  gate_id: string;
  action_type: string;
  action_summary: string;
  timeout_at_iso: string;
}

/** Human-approval gate resolved — Phase 8 / ADR-025. */
export interface HumanGateResolvedEvent {
  type: "human_gate_resolved";
  incident_id: string;
  elapsed_ms: number;
  gate_id: string;
  decision: string;
  operator_note: string;
}

export type IncidentEvent =
  | IncidentStartedEvent
  | BriefingResolvedEvent
  | SeedCompletedEvent
  | StageStartedEvent
  | StageCompletedEvent
  | PostmortemValidatedEvent
  | IncidentCompletedEvent
  | IncidentFailedEvent
  | PromptEvolvedEvent
  | SLOBurnDetectedEvent
  | HumanGateAwaitingEvent
  | HumanGateResolvedEvent;

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

/**
 * Provenance tag for an ImpactReport (Phase 8 / ADR-018).
 * Mirrors sentinel.agents.schemas.ImpactConfidence.
 */
export type ImpactConfidence = "seed_grounded" | "scenario_inferred" | "default_caveat";

/**
 * Quantified customer + financial impact, emitted by the
 * CustomerImpactQuantifier sub-agent between root_cause and postmortem
 * stages. Embedded under Postmortem.impact_quantified. Phase 8 / ADR-018.
 */
export interface ImpactReport {
  dollars_at_risk_usd: number;
  customers_affected: number;
  transactions_affected: number;
  estimated_revenue_loss_usd: number;
  customer_trust_score_delta: number;
  audit_citation_lines: string[];
  confidence: ImpactConfidence;
  caveats: string[];
}

/**
 * One regulator clause cited by the ComplianceOfficer (Phase 8 / ADR-019).
 * Every cite is grounded against the curated corpus; hallucinated cites
 * never reach the wire.
 */
export interface CitedClause {
  regulation_short_name: string;
  regulation_full_name: string;
  clause_id: string;
  clause_title: string;
  quoted_excerpt: string;
  source_url: string;
  applicability_rationale: string;
}

/**
 * One regulator notification this incident triggers (Phase 8 / ADR-019).
 */
export interface ReportingObligation {
  regulator: string;
  timeframe_days: number;
  triggered_by_clauses: string[];
  draft_notification_headline: string;
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
  // Phase 8 / ADR-018 — optional structured impact block (legacy
  // postmortems may omit it; UI gracefully falls back to the prose
  // `impact` field in that case).
  impact_quantified?: ImpactReport | null;
  // Phase 8 / ADR-019 — regulator exposure populated by the
  // ComplianceOfficer after the critic loop accepts the postmortem.
  // Empty arrays are valid (no specific regulation matched).
  regulatory_citations?: CitedClause[];
  reporting_obligations?: ReportingObligation[];
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
