import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorNote, Evidence, fmt, Loading, PageHeader, Table, useLoad } from "../ui";

export function Runs() {
  const { data, error, loading } = useLoad(api.runs);
  return (
    <>
      <PageHeader title="Test Runs" sub="Every execution of the isolation suite, newest first." />
      <ErrorNote message={error} />
      {loading ? <Loading /> : !data?.length ? <Empty>No runs yet. Start one from the Overview.</Empty> : (
        <Table head={["Run", "Started", "Tests", "Passed", "Findings", "Inconclusive", "Status", ""]}>
          {data.map((r) => (
            <tr key={r.id}>
              <td className="td code">#{r.id}</td><td className="td">{fmt(r.started_at)}</td>
              <td className="td">{r.total_tests}</td><td className="td">{r.passed_count}</td>
              <td className="td">{r.finding_count}</td><td className="td">{r.inconclusive_count}</td>
              <td className="td"><Badge status={r.status} /></td>
              <td className="td"><Link className="text-accent underline" to={`/runs/${r.id}`}>View details</Link></td>
            </tr>))}
        </Table>)}
    </>
  );
}

export function RunDetail() {
  const { id } = useParams();
  const { data, error, loading } = useLoad(() => api.run(id!), [id]);
  if (loading) return <Loading />;
  if (!data) return <ErrorNote message={error} />;
  return (
    <>
      <PageHeader title={`Run #${data.id}`}
        sub={`Started ${fmt(data.started_at)} · demo was in ${data.demo_mode} mode when run.`}
        action={<Badge status={data.status} />} />
      {data.error_summary && <div role="alert" className="mb-4 rounded border border-warn/40 bg-warn/5 px-3 py-2 text-warn">{data.error_summary}. Checks that did not execute are shown as inconclusive; this is not a clean result.</div>}
      <div className="space-y-3">
        {data.results!.map((x) => (
          <div key={x.id} className="panel p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">{x.test_name}</div><Badge status={x.result_status} />
            </div>
            <dl className="mt-2 text-[13px]">
              <div className="code text-muted">{x.endpoint} · as {x.requesting_tenant_id} · HTTP {x.actual_status_code ?? "—"} · {x.duration_ms} ms</div>
              <div className="mt-1"><span className="text-muted">Expected: </span>{x.expected_outcome}</div>
              <div><span className="text-muted">Observed: </span>{x.observed_outcome}</div>
            </dl>
            {x.finding_id && <Link className="mt-2 inline-block text-accent underline" to={`/findings/${x.finding_id}`}>Open finding</Link>}
            <details className="mt-2"><summary className="cursor-pointer text-muted">Evidence</summary><Evidence value={x.evidence} /></details>
          </div>))}
      </div>
    </>
  );
}
