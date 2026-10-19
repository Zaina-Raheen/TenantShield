import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, RegBadge, Empty, ErrorNote, Evidence, fmt, KV, Loading, PageHeader, Section, Table, useBusy, useLoad } from "../ui";

export function Regressions() {
  const { data, error, loading, reload } = useLoad(api.regressions);
  const { busy, err, wrap } = useBusy();
  const rename = (id: number, cur: string) => {
    const name = window.prompt("Rename regression test (1-120 characters)", cur)?.trim();
    if (name === undefined) return;
    if (!name || name.length > 120) { window.alert("Enter a name of 1-120 characters."); return; }
    wrap(async () => { await api.renameRegression(id, name); reload(); });
  };
  const del = (id: number, name: string) => {
    if (window.confirm(`Delete "${name}"? It is hidden from this list, but its retest history and the original finding are kept.`))
      wrap(async () => { await api.deleteRegression(id); reload(); });
  };
  return (
    <>
      <PageHeader title="Regression Tests" sub="Saved request scenarios with their expected policy. Results do not depend on the demo toggle." />
      <ErrorNote message={error || err} />
      {loading ? <Loading /> : !data?.length ? (
        <Empty>No saved tests. Open a finding and choose <b>Save as regression test</b>.</Empty>
      ) : (
        <Table head={["Test", "Endpoint", "Expected behavior", "Last result", "Last run", "Actions"]}>
          {data.map((t) => (
            <tr key={t.id}>
              <td className="td font-medium">{t.name}</td>
              <td className="td code">{t.endpoint}</td>
              <td className="td">{t.expected_policy}</td>
              <td className="td"><RegBadge status={t.last_result_status} /></td>
              <td className="td">{fmt(t.last_run_at)}</td>
              <td className="td"><div className="flex flex-wrap gap-1">
                <button className="btn" disabled={busy} onClick={() => wrap(async () => { await api.runRegression(t.id); reload(); })}>Run test</button>
                <Link className="btn" to={`/regression/${t.id}`}>Details</Link>
                <button className="btn" disabled={busy} onClick={() => rename(t.id, t.name)}>Rename</button>
                <button className="btn btn-danger" disabled={busy} onClick={() => del(t.id, t.name)}>Delete</button>
              </div></td>
            </tr>))}
        </Table>)}
    </>
  );
}

export function RegressionDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: t, error, loading, reload } = useLoad(() => api.regression(id!), [id]);
  const { busy, err, wrap } = useBusy();
  if (loading && !t) return <Loading />;
  if (!t) return <ErrorNote message={error} />;
  return (
    <>
      <PageHeader title={t.name} sub={`Created ${fmt(t.created_at)} from finding #${t.source_finding_id}`}
        action={<button className="btn btn-primary" disabled={busy} onClick={() => wrap(async () => { await api.runRegression(t.id); reload(); })}>
          {busy ? "Running…" : "Run test"}</button>} />
      <ErrorNote message={err} />
      <Section title="Stored scenario">
        <dl className="panel px-4 py-2">
          <KV k="Request" v={<span className="code">{t.definition.method} {t.definition.path}</span>} />
          <KV k="Identity" v={`${t.definition.identity} (${t.definition.requesting_tenant_id})`} />
          <KV k="Expected policy" v={t.expected_policy} />
          <KV k="Finding" v={<Link className="text-accent underline" to={`/findings/${t.source_finding_id}`}>#{t.source_finding_id}</Link>} />
        </dl>
      </Section>
      <Section title="Retest history">
        {!t.runs?.length ? <p className="text-muted">Not run yet.</p> : (
          <div className="space-y-2">{t.runs.map((r) => (
            <div key={r.id} className="panel p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span><RegBadge status={r.result_status} /> <span className="ml-2 text-muted">{fmt(r.run_at)} · demo {r.demo_mode} · HTTP {r.actual_status_code ?? "—"}</span></span>
              </div>
              <div className="mt-1">{r.observed_outcome}</div>
              <details className="mt-1"><summary className="cursor-pointer text-muted">Evidence</summary><Evidence value={r.evidence} /></details>
            </div>))}</div>)}
      </Section>
      <button className="btn btn-danger" disabled={busy} onClick={() => {
        if (window.confirm("Delete this regression test? Its retest history and the finding are kept.")) wrap(async () => { await api.deleteRegression(t.id); nav("/regression"); });
      }}>Delete test</button>
    </>
  );
}
