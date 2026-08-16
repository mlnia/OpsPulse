import { FormEvent, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Role = "admin" | "responder" | "viewer";
type User = { email: string; role: Role };
type Incident = { id: string; title: string; severity: "critical" | "high" | "medium" | "low"; status: "open" | "investigating" | "resolved"; service: string; created_at: string };
type Audit = { actor: string; action: string; at: string };
const statuses = ["open", "investigating", "resolved"] as const;

function Login({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const response = await fetch("/api/v1/auth/token", { method: "POST", body: new URLSearchParams({ username: String(data.get("email")), password: String(data.get("password")) }) });
    if (!response.ok) { setError(`Sign-in failed (HTTP ${response.status}). Check API logs: 401 means invalid credentials, 404 an outdated API image, and 500 a server error.`); return; }
    const payload = await response.json(); onLogin(payload.access_token, payload.user);
  };
  return <main className="login"><section><p className="eyebrow">SRE COMMAND CENTER</p><h1>OpsPulse</h1><p>Manage incidents, SLAs, and operational signals from one place.</p><form onSubmit={submit}><label>Email<input name="email" type="email" defaultValue="admin@opspulse.local" required /></label><label>Password<input name="password" type="password" defaultValue="ChangeMe123!" required /></label>{error && <p className="error">{error}</p>}<button type="submit">Sign in</button></form><small>Development credentials are configured in `.env`.</small></section></main>;
}

function Dashboard({ token, user, onLogout }: { token: string; user: User; onLogout: () => void }) {
  const [incidents, setIncidents] = useState<Incident[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState(""); const [audit, setAudit] = useState<Audit[]>([]); const [selected, setSelected] = useState("");
  const api = (path: string, options: RequestInit = {}) => fetch(path, { ...options, cache: "no-store", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...options.headers } });
  const load = async () => { try { setLoading(true); const r = await api("/api/v1/incidents"); if (r.status === 401) { onLogout(); return; } if (!r.ok) throw new Error("The API is unavailable"); setIncidents(await r.json()); } catch (e) { setError(e instanceof Error ? e.message : "Unexpected error"); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  const create = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); const r = await api("/api/v1/incidents", { method: "POST", body: JSON.stringify({ title: data.get("title"), service: data.get("service"), severity: data.get("severity") }) }); if (r.ok) { const created: Incident = await r.json(); setIncidents((current) => [created, ...current]); event.currentTarget.reset(); } else setError("A responder role is required for this action."); };
  const advance = async (incident: Incident) => { const next = statuses[Math.min(statuses.indexOf(incident.status) + 1, statuses.length - 1)]; const r = await api(`/api/v1/incidents/${incident.id}`, { method: "PATCH", body: JSON.stringify({ status: next }) }); if (r.ok) await load(); else setError("Unable to update incident status."); };
  const showAudit = async (id: string) => { setSelected(id); const r = await api(`/api/v1/incidents/${id}/audit`); if (r.ok) setAudit(await r.json()); };
  const active = incidents.filter((i) => i.status !== "resolved").length; const canWrite = user.role !== "viewer";
  return <main><header><div><p className="eyebrow">SRE COMMAND CENTER · {user.role.toUpperCase()}</p><h1>OpsPulse</h1></div><div className="header-actions"><span>{user.email}</span><button onClick={() => void load()}>↻ Refresh</button><button className="ghost" onClick={onLogout}>Sign out</button></div></header><section className="metrics"><article><span>Active incidents</span><strong>{active}</strong></article><article><span>Critical incidents</span><strong>{incidents.filter((i) => i.severity === "critical" && i.status !== "resolved").length}</strong></article><article><span>Resolved</span><strong>{incidents.filter((i) => i.status === "resolved").length}</strong></article></section><section className="grid">{canWrite && <form onSubmit={create}><h2>Create incident</h2><label>Title<input name="title" placeholder="e.g. Payments API latency" required minLength={4} /></label><label>Service<input name="service" placeholder="payments-api" required minLength={2} /></label><label>Severity<select name="severity" defaultValue="high"><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label><button type="submit">Create incident</button></form>}<section className="feed"><div className="section-title"><h2>Incident feed</h2><span>{incidents.length} records</span></div>{error && <p className="error">{error}</p>}{loading ? <p>Loading…</p> : incidents.length === 0 ? <p className="empty">No incidents yet. Create the first one.</p> : incidents.map((i) => <article className="incident" key={i.id}><div><span className={`badge ${i.severity}`}>{i.severity}</span><h3>{i.title}</h3><p>{i.service} · {new Date(i.created_at).toLocaleString("en-US")}</p></div><div className="incident-actions"><button className="ghost" onClick={() => void showAudit(i.id)}>History</button><button className="status" disabled={i.status === "resolved" || !canWrite} onClick={() => void advance(i)}>{i.status}</button></div></article>)}</section></section>{selected && <section className="audit"><div className="section-title"><h2>Audit log</h2><button className="ghost" onClick={() => setSelected("")}>Close</button></div>{audit.length === 0 ? <p>No audit records for this incident.</p> : audit.map((entry) => <p key={`${entry.at}-${entry.action}`}><b>{entry.actor}</b> {entry.action} · {new Date(entry.at).toLocaleString("en-US")}</p>)}</section>}</main>;
}

function App() { const [session, setSession] = useState<{ token: string; user: User } | null>(() => { const saved = localStorage.getItem("opspulse-session"); return saved ? JSON.parse(saved) : null; }); const login = (token: string, user: User) => { const next = { token, user }; localStorage.setItem("opspulse-session", JSON.stringify(next)); setSession(next); }; const logout = () => { localStorage.removeItem("opspulse-session"); setSession(null); }; return session ? <Dashboard {...session} onLogout={logout} /> : <Login onLogin={login} />; }
createRoot(document.getElementById("root")!).render(<App />);
