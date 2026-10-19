import { api } from "../api";
import { Badge, ErrorNote, Loading, PageHeader, Section, useBusy, useLoad } from "../ui";

export default function Demo() {
  const status = useLoad(api.demoStatus);
  const tenants = useLoad(api.tenants);
  const { busy, err, wrap } = useBusy();
  const s = status.data;
  const refresh = () => { status.reload(); tenants.reload(); };
  const setMode = (m: "vulnerable" | "fixed") => wrap(async () => { await api.setMode(m); refresh(); });
  return (
    <>
      <PageHeader title="Demo Environment" sub="A bundled, synthetic college-management API. Active tests run only against this local demo." />
      <ErrorNote message={err || status.error || tenants.error} />
      <Section title="Status">
        {!s ? <Loading /> : (
          <div className="panel flex flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3">
            <div>Health: {s.reachable ? <b className="text-ok">ok</b> : <b className="text-fail">unreachable</b>}</div>
            <div className="flex items-center gap-2">Mode: <Badge status={s.mode} /></div>
          </div>)}
      </Section>

      <Section title="Vulnerability toggle (development only)">
        <div className="panel p-4">
          <p className="mb-3 max-w-[70ch] text-muted">
            In <b>vulnerable</b> mode, <span className="code">GET /api/demo/documents/&#123;id&#125;</span> skips the ownership check, so any
            authenticated user can read another tenant's document. In <b>fixed</b> mode the server compares the document's tenant with the
            tenant derived from the validated token and returns 404 on mismatch. The document list is always tenant-scoped.
          </p>
          {s && !s.dev_controls_enabled ? <p className="text-fail">Controls are disabled because the environment is not <span className="code">development</span>. The demo API always behaves as fixed.</p> : (
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn" disabled={busy || s?.mode === "vulnerable" || !s?.vulnerable_demo_enabled} onClick={() => setMode("vulnerable")}>Enable vulnerable mode</button>
              <button className="btn" disabled={busy || s?.mode === "fixed"} onClick={() => setMode("fixed")}>Switch to fixed mode</button>
              {s && !s.vulnerable_demo_enabled && <p className="basis-full text-warn">The vulnerable demo is switched off. Start the app with <span className="code">python run.py</span> (or set <span className="code">TENANTSHIELD_ENABLE_VULNERABLE_DEMO=1</span> in a development environment) to demonstrate detection.</p>}
            </div>)}
        </div>
      </Section>

      <Section title="Tenants and synthetic documents">
        {!tenants.data ? <Loading /> : (
          <div className="grid gap-3 md:grid-cols-2">
            {tenants.data.map((t) => (
              <div key={t.id} className="panel p-4">
                <div className="font-medium">{t.name}</div>
                <div className="code text-muted">{t.id}</div>
                <div className="mt-2 text-[13px]"><span className="text-muted">Test identity: </span>
                  {t.users.map((u) => <span key={u.user_id} className="code">{u.display_name} ({u.user_id})</span>)}</div>
                <ul className="mt-2 text-[13px]">{t.documents.map((d) => (
                  <li key={d.id}><span className="code">{d.id}</span> · {d.title} · <span className="code text-muted">{t.marker}</span></li>))}</ul>
              </div>))}
          </div>)}
      </Section>

      <Section title="Reset">
        <div className="flex flex-wrap gap-2">
          <button className="btn" disabled={busy || !s?.dev_controls_enabled} onClick={() => wrap(async () => { await api.resetDemo(); refresh(); })}>
            Reset demo data</button>
          <button className="btn btn-danger" disabled={busy || !s?.dev_controls_enabled} onClick={() => {
            if (window.confirm("Permanently delete ALL test runs, findings and regression tests?")) wrap(async () => { await api.resetHistory(); refresh(); });
          }}>Delete all history…</button>
        </div>
        <p className="mt-2 text-muted">Resetting demo data restores the seeded documents and keeps your runs, findings and regression tests.</p>
      </Section>
    </>
  );
}
