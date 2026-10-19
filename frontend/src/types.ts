export type ResultStatus = "passed" | "finding" | "failed" | "inconclusive";
export type RunStatus = ResultStatus | "findings" | "running";

export interface Run {
  id: number; started_at: string; completed_at: string | null; status: RunStatus; demo_mode: string;
  total_tests: number; passed_count: number; finding_count: number; failed_count: number; inconclusive_count: number;
  error_summary: string | null; results?: Result[];
}
export interface Result {
  id: number; run_id: number; test_case_key: string; test_name: string; requesting_tenant_id: string;
  resource_id: string | null; endpoint: string; expected_outcome: string; actual_status_code: number | null;
  observed_outcome: string; result_status: ResultStatus; finding_id: number | null; duration_ms: number; evidence: any;
}
export interface RegRun {
  id: number; run_at: string; demo_mode: string; result_status: ResultStatus; actual_status_code: number | null;
  observed_outcome: string; duration_ms: number; evidence: any;
}
export interface RegTest {
  id: number; name: string; source_finding_id: number; endpoint: string; expected_policy: string; definition: any;
  created_at: string; last_run_at: string | null; last_result_status: ResultStatus | null; runs?: RegRun[];
}
export interface Finding {
  id: number; title: string; severity: string; endpoint: string; requesting_tenant_id: string;
  resource_owner_tenant_id: string | null; resource_id: string | null; expected_behavior: string;
  actual_behavior: string; first_detected_run_id: number; created_at: string;
  regression_test_id: number | null; regression_status: string;
  evidence?: any; requesting_tenant_name?: string; resource_owner_tenant_name?: string;
  remediation?: string; first_detected_demo_mode?: string; regression?: RegTest | null;
  occurrence_count: number; last_detected_at: string;
  original?: { run_id: number; detected_at: string; demo_mode: string; evidence: any };
  latest_occurrence?: Occurrence | null; occurrences?: Occurrence[];
  latest_regression_result?: { status: ResultStatus; run_at: string; regression_test_id: number } | null;
  regression_history?: (RegRun & { regression_test_id: number; test_name: string; test_deleted: boolean })[];
}
export interface Occurrence {
  id: number; source: "suite" | "regression"; run_id: number | null; regression_run_id: number | null;
  detected_at: string; demo_mode: string; evidence?: any;
}
export interface DemoStatus { reachable: boolean; mode: string; dev_controls_enabled: boolean; vulnerable_demo_enabled: boolean }
export interface Tenant {
  id: string; name: string; marker: string; users: { user_id: string; display_name: string }[];
  documents: { id: string; title: string }[];
}
export interface Activity { at: string; text: string; status: string }
