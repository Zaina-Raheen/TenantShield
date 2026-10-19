import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError } from "./api";

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(() => {
    setLoading(true);
    fn().then((d) => { setData(d); setError(null); })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Unexpected error"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

const STATUS: Record<string, { label: string; cls: string }> = {
  passed: { label: "Passed", cls: "text-ok border-ok/40 bg-ok/5" },
  finding: { label: "Finding", cls: "text-fail border-fail/40 bg-fail/5" },
  findings: { label: "Findings confirmed", cls: "text-fail border-fail/40 bg-fail/5" },
  failed: { label: "Test failure", cls: "text-warn border-warn/40 bg-warn/5" },
  inconclusive: { label: "Inconclusive", cls: "text-muted border-line bg-page" },
  running: { label: "Running", cls: "text-muted border-line bg-page" },
  vulnerable: { label: "Vulnerable", cls: "text-fail border-fail/40 bg-fail/5" },
  fixed: { label: "Fixed", cls: "text-ok border-ok/40 bg-ok/5" },
  not_saved: { label: "No regression test", cls: "text-muted border-line bg-page" },
  saved: { label: "Saved, not yet run", cls: "text-muted border-line bg-page" },
};
export function Badge({ status }: { status: string | null | undefined }) {
  const s = STATUS[status ?? ""] ?? { label: status ?? "Not run", cls: "text-muted border-line bg-page" };
  return <span className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[12px] font-medium ${s.cls}`}>{s.label}</span>;
}

export const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

export function PageHeader({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-line pb-4">
      <div>
        <h1 className="text-[28px] font-semibold leading-tight">{title}</h1>
        {sub && <p className="mt-1 max-w-[62ch] text-muted">{sub}</p>}
      </div>
      {action}
    </header>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <div role="alert" className="mb-4 rounded border border-fail/40 bg-fail/5 px-3 py-2 text-fail">{message}</div>;
}
export function Loading() { return <p className="text-muted">Loading…</p>; }
export function Empty({ children }: { children: ReactNode }) {
  return <div className="panel px-4 py-8 text-center text-muted">{children}</div>;
}
export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse">
        <thead><tr>{head.map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
export function Evidence({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2);
  return (
    <div className="relative">
      <pre className="code max-h-72 overflow-auto whitespace-pre-wrap rounded border border-line bg-page p-3">{text}</pre>
      <button className="btn absolute right-2 top-2 !py-0.5 text-[12px]" onClick={() => navigator.clipboard?.writeText(text)}>Copy</button>
    </div>
  );
}
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mb-6"><h2 className="mb-2 text-[18px] font-semibold">{title}</h2>{children}</section>;
}
export function KV({ k, v }: { k: string; v: ReactNode }) {
  return <div className="flex gap-3 py-1"><dt className="w-40 shrink-0 text-muted">{k}</dt><dd className="min-w-0 break-words">{v}</dd></div>;
}
export function useBusy() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const wrap = async <R,>(fn: () => Promise<R>): Promise<R | undefined> => {
    if (busy) return;
    setBusy(true); setErr(null);
    try { return await fn(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Unexpected error"); }
    finally { setBusy(false); }
  };
  return { busy, err, wrap };
}

const REG: Record<string, { label: string; cls: string }> = {
  not_saved: { label: "No test saved", cls: "text-muted border-line bg-page" },
  saved: { label: "Saved, not yet run", cls: "text-muted border-line bg-page" },
  passed: { label: "Fixed: retest passed", cls: "text-ok border-ok/40 bg-ok/5" },
  finding: { label: "Still vulnerable", cls: "text-fail border-fail/40 bg-fail/5" },
  failed: { label: "Test failure", cls: "text-warn border-warn/40 bg-warn/5" },
  inconclusive: { label: "Inconclusive", cls: "text-muted border-line bg-page" },
};
/** Status wording for regression contexts, where "finding" means the issue is still present. */
export function RegBadge({ status }: { status: string | null | undefined }) {
  const s = REG[status ?? "saved"] ?? REG.saved;
  return <span className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[12px] font-medium ${s.cls}`}>{status ? s.label : "Not run"}</span>;
}
