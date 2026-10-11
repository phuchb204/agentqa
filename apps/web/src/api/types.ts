export interface Entity {
  id: string;
  logical_key: string;
}

export interface Workspace {
  id: string;
  slug: string;
  name: string;
}

export interface Membership {
  user_id: string;
  role: string;
  permission_flags: string[];
}

export interface SessionInfo {
  user_id: string;
  username: string;
}

export interface Revision {
  revision_id: string;
  entity_id: string;
  revision_no: number;
  content: Record<string, unknown>;
  content_digest: string;
  lifecycle: string;
  author: string;
  promoted_by?: string | null;
  promoted_at?: string | null;
  supersedes?: string | null;
  archived_at?: string | null;
}

export interface Draft {
  entity_id: string;
  edit_version: number;
  content: Record<string, unknown>;
  updated_by: string;
  updated_at: string;
}

export interface Promotion {
  revision_id: string;
  entity_id: string;
  revision_no: number;
  content_digest: string;
  promoted_by: string;
  promoted_at: string;
  supersedes?: string | null;
}

export interface ImpactLink {
  case_id: string;
  logical_key: string;
  case_revision_id: string;
  revision_no: number;
  needs_review: boolean;
  source_names: string[];
  affected_assertions: string[];
  affected_nodes: string[];
  review_marked_at: string | null;
}

export interface Impact {
  requirement_id: string;
  logical_key: string;
  latest_revision_no: number | null;
  links: ImpactLink[];
}

export interface SourceRevision {
  revision_id: string;
  source_id: string;
  logical_key: string;
  revision_no: number;
  filename: string;
  media_type: string;
  size_bytes: number;
  file_digest: string;
  privacy_class: string;
  state: string;
  unextractable_reason: string | null;
  created_at: string;
  segment_count: number;
}

export interface SourceSegment {
  ordinal: number;
  anchor: Record<string, unknown>;
  text: string;
  text_digest: string;
  privacy: string;
}

export interface SourceDetail {
  revision: SourceRevision;
  segments: SourceSegment[];
}

export interface ProposalProvenance {
  path: string;
  source: string;
  ref?: string | null;
}

export interface Proposal {
  proposal_id: string;
  job_id: string;
  title: string;
  case_kind: string;
  requirement_keys: string[];
  content: Record<string, unknown>;
  provenance: ProposalProvenance[];
  status: string;
  rejection_reason: string | null;
}

export interface AuthoringJob {
  job_id: string;
  kind: string;
  state: string;
  model_requested: string | null;
  error_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  proposals: Proposal[];
}

export interface DiffEntry {
  op: string;
  node_id?: string;
  name?: string;
  field?: string;
  kind?: string;
  before?: unknown;
  after?: unknown;
  provenance?: string;
  assertions_added?: string[];
  assertions_removed?: string[];
  assertions_changed?: string[];
}

export interface ApplyResult {
  proposal_id: string;
  case_id: string;
  edit_version: number;
  content: Record<string, unknown>;
  diff: DiffEntry[];
}

export interface DraftRun {
  run_id: string;
  snapshot_digest: string;
  provisional: boolean;
  blocked: boolean;
  planned_executions: number;
}

export interface BindExecution {
  execution_key: string;
  case_logical_key: string;
  case_revision_id: string | null;
  dataset_row_index: number | null;
  parameters: Record<string, unknown>;
}

export interface BindResult {
  suite_revision_id: string;
  suite_logical_key: string;
  fixture_refs: string[];
  executions: BindExecution[];
  facts: string[];
}

export interface CredentialReferenceSummary {
  credential_ref: string;
  version: number;
  kind: string;
  status: string;
  algorithm: string | null;
  rotated_from: string | null;
}

export interface CredentialVersionInfo {
  credential_ref: string;
  version: number;
  status: string;
}

export interface CredentialRevokeInfo {
  credential_ref: string;
  revoked_versions: number;
}

export interface ScheduleRevisionSummary {
  revision_id: string;
  revision_no: number;
  content: Record<string, unknown>;
}

export interface ScheduleSummary {
  schedule_id: string;
  logical_key: string;
  enabled: boolean;
  latest_revision: ScheduleRevisionSummary | null;
}

export interface ScheduleOccurrence {
  occurrence_id: string;
  schedule_id: string;
  schedule_revision_id: string;
  occurrence_key: string;
  local_wall_time: string;
  scheduled_at: string | null;
  fold: number;
  state: string;
  reason: string | null;
  run_id: string | null;
}

export interface FieldError {
  path: (string | number)[];
  code: string;
  message: string;
}

export interface RunListItem {
  run_id: string;
  status: string;
  verdict: string | null;
  gate: string | null;
  annotations: string[];
  reasons: string[];
  policy: string | null;
  observation_mode: string | null;
  environment_revision_id: string | null;
  created_at: string;
  finalized_at: string | null;
  executions: {
    execution_id: string;
    logical_key: string;
    status: string;
    verdict: string | null;
  }[];
}

export interface RunList {
  items: RunListItem[];
  next_cursor: string | null;
  total: number;
}

export interface AssertionDetail {
  checkpoint_id: string;
  assertion_id: string;
  result: string;
  proof: Record<string, unknown>;
}

export interface ExecutionDetail {
  execution_id: string;
  logical_key: string;
  status: string;
  verdict: string | null;
  assertions: AssertionDetail[];
}

export interface ArtifactSummary {
  artifact_id: string;
  kind: string;
  state: string;
  media_type: string | null;
  digest: string | null;
  redacted: boolean;
  unavailable_reason: string | null;
}

export interface RunDetail {
  run_id: string;
  status: string;
  verdict: string | null;
  gate: string | null;
  reasons: string[];
  annotations: string[];
  terminal: boolean;
  snapshot: {
    policy: string | null;
    observation_mode: string | null;
    gate_profile: string | null;
    cache_profile: string | null;
    calibration_ref: string | null;
    budgets: Record<string, number> | null;
    content_digests: string[];
    environment_revision: string | null;
    provisional: boolean;
  };
  executions: ExecutionDetail[];
  controls: {
    control_id: string;
    action: string;
    requested_at: string;
    effective_at: string | null;
    effective_reason: string | null;
  }[];
  artifacts: ArtifactSummary[];
  usage: {
    state: string;
    input_tokens: number;
    output_tokens: number;
    settled_calls: number;
    unknown_calls: number;
    cost_state: string;
    cost_total: string | null;
    cost_currency: string | null;
  };
}

export interface ComparisonAssertion {
  checkpoint_id: string;
  assertion_id: string;
  aligned: boolean;
  a_status: string | null;
  b_status: string | null;
  a_expected: string | null;
  b_expected: string | null;
  a_observed: string | null;
  b_observed: string | null;
}

export interface Alignment {
  logical_key: string;
  aligned: boolean;
  reason: string | null;
  a_status: string | null;
  b_status: string | null;
  a_verdict: string | null;
  b_verdict: string | null;
  assertions: ComparisonAssertion[];
}

export interface RunComparison {
  run_a: string;
  run_b: string;
  config_diff: { field: string; a: unknown; b: unknown; equal: boolean }[];
  metrics: Record<
    string,
    {
      verdict: string | null;
      status: string;
      gate: string | null;
      usage_state: string;
      usage_input_tokens: number;
      usage_output_tokens: number;
      cost_state: string;
      cost_total: string | null;
      cost_currency: string | null;
    }
  >;
  alignment: Alignment[];
}

export interface RunState {
  run_id: string;
  status: string;
  verdict: string | null;
  gate: string | null;
  reasons: string[];
  snapshot_digest: string | null;
  last_run_seq: number;
  executions: {
    execution_id: string;
    logical_key: string;
    status: string;
    verdict: string | null;
  }[];
  controls: {
    control_id: string;
    action: string;
    requested_at: string;
    effective_at: string | null;
    effective_reason: string | null;
  }[];
}

export interface RunEventView {
  event_id: string;
  run_seq: number;
  execution_id: string | null;
  execution_seq: number | null;
  type: string;
}

export interface ReportSummary {
  report_id: string;
  run_id: string;
  format: string;
  artifact_id: string;
  digest: string | null;
  media_type: string;
  created_at: string;
}

export interface DiagnosticSummary {
  diagnostic_id: string;
  run_id: string;
  state: string;
  label: string;
  explanation: string | null;
  confidence: string | null;
  evidence_refs: string[];
  model_call_id: string | null;
  created_at: string;
}

export interface IssuePackageSummary {
  package_id: string;
  run_id: string;
  artifact_id: string;
  digest: string | null;
  preview: Record<string, unknown>;
  created_at: string;
}

export interface HealingRecord {
  record_id: string;
  run_id: string;
  execution_id: string | null;
  attempt_id: string | null;
  actor: "action" | "evidence";
  node_id: string;
  opportunity_id: string;
  attempt_ref: string;
  decision: "recovered" | "refused";
  ranking: Record<string, unknown> | null;
  expected_signature: string | null;
  actual_signature: string | null;
  original_target: Record<string, unknown> | null;
  actual_target: Record<string, unknown> | null;
  dispatch_outcome: string | null;
  guard_checks: string[];
  postconditions_ok: boolean | null;
  refusal_reason: string | null;
  error: string | null;
  proposal: {
    node_id: string;
    intent: string;
    proposed: Record<string, unknown>;
    locator: { kind: string; value: string } | null;
    source_run_id: string | null;
  } | null;
  source_run_id: string | null;
  case_id: string | null;
  case_revision_id: string | null;
  recorded_at: string;
}

export interface ErrorShape {
  code: string;
  message: string;
  field_errors?: FieldError[];
}

export interface ExperimentRevision {
  revision_id: string;
  experiment_id: string;
  logical_key: string;
  revision_no: number;
  content_digest: string;
}

export interface ExperimentRevisionList {
  items: ExperimentRevision[];
}

export interface ExperimentExecuteSummary {
  revision_id: string;
  attempt_no: number;
  slots: number;
  completed: number;
  blocked: number;
  errors: number;
}

export interface ExperimentSlot {
  slot_key: string;
  arm_id: string;
  case_key: string;
  variant_token: string | null;
  data_row: string | null;
  repetition: number;
  attempt_no: number;
  status: "scheduled" | "running" | "completed" | "blocked" | "error";
  blocked_reason: string | null;
  run_id: string | null;
  scoring_id: string | null;
  payload: Record<string, unknown>;
}

export interface ExperimentAnalysisArm {
  slots_total: number;
  valid_scheduled: number;
  completed: number;
  blocked: number;
  errors: number;
  product_pass_rate: number | null;
  oracle: {
    known_true: number;
    known_false: number;
    unscorable: number;
    success_lower_bound: number | null;
    success_upper_bound: number | null;
    coverage: number | null;
    unscorable_ratio: number | null;
  };
  detection: {
    detected: number;
    missed: number;
    detection_ratio: number | null;
    not_applicable: boolean;
  };
  healing: {
    attempts: number;
    correct_heals: number;
    false_heals: number;
    refusals: number;
  };
  false_passes: number;
  usage: { calls: number; input_tokens: number; output_tokens: number; wall_time_seconds: number };
  confounds: {
    unverified_model_alias: string[];
    provider_cache_observed: boolean;
    cost_basis_mixed: boolean;
    cost_bases: string[];
  };
}

export interface ExperimentAnalysis {
  arms: Record<string, ExperimentAnalysisArm>;
  comparisons: Array<{
    left: string;
    right: string;
    pairs: number;
    estimate: number | null;
    lower: number | null;
    upper: number | null;
    sufficient_support: boolean;
    non_inferior?: boolean | null;
    non_inferiority_margin?: number;
  }>;
  metric_definitions: Record<string, string>;
  seeds: number[];
  charts: {
    oracle_success: Array<{ arm: string; lower: number | null; upper: number | null }>;
    false_heals: Array<{ arm: string; false_heals: number }>;
    wall_time: Array<{ arm: string; wall_time_seconds: number }>;
  };
}

export interface ExperimentResults {
  revision_id: string;
  content_digest: string;
  manifest: Record<string, unknown>;
  slots: ExperimentSlot[];
  analysis: ExperimentAnalysis;
}
