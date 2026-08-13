"use client";

import { useCallback, useEffect, useState } from "react";
import {
  advanceProject,
  createProject,
  fetchEvents,
  fetchProjects,
  fetchTasks,
  getWebSocketUrl,
  type FactoryEvent,
  type Project,
  type Task,
} from "@/lib/api";
import styles from "./page.module.css";

const STATE_COLORS: Record<string, string> = {
  REQUESTED: "var(--muted)",
  PLANNING: "var(--accent)",
  IMPLEMENTING: "var(--accent)",
  UNIT_TESTING: "var(--warning)",
  INTEGRATION_TESTING: "var(--warning)",
  DOCKER_BUILD: "var(--warning)",
  STAGING_DEPLOY: "var(--warning)",
  SMOKE_TESTING: "var(--warning)",
  REVIEW: "var(--accent)",
  PRODUCTION: "var(--success)",
  DIAGNOSING: "var(--danger)",
  FIXING: "var(--warning)",
  AUTONOMOUSLY_BLOCKED: "var(--danger)",
};

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [events, setEvents] = useState<FactoryEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [p, t, e] = await Promise.all([fetchProjects(), fetchTasks(), fetchEvents()]);
      setProjects(p);
      setTasks(t);
      setEvents(e);
      if (!selectedId && p.length > 0) setSelectedId(p[0].id);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    }
  }, [selectedId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const ws = new WebSocket(`${getWebSocketUrl()}/ws/events`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.type === "ping") return;
      setEvents((prev) => [...prev.slice(-99), data]);
      refresh();
    };

    return () => ws.close();
  }, [refresh]);

  const selected = projects.find((p) => p.id === selectedId) ?? null;
  const projectTasks = tasks.filter((t) => t.project_id === selectedId);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    await createProject(newName, newDesc);
    setNewName("");
    setNewDesc("");
    await refresh();
  }

  async function handleAdvance() {
    if (!selected) return;
    await advanceProject(selected.id);
    await refresh();
  }

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div>
          <h1>turtSlopFactory</h1>
          <p className={styles.subtitle}>Agentic software development control plane</p>
        </div>
        <div className={styles.statusBadge}>
          <span className={connected ? styles.dotOn : styles.dotOff} />
          {connected ? "Live" : "Disconnected"}
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.main}>
        <aside className={styles.sidebar}>
          <h2>Projects</h2>
          <ul className={styles.projectList}>
            {projects.map((p) => (
              <li key={p.id}>
                <button
                  className={p.id === selectedId ? styles.projectActive : styles.projectItem}
                  onClick={() => setSelectedId(p.id)}
                >
                  <span className={styles.projectName}>{p.name}</span>
                  <span
                    className={styles.statePill}
                    style={{ background: STATE_COLORS[p.state] ?? "var(--muted)" }}
                  >
                    {p.state.replace(/_/g, " ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <form className={styles.createForm} onSubmit={handleCreate}>
            <h3>New project</h3>
            <input
              placeholder="Project name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <textarea
              placeholder="Description / spec"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              rows={3}
            />
            <button type="submit" className={styles.btnPrimary}>
              Create
            </button>
          </form>
        </aside>

        <section className={styles.content}>
          {selected ? (
            <>
              <div className={styles.projectHeader}>
                <div>
                  <h2>{selected.name}</h2>
                  <p className={styles.muted}>{selected.description}</p>
                </div>
                <div className={styles.actions}>
                  <button className={styles.btnSecondary} onClick={handleAdvance}>
                    Advance state
                  </button>
                </div>
              </div>

              <div className={styles.grid}>
                <div className={styles.card}>
                  <h3>Pipeline</h3>
                  <div className={styles.pipeline}>
                    {[
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
                    ].map((state) => (
                      <div
                        key={state}
                        className={
                          state === selected.state
                            ? styles.pipelineStepActive
                            : styles.pipelineStep
                        }
                      >
                        {state.replace(/_/g, " ")}
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.card}>
                  <h3>Task queue</h3>
                  {projectTasks.length === 0 ? (
                    <p className={styles.muted}>No tasks yet</p>
                  ) : (
                    <ul className={styles.taskList}>
                      {projectTasks.map((t) => (
                        <li key={t.id} className={styles.taskItem}>
                          <span className={styles.taskTitle}>{t.title}</span>
                          <span className={styles.taskMeta}>
                            {t.role} · {t.status}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className={styles.empty}>
              <p>Create a project to get started.</p>
            </div>
          )}
        </section>

        <aside className={styles.eventPanel}>
          <h2>Live events</h2>
          <ul className={styles.eventList}>
            {[...events].reverse().map((ev) => (
              <li key={ev.id} className={styles.eventItem}>
                <span className={styles.eventType}>{ev.type}</span>
                <span className={styles.eventPayload}>
                  {JSON.stringify(ev.payload).slice(0, 120)}
                </span>
                <time className={styles.eventTime}>
                  {new Date(ev.created_at).toLocaleTimeString()}
                </time>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}
