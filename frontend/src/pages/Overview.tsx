import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorNote, fmt, Loading, PageHeader, RegBadge, useBusy, useLoad } from "../ui";

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="border-l border-line pl-3">
      <div className={`font-mono text-[26px] leading-none ${tone ?? ""}`}>{value}</div>
      <div className="mt-1 text-[12px] text-muted">{label}</div>
    </div>
  );
}

export default function Overview() {
  const status = useLoad(api.demoStatus);
  const runs = useLoad(api.runs);
  const findings = useLoad(api.findings);
  const regs = useLoad(api.regressions);
  const act = useLoad(api.activity);
  const latest = runs.data?.[0];
  const latestDetail = useLoad(() => (latest ? api.run(latest.id) : Promise.resolve(null)), [latest?.id]);
  const { busy, err, wrap } = useBusy();

  const start = () => wrap(async () => {
    await api.startRun();
    runs.reload(); findings.reload(); regs.reload(); act.reload(); status.reload();
  });

  const hasRun = (runs.data?.length ?? 0) > 0;
  const hasFinding = (findings.data?.length ?? 0) > 0;
  const hasReg = (regs.data?.length ?? 0) > 0;
  const verified = regs.data?.some((r) => r.last_result_status === "passed") ?? false;
  const steps = [
    { name: "Test", text: "Run same-tenant and cross-tenant checks", done: hasRun, to: "/runs" },
    { name: "Prove", text: "Inspect the request, response and owner evidence", done: hasFinding, to: "/findings" },
    { name: "Preserve", text: "Save the failure as a regression test", done: hasReg, to: "/regression" },
    { name: "Verify", text: "Retest after the fix and see it pass", done: verified, to: "/regression" },
  ];
  const next = !hasRun ? "Choose Run isolation tests."
    : !hasFinding ? "No findings in this state. To see detection, enable vulnerable mode in Demo Environment and run again."
    : !hasReg ? "Open a finding and save it as a regression test."
    : !verified ? "Switch the demo to fixed mode, then run the regression test again."
    : "Fix verified. The original finding stays on record next to the passing retest.";

  return (
    <>
      <PageHeader title="Overview"
        sub="Checks whether one customer organization can read another's private API resources, then proves the fix."
        action={<button className="btn btn-primary" disabled={busy || status.data?.reachable === false} onClick={start}>
          {busy ? "Running tests…" : "Run isolation tests"}</button>} />
      <ErrorNote message={err || runs.error || status.error} />

      <div className="panel mb-6 flex flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3">
        <div>Demo API: {status.data ? (status.data.reachable
          ? <span className="font-medium text-ok">connected</span>
          : <span className="font-medium text-fail">unreachable</span>) : "…"}</div>
        <div className="flex items-center gap-2">Demo mode: <Badge status={status.data?.mode} /></div>
        {status.data && !status.data.reachable &&
          <div className="text-muted">Start the backend (see README), then reload. Runs will be inconclusive until then.</div>}
      </div>

      <section className="mb-6">
        <div className="grid gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-4">
          {steps.map((s) => (
            <Link key={s.name} to={s.to} className="bg-white p-3 hover:bg-page">
              <div className="flex items-center gap-2 font-medium">
                <span className={`inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] ${s.done ? "border-ok bg-ok text-white" : "border-line text-transparent"}`}>✓</span>
                {s.name}
              </div>
              <div className="mt-1 text-[12px] text-muted">{s.text}</div>
            </Link>))}
        </div>
        <p className="mt-2 text-muted">Next: {next}</p>
      </section>

      {runs.loading ? <Loading /> : !latest ? (
        <Empty>No runs yet. Make sure the demo API is connected, then choose <b>Run isolation tests</b>.</Empty>
      ) : (
        <>
          <div className="mb-2 text-muted">Latest run: <Link className="text-accent underline" to={`/runs/${latest.id}`}>#{latest.id}</Link> · {fmt(latest.started_at)} · demo was <b>{latest.demo_mode}</b> · <Badge status={latest.status} /></div>
          <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Tests in latest run" value={latest.total_tests} />
            <Stat label="Passed checks" value={latest.passed_count} tone="text-ok" />
            <Stat label="Confirmed findings" value={latest.finding_count} tone={latest.finding_count ? "text-fail" : ""} />
            <Stat label="Inconclusive checks" value={latest.inconclusive_count} />
          </div>
          {latest.failed_count > 0 && <p className="mb-2 text-warn">{latest.failed_count} test(s) behaved differently than expected without confirming a leak.</p>}
          {latest.status === "passed" && <p className="mb-2 text-muted">All configured checks passed. This does not mean the whole application is secure.</p>}
          {latest.error_summary && <p className="mb-2 text-warn">{latest.error_summary}.</p>}
          {latest.status === "inconclusive" && <p className="mb-2 text-muted">Some checks could not be evaluated, so this run is not a clean result.</p>}

          {latestDetail.data?.results && (
            <ul className="panel mt-4 divide-y divide-line">
              {latestDetail.data.results.map((x) => (
                <li key={x.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <span>{x.test_name}</span>
                  <span className="flex items-center gap-3">
                    <span className="code text-muted">HTTP {x.actual_status_code ?? "—"}</span><Badge status={x.result_status} />
                  </span>
                </li>))}
            </ul>)}
        </>
      )}

      {hasFinding && (
        <>
          <h2 className="mb-2 mt-8 text-[18px] font-semibold">Fix verification</h2>
          <ul className="panel divide-y divide-line">
            {findings.data!.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <Link className="text-accent underline" to={`/findings/${f.id}`}>{f.title}</Link>
                <RegBadge status={f.regression_status} />
              </li>))}
          </ul>
        </>
      )}

      <h2 className="mb-2 mt-8 text-[18px] font-semibold">Recent activity</h2>
      {act.data && act.data.length > 0 ? (
        <ul className="panel divide-y divide-line">
          {act.data.map((a, i) => (
            <li key={i} className="flex items-center justify-between gap-3 px-3 py-2">
              <span>{a.text}</span><span className="shrink-0 text-[12px] text-muted">{fmt(a.at)}</span>
            </li>))}
        </ul>
      ) : <p className="text-muted">Nothing yet.</p>}
    </>
  );
}
