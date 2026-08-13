"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createProject,
  fetchArtifact,
  fetchDeployments,
  fetchEvents,
  fetchLog,
  fetchProjectDetail,
  fetchProjectTasks,
  fetchProjects,
  getWebSocketUrl,
  promoteProject,
  runPipeline,
  type Deployment,
  type FactoryEvent,
  type Project,
  type ProjectDetail,
  type Task,
} from "@/lib/api";
import styles from "./page.module.css";

const PIPELINE = [
  "REQUESTED",
  "PLANNING",
  "IMPLEMENTING",
  "UNIT_TESTING",
  "INTEGRATION_TESTING",
  "DOCKER_BUILD",
  "STAGING_DEPLOY",
  "SMOKE_TESTING",
  "REVIEW",
  "PRODUCTION",
] as const;

const STATE_COLORS: Record<string, string> = {
  REQUESTED: "#6b7280",
  PLANNING: "#5b8def",
  IMPLEMENTING: "#5b8def",
  UNIT_TESTING: "#f5a623",
  INTEGRATION_TESTING: "#f5a623",
  DOCKER_BUILD: "#f5a623",
  STAGING_DEPLOY: "#f5a623",
  SMOKE_TESTING: "#f5a623",
  REVIEW: "#a78bfa",
  PRODUCTION: "#3dd68c",
  DIAGNOSING: "#f56565",
  FIXING: "#f5a623",
  AUTONOMOUSLY_BLOCKED: "#f56565",
};

type Tab = "overview" | "tasks" | "artifacts" | "deployments" | "logs";

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [events, setEvents] = useState<FactoryEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [artifactView, setArtifactView] = useState<{ name: string; content: string } | null>(null);
  const [logView, setLogView] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const p = await fetchProjects();
      setProjects(p);
      if (!selectedId && p.length > 0) setSelectedId(p[0].id);

      if (selectedId) {
        const [d, t, dep, e] = await Promise.all([
          fetchProjectDetail(selectedId),
          fetchProjectTasks(selectedId),
          fetchDeployments(selectedId),
          fetchEvents(100, selectedId),
        ]);
        setDetail(d);
        setTasks(t);
        setDeployments(dep);
        setEvents(e);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    }
  }, [selectedId]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, detail?.pipeline_running ? 2000 : 10000);
    return () => clearInterval(interval);
  }, [refresh, detail?.pipeline_running]);

  useEffect(() => {
    const ws = new WebSocket(`${getWebSocketUrl()}/ws/events`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.type === "ping") return;
      setEvents((prev) => [...prev.slice(-199), data]);
      refresh();
    };
    return () => ws.close();
  }, [refresh]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setLoading(true);
    try {
      const p = await createProject(newName, newDesc);
      setNewName("");
      setNewDesc("");
      setSelectedId(p.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleRun() {
    if (!selectedId) return;
    setLoading(true);
    try {
      await runPipeline(selectedId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pipeline start failed");
    } finally {
      setLoading(false);
    }
  }

  async function handlePromote() {
    if (!selectedId) return;
    setLoading(true);
    try {
      await promoteProject(selectedId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Promote failed");
    } finally {
      setLoading(false);
    }
  }

  async function viewArtifact(name: string) {
    if (!selectedId) return;
    const content = await fetchArtifact(selectedId, name);
    setArtifactView({ name, content });
  }

  async function viewLog(name: string) {
    if (!selectedId) return;
    const content = await fetchLog(selectedId, name);
    setLogView(content);
  }

  const currentIdx = detail ? PIPELINE.indexOf(detail.state as (typeof PIPELINE)[number]) : -1;

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <div className={styles.logo}>🐢</div>
          <div>
            <h1>turtSlopFactory</h1>
            <p>Agentic software development platform</p>
          </div>
        </div>
        <div className={styles.headerRight}>
          <span className={connected ? styles.live : styles.offline}>
            <span className={styles.dot} />
            {connected ? "Live" : "Offline"}
          </span>
          <span className={styles.badge}>{projects.length} projects</span>
        </div>
      </header>

      {error && (
        <div className={styles.error} onClick={() => setError(null)}>
          {error} <span className={styles.dismiss}>✕</span>
        </div>
      )}

      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <div className={styles.sidebarHeader}>
            <h2>Projects</h2>
          </div>
          <ul className={styles.projectList}>
            {projects.map((p) => (
              <li key={p.id}>
                <button
                  className={p.id === selectedId ? styles.projectActive : styles.projectBtn}
                  onClick={() => {
                    setSelectedId(p.id);
                    setTab("overview");
                    setArtifactView(null);
                    setLogView(null);
                  }}
                >
                  <span className={styles.projectName}>{p.name}</span>
                  <span
                    className={styles.stateTag}
                    style={{ background: STATE_COLORS[p.state] ?? "#6b7280" }}
                  >
                    {p.state.replace(/_/g, " ")}
                  </span>
                </button>
              </li>
            ))}
            {projects.length === 0 && (
              <p className={styles.emptyHint}>No projects yet</p>
            )}
          </ul>

          <form className={styles.createForm} onSubmit={handleCreate}>
            <h3>New project</h3>
            <input
              placeholder="e.g. Invoice Manager"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
            />
            <textarea
              placeholder="Describe what to build: a Docker-deployable web app with REST API..."
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              rows={4}
            />
            <button type="submit" className={styles.btnPrimary} disabled={loading}>
              Create project
            </button>
          </form>
        </aside>

        <main className={styles.main}>
          {detail ? (
            <>
              <div className={styles.projectTop}>
                <div>
                  <h2>{detail.name}</h2>
                  <p>{detail.description}</p>
                </div>
                <div className={styles.actions}>
                  {detail.pipeline_running ? (
                    <span className={styles.running}>Pipeline running…</span>
                  ) : (
                    <>
                      {detail.state !== "PRODUCTION" && (
                        <button className={styles.btnPrimary} onClick={handleRun} disabled={loading}>
                          {detail.state === "REQUESTED" ? "Start pipeline" : "Re-run pipeline"}
                        </button>
                      )}
                      {detail.state === "REVIEW" && (
                        <button className={styles.btnSuccess} onClick={handlePromote} disabled={loading}>
                          Promote to production
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>

              <div className={styles.meta}>
                {detail.image_tag && <span>Image: <code>{detail.image_tag}</code></span>}
                {detail.staging_url && (
                  <a href={detail.staging_url} target="_blank" rel="noreferrer">
                    Staging ↗
                  </a>
                )}
                {detail.production_url && (
                  <a href={detail.production_url} target="_blank" rel="noreferrer" className={styles.prodLink}>
                    Production ↗
                  </a>
                )}
              </div>

              <div className={styles.tabs}>
                {(["overview", "tasks", "artifacts", "deployments", "logs"] as Tab[]).map((t) => (
                  <button
                    key={t}
                    className={tab === t ? styles.tabActive : styles.tab}
                    onClick={() => setTab(t)}
                  >
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>

              {tab === "overview" && (
                <div className={styles.pipeline}>
                  {PIPELINE.map((state, i) => {
                    const done = currentIdx > i;
                    const active = detail.state === state;
                    const failed = ["DIAGNOSING", "FIXING", "AUTONOMOUSLY_BLOCKED"].includes(detail.state) && i === currentIdx;
                    return (
                      <div
                        key={state}
                        className={`${styles.step} ${done ? styles.stepDone : ""} ${active ? styles.stepActive : ""} ${failed ? styles.stepFailed : ""}`}
                      >
                        <div className={styles.stepDot} />
                        <span>{state.replace(/_/g, " ")}</span>
                      </div>
                    );
                  })}
                </div>
              )}

              {tab === "tasks" && (
                <div className={styles.table}>
                  {tasks.length === 0 ? (
                    <p className={styles.emptyHint}>No tasks yet — start the pipeline</p>
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Task</th>
                          <th>Role</th>
                          <th>Status</th>
                          <th>Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tasks.map((t) => (
                          <tr key={t.id}>
                            <td>{t.title}</td>
                            <td><span className={styles.roleBadge}>{t.role}</span></td>
                            <td><span className={styles[`status_${t.status}`] ?? ""}>{t.status}</span></td>
                            <td>{new Date(t.created_at).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {tab === "artifacts" && (
                <div className={styles.artifactGrid}>
                  {detail.artifacts.length === 0 ? (
                    <p className={styles.emptyHint}>No artifacts yet</p>
                  ) : (
                    detail.artifacts.map((a) => (
                      <button key={a} className={styles.artifactCard} onClick={() => viewArtifact(a)}>
                        📄 {a}
                      </button>
                    ))
                  )}
                  {artifactView && (
                    <div className={styles.modal}>
                      <div className={styles.modalContent}>
                        <div className={styles.modalHeader}>
                          <h3>{artifactView.name}</h3>
                          <button onClick={() => setArtifactView(null)}>✕</button>
                        </div>
                        <pre>{artifactView.content}</pre>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === "deployments" && (
                <div className={styles.table}>
                  {deployments.length === 0 ? (
                    <p className={styles.emptyHint}>No deployments yet</p>
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Environment</th>
                          <th>Image</th>
                          <th>URL</th>
                          <th>Status</th>
                          <th>Deployed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {deployments.map((d) => (
                          <tr key={d.id}>
                            <td><span className={d.environment === "production" ? styles.prodBadge : styles.stagingBadge}>{d.environment}</span></td>
                            <td><code>{d.image_tag}</code></td>
                            <td>{d.url ? <a href={d.url} target="_blank" rel="noreferrer">{d.url}</a> : "—"}</td>
                            <td>{d.status}</td>
                            <td>{new Date(d.created_at).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {tab === "logs" && (
                <div className={styles.logPanel}>
                  <button className={styles.btnSecondary} onClick={() => viewLog("pipeline.log")}>
                    View pipeline.log
                  </button>
                  {logView && <pre className={styles.logContent}>{logView}</pre>}
                </div>
              )}
            </>
          ) : (
            <div className={styles.welcome}>
              <h2>Welcome to turtSlopFactory</h2>
              <p>
                Create a project with a natural-language spec. The factory will plan, implement,
                test, build a Docker image, deploy to staging, and promote to production —
                autonomously.
              </p>
              <ol>
                <li>Describe your app in the sidebar</li>
                <li>Click <strong>Start pipeline</strong></li>
                <li>Watch agents work in real time</li>
                <li>Approve promotion when review passes</li>
              </ol>
            </div>
          )}
        </main>

        <aside className={styles.events}>
          <h2>Live events</h2>
          <ul>
            {[...events].reverse().slice(0, 50).map((ev) => (
              <li key={ev.id} className={styles.event}>
                <span className={styles.eventType}>{ev.type}</span>
                <span className={styles.eventBody}>
                  {formatEvent(ev)}
                </span>
                <time>{new Date(ev.created_at).toLocaleTimeString()}</time>
              </li>
            ))}
            {events.length === 0 && <p className={styles.emptyHint}>Waiting for events…</p>}
          </ul>
        </aside>
      </div>
    </div>
  );
}

function formatEvent(ev: FactoryEvent): string {
  const p = ev.payload;
  if (ev.type === "state.transition") return `${p.from ?? "—"} → ${p.to}`;
  if (ev.type === "task.status.changed") return String(p.title ?? p.status);
  if (ev.type === "test.completed") return `${p.stage}: ${p.passed ? "PASS" : "FAIL"}`;
  if (ev.type === "deployment.finished") return `${p.environment} ${p.url ?? ""}`;
  if (ev.type === "agent.command.finished") return String(p.output ?? p.command ?? "").slice(0, 80);
  return JSON.stringify(p).slice(0, 80);
}
