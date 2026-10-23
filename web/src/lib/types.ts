// Response shapes for the ATLAS API. Request bodies are generated from OpenAPI
// (api-schema.ts); responses are typed here for the fields the UI reads. The server
// side of each shape is pinned by tests/test_api.py.

export type Evidence = "Observed" | "Attributed" | "Modeled" | "Experimental" | "Simulated" | "Assumption";

export interface Provenance {
  evidence_type: Evidence | string;
  run_id?: string;
  source_tables?: string[];
  note?: string;
}

export interface MetricResponse {
  metric: { name: string; label: string; format: string; definition: string; caveats: string[] };
  window: [string, string] | null;
  rows: Array<Record<string, string | number | null> & { value: number | null }>;
  provenance: Provenance;
}

export interface Quantiles {
  mean: number;
  p10: number;
  p50: number;
  p90: number;
}

export interface Estimate {
  channel: string;
  method: string;
  roi_mean: number;
  roi_p05: number | null;
  roi_p95: number | null;
  true_roi?: number;
  abs_error?: number;
  covered90?: boolean | null;
}

export interface Diagnostics {
  rhat_max: number;
  ess_bulk_min: number;
  divergences: number;
  converged: boolean;
  chains: number;
  draws_total: number;
  train?: { mape: number; r2: number; coverage90: number };
  holdout?: {
    mape: number;
    coverage90: number;
    baseline_mape_trailing13: number;
    baseline_mape_seasonal_naive: number;
  };
}

export interface MeasurementResponse {
  estimates: Estimate[];
  diagnostics: Record<string, Diagnostics>;
  holdout: Record<string, Diagnostics & { mape?: number }>;
  attribution: Array<{
    method: string;
    channel: string;
    conversions: number;
    revenue: number;
    spend: number | null;
    roas: number | null;
  }>;
  geolift: {
    channel: string;
    holdout: string[];
    test_weeks: number;
    delta_y: number;
    se: number;
    ci90: [number, number];
    p_value: number;
    true_delta_y?: number;
  };
  recommended_variant: string;
  mmm_runs: Record<string, string>;
  truth?: Array<{ channel: string; label: string; true_roi_first_order_billed: number; spend_policy: string }>;
  graded?: {
    objective: string;
    true_value_optimum: number;
    plans: Record<string, { true_value: number; regret: number }>;
  };
  provenance: Provenance;
}

export interface ScorecardResponse {
  n_worlds: number;
  regimes: Record<string, number>;
  roi_by_method: Array<{
    method: string;
    mean_abs_error: number;
    median_abs_error: number;
    mean_rel_error: number;
    coverage90: number | null;
  }>;
  regret_by_plan: Array<{
    plan: string;
    mean_regret: number;
    median_regret: number;
    p90_regret: number;
    median_regret_share: number;
    worse_than_current: number;
  }>;
  convergence: Array<{ variant: string; converged: number; rhat_max_median: number; divergent_fits: number }>;
  geolift: { coverage90: number; mean_abs_error: number; mean_se: number };
  calibration_effect_on_tested_channel: { mean_error_before: number; mean_error_after: number; share_improved: number };
  failures: Array<{ seed: number; regime: string; what: string; regret: number; regret_current: number }>;
  failed_worlds: number[];
  config: { seeds: number[]; draws: number; tune: number; chains: number };
  provenance: Provenance;
}

export interface ChannelPlan {
  channel: string;
  current: number;
  proposed: number;
  min: number;
  max: number;
  observed_weekly_min: number;
  observed_weekly_max: number;
  outside_observed_range: boolean;
  mroi_current: Quantiles;
  mroi_proposed: Quantiles;
  incremental_revenue_proposed: Quantiles;
}

export interface OptimizationResult {
  run_id: string;
  objective: string;
  budget: number;
  spend_all: boolean;
  economics: { cm_rate: number; repeat_multiplier: number };
  channels: ChannelPlan[];
  outcome_current: Record<string, Quantiles>;
  outcome_proposed: Record<string, Quantiles>;
  uplift: Record<string, Quantiles>;
  prob_proposed_beats_current: number;
  break_even_mroi: number | null;
  n_draws: number;
  explanation: string;
  assumptions_overridden?: string[];
  provenance?: Provenance;
}

export interface PlanResponse {
  budget: number;
  objective: string;
  economics: { cm_rate: number; repeat_multiplier: number };
  current: Record<string, number>;
  constraints: { budget: number; mins: Record<string, number>; maxs: Record<string, number> };
  optimizer: Record<string, OptimizationResult>;
  tornado: Array<{
    assumption: string;
    key: string;
    low_delta: number;
    high_delta: number;
    low_budget_moved: number;
    high_budget_moved: number;
  }>;
  provenance: Provenance;
}

export interface ExperimentOption {
  channel: string;
  evsi: number;
  evsi_mc_se: number;
  n_weeks: number;
  holdout_label?: string;
  expected_test_cost: number;
  net_value: number;
  power_at_predicted_effect: number;
  predicted_effect_mean: number;
  expected_budget_moved: number;
}

export interface ExperimentsResponse {
  next_experiments: ExperimentOption[];
  evpi: number;
  provenance: Provenance;
}

export interface Hypothesis {
  title: string;
  status: "Confirmed" | "Supported hypothesis" | "Unverified" | string;
  evidence: string[];
  follow_ups: string[];
  score: number;
}

export interface AnomalyWeek {
  week: string;
  flagged_series: Record<string, number>;
  hypotheses: Hypothesis[];
}

export interface HaldenAnomaliesResponse {
  thresholds: Record<string, number>;
  fpr_target: number;
  evaluation: {
    precision: number;
    recall: number;
    alert_events: number;
    incidents: number;
    recall_by_kind: Array<{ kind: string; recall: number; n: number }>;
  };
  weeks: AnomalyWeek[];
  national_series: Array<{ period: string; metric: string; actual: number; expected: number; z: number }>;
  provenance: Provenance;
}

export interface Ga4AnomaliesResponse {
  threshold: number;
  alerts: Array<{ period: string; series: string; z: number; actual: number; expected: number }>;
  late_january: {
    start: string;
    conclusion: string;
    evidence_status: string;
    status_note: string;
    ratios: Record<string, { before: number; after: number }>;
    comparison: Record<string, { before_per_day: number; after_per_day: number; change_pct: number }>;
    follow_ups: string[];
  };
  provenance: Provenance;
}

export interface RowsResponse<T = Record<string, unknown>> {
  rows: T[];
  provenance: Provenance;
}
