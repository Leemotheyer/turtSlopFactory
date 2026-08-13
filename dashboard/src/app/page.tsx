"use client";

import { useCallback, useEffect, useState } from "react";
import {
  addNote,
  createProject,
  deleteSecret,
  fetchArtifact,
  fetchDeployments,
  fetchDiscovery,
  fetchEvents,
  fetchInputRequests,
  fetchLog,
  fetchNotes,
  fetchNotifications,
  fetchProgress,
  fetchProjectDetail,
  fetchProjectTasks,
  fetchProjects,
  fetchSecrets,
  fetchUnreadCount,
  getWebSocketUrl,
  markAllNotificationsRead,
  markNotificationRead,
  promoteProject,
  respondToInput,
  runPipeline,
  setSecret,
  submitIntake,
  type Deployment,
  type DiscoverySession,
  type FactoryEvent,
  type InputRequest,
  type IntakeField,
  type NoteType,
  type Notification,
  type ProgressDigest,
  type Project,
  type ProjectDetail,
  type ProjectNote,
  type ProjectSecrets,
  type Task,
} from "@/lib/api";
import styles from "./page.module.css";

const PIPELINE = [
  "REQUESTED",
  "DISCOVERY",
  "INTAKE_PENDING",
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
  DISCOVERY: "#5b8def",
  INTAKE_PENDING: "#f5a623",
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

type Tab = "overview" | "intake" | "guidance" | "secrets" | "tasks" | "artifacts" | "deployments" | "logs";

const NOTE_TYPES: { value: NoteType; label: string }[] = [
  { value: "instruction", label: "Instruction" },
  { value: "feature", label: "Add feature" },
  { value: "scope_out", label: "Out of scope" },
  { value: "general", label: "General" },
];

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
  const [progress, setProgress] = useState<ProgressDigest | null>(null);
  const [notes, setNotes] = useState<ProjectNote[]>([]);
  const [inputRequests, setInputRequests] = useState<InputRequest[]>([]);
  const [noteText, setNoteText] = useState("");
  const [noteType, setNoteType] = useState<NoteType>("instruction");
  const [inputResponses, setInputResponses] = useState<Record<string, string>>({});
  const [discovery, setDiscovery] = useState<DiscoverySession | null>(null);
  const [intakeAnswers, setIntakeAnswers] = useState<Record<string, string | string[]>>({});
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showNotifications, setShowNotifications] = useState(false);
  const [secrets, setSecrets] = useState<ProjectSecrets | null>(null);
  const [secretKey, setSecretKey] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [secretDesc, setSecretDesc] = useState("");

  const refresh = useCallback(async () => {
    try {
      const p = await fetchProjects();
      setProjects(p);
      if (!selectedId && p.length > 0) setSelectedId(p[0].id);

      const [notifs, unread] = await Promise.all([
        fetchNotifications(),
        fetchUnreadCount(),
      ]);
      setNotifications(notifs);
      setUnreadCount(unread);

      if (selectedId) {
        const [d, t, dep, e, prog, n, inputs, disc, sec] = await Promise.all([
          fetchProjectDetail(selectedId),
          fetchProjectTasks(selectedId),
          fetchDeployments(selectedId),
          fetchEvents(100, selectedId),
          fetchProgress(selectedId),
          fetchNotes(selectedId),
          fetchInputRequests(selectedId),
          fetchDiscovery(selectedId),
          fetchSecrets(selectedId),
        ]);
        setDetail(d);
        setTasks(t);
        setDeployments(dep);
        setEvents(e);
        setProgress(prog);
        setNotes(n);
        setInputRequests(inputs);
        setDiscovery(disc);
        setSecrets(sec);
        if (disc?.form_fields && Object.keys(intakeAnswers).length === 0) {
          const defaults: Record<string, string | string[]> = {};
          disc.form_fields.forEach((f) => {
            if (f.default) defaults[f.id] = f.default;
          });
          setIntakeAnswers(defaults);
        }
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    }
  }, [selectedId]);

  useEffect(() => {
    if (detail?.state === "INTAKE_PENDING") {
      setTab("intake");
    }
  }, [detail?.state]);

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

  async function handleAddNote(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || !noteText.trim()) return;
    setLoading(true);
    try {
      await addNote(selectedId, noteText, noteType);
      setNoteText("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setLoading(false);
    }
  }

  async function handleRespondInput(requestId: string) {
    if (!selectedId) return;
    const response = inputResponses[requestId]?.trim();
    if (!response) return;
    setLoading(true);
    try {
      await respondToInput(selectedId, requestId, response);
      setInputResponses((prev) => ({ ...prev, [requestId]: "" }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to respond");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmitIntake(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || !discovery) return;
    setLoading(true);
    try {
      await submitIntake(selectedId, intakeAnswers);
      await refresh();
      setTab("overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit intake");
    } finally {
      setLoading(false);
    }
  }

  async function handleSetSecret(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || !secretKey.trim() || !secretValue.trim()) return;
    setLoading(true);
    try {
      await setSecret(selectedId, secretKey, secretValue, secretDesc);
      setSecretKey("");
      setSecretValue("");
      setSecretDesc("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save secret");
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteSecret(keyName: string) {
    if (!selectedId) return;
    setLoading(true);
    try {
      await deleteSecret(selectedId, keyName);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete secret");
    } finally {
      setLoading(false);
    }
  }

  async function handleNotificationClick(notif: Notification) {
    if (!notif.read) {
      await markNotificationRead(notif.id);
      setUnreadCount((c) => Math.max(0, c - 1));
      setNotifications((prev) =>
        prev.map((n) => (n.id === notif.id ? { ...n, read: true } : n))
      );
    }
    setShowNotifications(false);
    if (notif.project_id) setSelectedId(notif.project_id);
    if (notif.action === "secrets") setTab("secrets");
    else if (notif.action === "guidance") setTab("guidance");
    else if (notif.action === "intake") setTab("intake");
    else setTab("overview");
  }

  async function handleMarkAllRead() {
    await markAllNotificationsRead();
    setUnreadCount(0);
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }

  function notificationIcon(type: Notification["type"]): string {
    switch (type) {
      case "env_required": return "🔐";
      case "agent_question": return "❓";
      case "project_finished": return "✅";
      case "intake_ready": return "📋";
      case "review_ready": return "👀";
      default: return "🔔";
    }
  }

  function renderIntakeField(field: IntakeField) {
    const value = intakeAnswers[field.id] ?? "";
    const setValue = (v: string | string[]) =>
      setIntakeAnswers((prev) => ({ ...prev, [field.id]: v }));

    if (field.type === "textarea") {
      return (
        <textarea
          value={typeof value === "string" ? value : ""}
          onChange={(e) => setValue(e.target.value)}
          placeholder={field.placeholder}
          rows={4}
          required={field.required}
        />
      );
    }
    if (field.type === "select") {
      return (
        <select
          value={typeof value === "string" ? value : field.options[0] ?? ""}
          onChange={(e) => setValue(e.target.value)}
          required={field.required}
        >
          {field.options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      );
    }
    if (field.type === "multiselect") {
      const selected = Array.isArray(value) ? value : value ? [value] : [];
      return (
        <div className={styles.multiSelect}>
          {field.options.map((opt) => (
            <label key={opt} className={styles.checkLabel}>
              <input
                type="checkbox"
                checked={selected.includes(opt)}
                onChange={(e) => {
                  if (e.target.checked) setValue([...selected, opt]);
                  else setValue(selected.filter((s) => s !== opt));
                }}
              />
              {opt}
            </label>
          ))}
        </div>
      );
    }
    return (
      <input
        type="text"
        value={typeof value === "string" ? value : ""}
        onChange={(e) => setValue(e.target.value)}
        placeholder={field.placeholder}
        required={field.required}
      />
    );
  }

  const openInputs = inputRequests.filter((r) => r.status === "open");
  const pendingSecrets = secrets?.pending_requirements.length ?? 0;
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
          <div className={styles.notifWrapper}>
            <button
              type="button"
              className={styles.notifBell}
              onClick={() => setShowNotifications((v) => !v)}
              aria-label="Notifications"
            >
              🔔
              {unreadCount > 0 && (
                <span className={styles.notifCount}>{unreadCount > 99 ? "99+" : unreadCount}</span>
              )}
            </button>
            {showNotifications && (
              <div className={styles.notifDropdown}>
                <div className={styles.notifHeader}>
                  <h3>Notifications</h3>
                  {unreadCount > 0 && (
                    <button type="button" className={styles.notifMarkAll} onClick={handleMarkAllRead}>
                      Mark all read
                    </button>
                  )}
                </div>
                <ul className={styles.notifList}>
                  {notifications.length === 0 ? (
                    <li className={styles.notifEmpty}>No notifications yet</li>
                  ) : (
                    notifications.slice(0, 20).map((n) => (
                      <li key={n.id}>
                        <button
                          type="button"
                          className={`${styles.notifItem} ${!n.read ? styles.notifUnread : ""}`}
                          onClick={() => handleNotificationClick(n)}
                        >
                          <span className={styles.notifIcon}>{notificationIcon(n.type)}</span>
                          <div className={styles.notifBody}>
                            <strong>{n.title}</strong>
                            <p>{n.message}</p>
                            <time>{new Date(n.created_at).toLocaleString()}</time>
                          </div>
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            )}
          </div>
          {(openInputs.length > 0 || pendingSecrets > 0) && (
            <span className={styles.alertBadge}>
              {openInputs.length > 0 && `${openInputs.length} question${openInputs.length > 1 ? "s" : ""}`}
              {openInputs.length > 0 && pendingSecrets > 0 && " · "}
              {pendingSecrets > 0 && `${pendingSecrets} secret${pendingSecrets > 1 ? "s" : ""} needed`}
            </span>
          )}
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
                  ) : detail.state === "DISCOVERY" ? (
                    <span className={styles.running}>Discovery agent thinking…</span>
                  ) : detail.state === "INTAKE_PENDING" ? (
                    <button className={styles.btnPrimary} onClick={() => setTab("intake")}>
                      Complete intake form
                    </button>
                  ) : (
                    <>
                      {detail.state !== "PRODUCTION" && detail.state !== "REQUESTED" && (
                        <button className={styles.btnPrimary} onClick={handleRun} disabled={loading}>
                          {detail.state === "PLANNING" ? "Start pipeline" : "Re-run pipeline"}
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

              {progress && (
                <div className={styles.progressDigest}>
                  <div className={styles.progressHeader}>
                    <h3>What&apos;s done</h3>
                    {detail.pipeline_running && (
                      <span className={styles.running}>Building…</span>
                    )}
                  </div>
                  {progress.summary_lines.length === 0 ? (
                    <p className={styles.emptyHint}>Pipeline not started yet — progress will appear here as agents work.</p>
                  ) : (
                    <ul className={styles.progressList}>
                      {progress.summary_lines.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className={styles.tabs}>
                {(["overview", "intake", "guidance", "secrets", "tasks", "artifacts", "deployments", "logs"] as Tab[]).map((t) => (
                  <button
                    key={t}
                    className={tab === t ? styles.tabActive : styles.tab}
                    onClick={() => setTab(t)}
                  >
                    {t === "intake"
                      ? `Intake${detail.state === "INTAKE_PENDING" ? " •" : ""}`
                      : t === "guidance"
                        ? `Notes & Input${openInputs.length ? ` (${openInputs.length})` : ""}`
                        : t === "secrets"
                          ? `Secrets${pendingSecrets ? ` (${pendingSecrets})` : ""}`
                          : t.charAt(0).toUpperCase() + t.slice(1)}
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

              {tab === "intake" && (
                <div className={styles.intakePanel}>
                  {detail.state === "DISCOVERY" || discovery?.status === "generating" ? (
                    <div className={styles.intakeWaiting}>
                      <h3>Discovery agent is working…</h3>
                      <p>Analyzing your idea and preparing a loose plan with follow-up questions.</p>
                    </div>
                  ) : discovery ? (
                    <>
                      <div className={styles.loosePlan}>
                        <h3>Loose plan</h3>
                        <pre>{discovery.loose_plan}</pre>
                      </div>
                      {discovery.status === "awaiting_user" ? (
                        <form className={styles.intakeForm} onSubmit={handleSubmitIntake}>
                          <h3>Scope intake form</h3>
                          <p className={styles.guidanceHint}>
                            Help the factory understand what to build and what to skip. Required fields
                            are marked with *.
                          </p>
                          {discovery.form_fields.map((field) => (
                            <div key={field.id} className={styles.intakeField}>
                              <label>
                                {field.label}
                                {field.required && <span className={styles.required}> *</span>}
                              </label>
                              {field.help && <span className={styles.fieldHelp}>{field.help}</span>}
                              {renderIntakeField(field)}
                            </div>
                          ))}
                          <button type="submit" className={styles.btnPrimary} disabled={loading}>
                            Lock scope & continue
                          </button>
                        </form>
                      ) : (
                        <div className={styles.intakeDone}>
                          <h3>Intake complete</h3>
                          <p>Scope locked in. You can start the build pipeline when ready.</p>
                        </div>
                      )}
                    </>
                  ) : (
                    <p className={styles.emptyHint}>Discovery not started yet.</p>
                  )}
                </div>
              )}

              {tab === "guidance" && (
                <div className={styles.guidancePanel}>
                  <section className={styles.guidanceSection}>
                    <h3>Your notes</h3>
                    <p className={styles.guidanceHint}>
                      Add instructions anytime — running or not. Agents read these on their next step.
                      Use &quot;Out of scope&quot; to block features.
                    </p>
                    <form className={styles.noteForm} onSubmit={handleAddNote}>
                      <select value={noteType} onChange={(e) => setNoteType(e.target.value as NoteType)}>
                        {NOTE_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                      <textarea
                        placeholder="e.g. Don't add user auth — keep it simple. OR: Add export to CSV feature."
                        value={noteText}
                        onChange={(e) => setNoteText(e.target.value)}
                        rows={3}
                      />
                      <button type="submit" className={styles.btnPrimary} disabled={loading || !noteText.trim()}>
                        Add note
                      </button>
                    </form>
                    <ul className={styles.notesList}>
                      {notes.map((n) => (
                        <li key={n.id} className={styles.noteItem}>
                          <span className={styles.noteTypeBadge}>{n.note_type.replace("_", " ")}</span>
                          <p>{n.content}</p>
                          <time>{new Date(n.created_at).toLocaleString()}</time>
                        </li>
                      ))}
                      {notes.length === 0 && <p className={styles.emptyHint}>No notes yet</p>}
                    </ul>
                  </section>

                  <section className={styles.guidanceSection}>
                    <h3>Agent questions</h3>
                    <p className={styles.guidanceHint}>
                      Agents never pause the pipeline. They proceed with a default decision after
                      5 minutes if you don&apos;t respond. You can still override here.
                    </p>
                    {inputRequests.length === 0 ? (
                      <p className={styles.emptyHint}>No agent questions yet</p>
                    ) : (
                      <ul className={styles.inputList}>
                        {inputRequests.map((req) => (
                          <li key={req.id} className={`${styles.inputCard} ${req.status === "open" ? styles.inputOpen : ""}`}>
                            <div className={styles.inputHeader}>
                              <span className={styles.roleBadge}>{req.role}</span>
                              <span className={styles.inputStatus}>{req.status.replace("_", " ")}</span>
                            </div>
                            <p className={styles.inputQuestion}>{req.question}</p>
                            {req.context_detail && (
                              <p className={styles.inputContext}>{req.context_detail}</p>
                            )}
                            {req.options.length > 0 && (
                              <div className={styles.inputOptions}>
                                Options: {req.options.join(" · ")}
                              </div>
                            )}
                            <p className={styles.inputDefault}>
                              <strong>Proceeding with:</strong> {req.resolved_decision ?? req.default_decision}
                            </p>
                            {req.status === "open" && (
                              <div className={styles.inputRespond}>
                                <input
                                  placeholder="Your preference (optional — overrides default)"
                                  value={inputResponses[req.id] ?? ""}
                                  onChange={(e) =>
                                    setInputResponses((prev) => ({ ...prev, [req.id]: e.target.value }))
                                  }
                                />
                                <button
                                  className={styles.btnSecondary}
                                  onClick={() => handleRespondInput(req.id)}
                                  disabled={loading || !inputResponses[req.id]?.trim()}
                                >
                                  Send response
                                </button>
                                <span className={styles.inputExpiry}>
                                  Auto-decides {new Date(req.expires_at).toLocaleTimeString()}
                                </span>
                              </div>
                            )}
                            {req.human_response && (
                              <p className={styles.inputAnswer}>You said: {req.human_response}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </div>
              )}

              {tab === "secrets" && (
                <div className={styles.secretsPanel}>
                  <section className={styles.guidanceSection}>
                    <h3>Environment variables</h3>
                    <p className={styles.guidanceHint}>
                      Secrets are encrypted at rest. Agents see key names only — never values.
                      Set variables here; they are injected at staging deploy time.
                    </p>

                    {(secrets?.pending_requirements.length ?? 0) > 0 && (
                      <div className={styles.pendingSecrets}>
                        <h4>Action required</h4>
                        <ul>
                          {secrets!.pending_requirements.map((req) => (
                            <li key={req.id} className={styles.pendingSecretItem}>
                              <strong>{req.key_name}</strong>
                              <p>{req.description}</p>
                              <span className={styles.pendingMeta}>Requested by {req.requested_by}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <form className={styles.secretForm} onSubmit={handleSetSecret}>
                      <div className={styles.secretFormRow}>
                        <input
                          placeholder="KEY_NAME (e.g. OPENAI_API_KEY)"
                          value={secretKey}
                          onChange={(e) => setSecretKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""))}
                          required
                        />
                        <input
                          type="password"
                          placeholder="Secret value"
                          value={secretValue}
                          onChange={(e) => setSecretValue(e.target.value)}
                          required
                          autoComplete="off"
                        />
                      </div>
                      <input
                        placeholder="Description (optional)"
                        value={secretDesc}
                        onChange={(e) => setSecretDesc(e.target.value)}
                      />
                      <button type="submit" className={styles.btnPrimary} disabled={loading}>
                        Save secret
                      </button>
                    </form>

                    <ul className={styles.secretsList}>
                      {(secrets?.secrets ?? []).map((s) => (
                        <li key={s.key_name} className={styles.secretItem}>
                          <div>
                            <strong>{s.key_name}</strong>
                            <code>{s.masked_value}</code>
                            {s.description && <p>{s.description}</p>}
                          </div>
                          <button
                            type="button"
                            className={styles.btnDanger}
                            onClick={() => handleDeleteSecret(s.key_name)}
                            disabled={loading}
                          >
                            Remove
                          </button>
                        </li>
                      ))}
                      {(secrets?.secrets.length ?? 0) === 0 && (
                        <p className={styles.emptyHint}>No secrets configured yet</p>
                      )}
                    </ul>
                  </section>
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
  if (ev.type === "progress.updated") return `${p.title}: ${p.summary}`;
  if (ev.type === "note.added") return String(p.content ?? "").slice(0, 80);
  if (ev.type === "input.requested") return String(p.question ?? "").slice(0, 80);
  if (ev.type === "input.resolved") return `${p.status}: ${p.decision ?? ""}`.slice(0, 80);
  if (ev.type === "discovery.started") return "Discovery agent started";
  if (ev.type === "discovery.completed") return `Intake form ready (${p.field_count} questions)`;
  if (ev.type === "intake.submitted") return "Scope locked in";
  if (ev.type === "notification.created") return String(p.title ?? "");
  if (ev.type === "env.required") return `Secret needed: ${p.key_name ?? ""}`;
  return JSON.stringify(p).slice(0, 80);
}
