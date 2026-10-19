import { NavLink, Route, Routes } from "react-router-dom";
import { Activity, Bug, FlaskConical, LayoutDashboard, Server } from "lucide-react";
import Overview from "./pages/Overview";
import { RunDetail, Runs } from "./pages/Runs";
import { FindingDetail, Findings } from "./pages/Findings";
import { RegressionDetail, Regressions } from "./pages/Regressions";
import Demo from "./pages/Demo";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/runs", label: "Test Runs", icon: Activity },
  { to: "/findings", label: "Findings", icon: Bug },
  { to: "/regression", label: "Regression Tests", icon: FlaskConical },
  { to: "/demo", label: "Demo Environment", icon: Server },
];

export default function App() {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="shrink-0 border-b border-line bg-white md:w-56 md:border-b-0 md:border-r">
        <div className="px-4 py-4">
          <div className="font-serif text-[20px] font-semibold tracking-tight">Tenantshield</div>
          <div className="text-[12px] text-muted">Tenant-boundary verification</div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) =>
                `flex items-center gap-2 whitespace-nowrap rounded px-3 py-1.5 ${isActive ? "bg-accent/10 font-medium text-accent" : "text-ink hover:bg-page"}`}>
              <Icon size={15} strokeWidth={1.75} />{label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-10">
        <div className="mx-auto max-w-5xl">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/findings" element={<Findings />} />
            <Route path="/findings/:id" element={<FindingDetail />} />
            <Route path="/regression" element={<Regressions />} />
            <Route path="/regression/:id" element={<RegressionDetail />} />
            <Route path="/demo" element={<Demo />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
