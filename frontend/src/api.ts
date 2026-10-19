import type { Activity, DemoStatus, Finding, RegRun, RegTest, Run, Tenant } from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method, headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Cannot reach the TENANTSHIELD backend. Start it and reload.", 0);
  }
  const json = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(json?.error?.message ?? `Request failed (${res.status})`, res.status);
  return json.data as T;
}

export const api = {
  demoStatus: () => req<DemoStatus>("GET", "/api/demo/status"),
  tenants: () => req<Tenant[]>("GET", "/api/demo/tenants"),
  setMode: (mode: "vulnerable" | "fixed") => req<{ mode: string }>("POST", "/api/demo/dev/mode", { mode }),
  resetDemo: () => req<unknown>("POST", "/api/demo/dev/reset"),
  resetHistory: () => req<unknown>("POST", "/api/dev/reset-history", { confirm: "DELETE_HISTORY" }),
  runs: () => req<Run[]>("GET", "/api/test-runs"),
  run: (id: string | number) => req<Run>("GET", `/api/test-runs/${id}`),
  startRun: () => req<Run>("POST", "/api/test-runs"),
  findings: () => req<Finding[]>("GET", "/api/findings"),
  finding: (id: string | number) => req<Finding>("GET", `/api/findings/${id}`),
  saveRegression: (id: number) => req<RegTest>("POST", `/api/findings/${id}/regression-tests`),
  regressions: () => req<RegTest[]>("GET", "/api/regression-tests"),
  regression: (id: string | number) => req<RegTest>("GET", `/api/regression-tests/${id}`),
  runRegression: (id: number) => req<RegRun>("POST", `/api/regression-tests/${id}/runs`),
  renameRegression: (id: number, name: string) => req<RegTest>("PATCH", `/api/regression-tests/${id}`, { name }),
  deleteRegression: (id: number) => req<unknown>("DELETE", `/api/regression-tests/${id}?confirm=true`),
  activity: () => req<Activity[]>("GET", "/api/activity"),
};
