/**
 * turtSlopFactory static dashboard — vanilla JS client for the factory API.
 */

const API = "/api";
const STATE_COLORS = {
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

const PIPELINE = [
  "REQUESTED", "DISCOVERY", "INTAKE_PENDING", "PLANNING", "IMPLEMENTING",
  "UNIT_TESTING", "INTEGRATION_TESTING", "DOCKER_BUILD", "STAGING_DEPLOY",
  "SMOKE_TESTING", "REVIEW", "PRODUCTION",
];

const state = {
  projects: [],
  selectedId: null,
  detail: null,
  tasks: [],
  events: [],
  progress: null,
  discovery: null,
  notifications: [],
  unreadCount: 0,
  intakeAnswers: {},
  connected: false,
  loading: false,
  mobilePanel: "status",
  activeTab: "overview",
  showNotifications: false,
  refreshTimer: null,
};

function $(sel) {
  return document.querySelector(sel);
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text ?? "";
  return d.innerHTML;
}

function headers() {
  const h = { "Content-Type": "application/json" };
  const key = localStorage.getItem("api_key");
  if (key) h["X-API-Key"] = key;
  return h;
}

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: { ...headers(), ...(opts.headers || {}) },
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      if (err.detail) msg = typeof err.detail === "string" ? err.detail : err.detail[0]?.msg || msg;
    } catch { /* ignore */ }
    const error = new Error(msg);
    error.status = res.status;
    throw error;
  }
  if (res.status === 204) return null;
  return res.json();
}

function showError(msg) {
  const el = $("#error-banner");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 8000);
}

function formatEvent(ev) {
  const p = ev.payload || {};
  switch (ev.type) {
    case "state.transition": return `${p.from ?? "—"} → ${p.to}`;
    case "task.status.changed": return String(p.title ?? p.status ?? "");
    case "test.completed": return `${p.stage}: ${p.passed ? "PASS" : "FAIL"}`;
    case "deployment.finished": return p.url ? `${p.environment} preview: ${p.url}` : `${p.environment} deploy`;
    case "progress.updated": return `${p.title}: ${p.summary}`;
    case "discovery.completed": return `Intake form ready (${p.field_count} questions)`;
    case "intake.submitted": return "Scope locked in";
    default: return JSON.stringify(p).slice(0, 80);
  }
}

function stateLabel(s) {
  return s.replace(/_/g, " ");
}

function renderProjectList() {
  const list = $("#project-list");
  if (!list) return;

  if (state.projects.length === 0) {
    list.innerHTML = '<li><p class="empty">No projects yet — describe your app below.</p></li>';
    return;
  }

  list.innerHTML = state.projects.map((p) => {
    const active = p.id === state.selectedId ? "active" : "";
    const color = STATE_COLORS[p.state] || "#6b7280";
    const preview = p.preview_url
      ? `<a href="${escapeHtml(p.preview_url)}" target="_blank" rel="noreferrer" class="preview-link" onclick="event.stopPropagation()">↗</a>`
      : "";
    return `<li>
      <button type="button" class="project-btn ${active}" data-id="${p.id}">
        <span class="project-name">${escapeHtml(p.name)}</span>
        <span class="project-meta">
          <span class="state-tag" style="background:${color}">${stateLabel(p.state)}</span>
          ${preview}
        </span>
      </button>
    </li>`;
  }).join("");

  list.querySelectorAll(".project-btn").forEach((btn) => {
    btn.addEventListener("click", () => selectProject(btn.dataset.id));
  });
}

function renderPipeline() {
  const el = $("#pipeline-steps");
  if (!el || !state.detail) return;
  const currentIdx = PIPELINE.indexOf(state.detail.state);
  el.innerHTML = PIPELINE.map((s, i) => {
    const cls = [
      "step",
      currentIdx > i ? "done" : "",
      state.detail.state === s ? "active" : "",
    ].filter(Boolean).join(" ");
    return `<span class="${cls}">${stateLabel(s)}</span>`;
  }).join("");
}

function renderTasks() {
  const el = $("#tasks-body");
  if (!el) return;
  if (state.tasks.length === 0) {
    el.innerHTML = '<p class="empty">No tasks yet — agents will appear here once the pipeline runs.</p>';
    return;
  }
  el.innerHTML = `<table class="task-table">
    <thead><tr><th>Task</th><th>Role</th><th>Status</th></tr></thead>
    <tbody>${state.tasks.map((t) => `
      <tr>
        <td>${escapeHtml(t.title)}</td>
        <td><span class="role-badge">${escapeHtml(t.role)}</span></td>
        <td>${escapeHtml(t.status)}</td>
      </tr>`).join("")}
    </tbody>
  </table>`;
}

function renderEvents() {
  const list = $("#event-list");
  if (!list) return;
  const items = [...state.events].reverse().slice(0, 50);
  if (items.length === 0) {
    list.innerHTML = '<li><p class="empty">Waiting for events…</p></li>';
    return;
  }
  list.innerHTML = items.map((ev) => `
    <li class="event-item">
      <span class="event-type">${escapeHtml(ev.type)}</span>
      <div>${escapeHtml(formatEvent(ev))}</div>
      <time>${new Date(ev.created_at).toLocaleTimeString()}</time>
    </li>`).join("");
}

function renderIntakeField(field) {
  const val = state.intakeAnswers[field.id] ?? field.default ?? "";
  if (field.type === "textarea") {
    return `<textarea data-field="${field.id}" rows="4" placeholder="${escapeHtml(field.placeholder)}" ${field.required ? "required" : ""}>${escapeHtml(typeof val === "string" ? val : "")}</textarea>`;
  }
  if (field.type === "select") {
    const opts = (field.options || []).map((o) =>
      `<option value="${escapeHtml(o)}" ${o === val ? "selected" : ""}>${escapeHtml(o)}</option>`
    ).join("");
    return `<select data-field="${field.id}" ${field.required ? "required" : ""}>${opts}</select>`;
  }
  if (field.type === "multiselect") {
    const selected = Array.isArray(val) ? val : val ? [val] : [];
    return `<div class="multi-select">${(field.options || []).map((o) => `
      <label><input type="checkbox" data-field="${field.id}" data-multi value="${escapeHtml(o)}" ${selected.includes(o) ? "checked" : ""} /> ${escapeHtml(o)}</label>`).join("")}</div>`;
  }
  return `<input type="text" data-field="${field.id}" value="${escapeHtml(typeof val === "string" ? val : "")}" placeholder="${escapeHtml(field.placeholder)}" ${field.required ? "required" : ""} />`;
}

function renderIntake() {
  const el = $("#intake-panel");
  if (!el) return;

  if (!state.detail) {
    el.innerHTML = "";
    return;
  }

  if (state.detail.state === "DISCOVERY" || state.discovery?.status === "generating") {
    el.innerHTML = `<div class="intake-box">
      <h3>Discovery agent is working…</h3>
      <p class="empty">Analyzing your idea and preparing a scope intake form. Check back in a few minutes.</p>
    </div>`;
    return;
  }

  if (!state.discovery) {
    el.innerHTML = '<p class="empty">Discovery not started yet.</p>';
    return;
  }

  if (state.discovery.status !== "awaiting_user") {
    el.innerHTML = `<div class="intake-box"><h3>Intake complete</h3><p class="empty">Scope locked in — agents will continue autonomously.</p></div>`;
    return;
  }

  const fields = (state.discovery.form_fields || []).map((f) => `
    <div class="intake-field">
      <label>${escapeHtml(f.label)}${f.required ? " *" : ""}</label>
      ${f.help ? `<span class="field-help">${escapeHtml(f.help)}</span>` : ""}
      ${renderIntakeField(f)}
    </div>`).join("");

  el.innerHTML = `
    <div class="loose-plan intake-box">
      <h3>Loose plan</h3>
      <pre>${escapeHtml(state.discovery.loose_plan || "")}</pre>
    </div>
    <form id="intake-form" class="intake-box">
      <h3>Scope intake</h3>
      <p class="field-help">Answer what you can — leave the rest; agents proceed with defaults after a timeout.</p>
      ${fields}
      <button type="submit" class="btn btn-primary" ${state.loading ? "disabled" : ""}>Lock scope &amp; continue</button>
    </form>`;

  $("#intake-form")?.addEventListener("submit", submitIntake);
}

function renderMain() {
  const el = $("#main-content");
  if (!el) return;

  $("#project-count").textContent = `${state.projects.length} projects`;

  if (!state.detail) {
    el.innerHTML = `<div class="welcome">
      <h2>Welcome to turtSlopFactory</h2>
      <p>Describe an app in the sidebar and walk away — agents plan, build, test, and deploy while you check in occasionally.</p>
      <ol>
        <li>Enter a name and short description</li>
        <li>Agents run discovery and intake automatically</li>
        <li>Come back to watch progress or approve promotion</li>
      </ol>
    </div>`;
    return;
  }

  const d = state.detail;
  const livePreview = d.preview_url || d.staging_url;
  const currentIdx = PIPELINE.indexOf(d.state);

  let actions = "";
  if (d.pipeline_running) {
    actions = '<span class="running">Pipeline running…</span>';
  } else if (d.state === "DISCOVERY") {
    actions = '<span class="running">Discovery agent thinking…</span>';
  } else if (d.state === "INTAKE_PENDING") {
    actions = '<button type="button" class="btn btn-primary" id="btn-intake">Complete intake</button>';
  } else {
    if (d.state !== "PRODUCTION" && d.state !== "REQUESTED") {
      actions += `<button type="button" class="btn btn-primary" id="btn-run">${d.state === "PLANNING" ? "Start pipeline" : "Re-run pipeline"}</button>`;
    }
    if (d.state === "REVIEW") {
      actions += '<button type="button" class="btn btn-success" id="btn-promote">Promote to production</button>';
    }
  }

  const progressHtml = state.progress?.summary_lines?.length
    ? `<ul class="progress-list">${state.progress.summary_lines.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}</ul>`
    : '<p class="empty">Progress will appear here as agents work.</p>';

  const previewHtml = livePreview ? `
    <div class="preview-box">
      <h3>Live preview</h3>
      <p class="field-help">${d.pipeline_running ? "Updating as agents work" : "Ready to open"}</p>
      <a href="${escapeHtml(livePreview)}" target="_blank" rel="noreferrer" class="btn btn-primary">Open web app ↗</a>
    </div>` : "";

  el.innerHTML = `
    <div class="project-top">
      <div>
        <h2>${escapeHtml(d.name)}</h2>
        <p>${escapeHtml(d.description)}</p>
      </div>
      <div class="actions">${actions}</div>
    </div>
    ${previewHtml}
    <div class="progress-box">
      <h3>What&apos;s done</h3>
      ${progressHtml}
    </div>
    <div class="tabs" id="tabs">
      <button type="button" class="tab ${state.activeTab === "overview" ? "active" : ""}" data-tab="overview">Overview</button>
      <button type="button" class="tab ${state.activeTab === "intake" ? "active" : ""}" data-tab="intake">Intake</button>
      <button type="button" class="tab ${state.activeTab === "tasks" ? "active" : ""}" data-tab="tasks">Tasks</button>
    </div>
    <div class="tab-panel ${state.activeTab === "overview" ? "active" : ""}" id="tab-overview">
      <div class="pipeline" id="pipeline-steps"></div>
    </div>
    <div class="tab-panel ${state.activeTab === "intake" ? "active" : ""}" id="tab-intake">
      <div id="intake-panel"></div>
    </div>
    <div class="tab-panel ${state.activeTab === "tasks" ? "active" : ""}" id="tab-tasks">
      <div id="tasks-body"></div>
    </div>`;

  renderPipeline();
  renderIntake();
  renderTasks();

  $("#btn-run")?.addEventListener("click", runPipeline);
  $("#btn-promote")?.addEventListener("click", promoteProject);
  $("#btn-intake")?.addEventListener("click", () => { state.activeTab = "intake"; renderMain(); });

  $("#tabs")?.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeTab = tab.dataset.tab;
      renderMain();
    });
  });
}

function renderNotifications() {
  const countEl = $("#notif-count");
  if (countEl) {
    if (state.unreadCount > 0) {
      countEl.textContent = state.unreadCount > 99 ? "99+" : state.unreadCount;
      countEl.classList.remove("hidden");
    } else {
      countEl.classList.add("hidden");
    }
  }

  const dropdown = $("#notif-dropdown");
  if (!dropdown) return;

  if (!state.showNotifications) {
    dropdown.classList.add("hidden");
    return;
  }
  dropdown.classList.remove("hidden");

  const items = state.notifications.slice(0, 20);
  dropdown.innerHTML = `
    <div class="notif-header"><h3>Notifications</h3></div>
    <ul class="notif-list">${items.length === 0
      ? '<li><p class="empty" style="padding:1rem">No notifications yet</p></li>'
      : items.map((n) => `
        <li><button type="button" class="notif-item ${n.read ? "" : "unread"}" data-id="${n.id}" data-project="${n.project_id || ""}">
          <strong>${escapeHtml(n.title)}</strong>
          <p>${escapeHtml(n.message)}</p>
          <time>${new Date(n.created_at).toLocaleString()}</time>
        </button></li>`).join("")}
    </ul>`;

  dropdown.querySelectorAll(".notif-item").forEach((btn) => {
    btn.addEventListener("click", () => handleNotification(btn.dataset.id, btn.dataset.project));
  });
}

function setMobilePanel(panel) {
  state.mobilePanel = panel;
  document.querySelectorAll(".panel").forEach((p) => {
    p.classList.toggle("active", p.dataset.panel === panel);
  });
  document.querySelectorAll(".mobile-nav button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.panel === panel);
  });
}

async function selectProject(id) {
  state.selectedId = id;
  state.activeTab = "overview";
  state.intakeAnswers = {};
  setMobilePanel("status");
  await refresh();
}

async function refresh() {
  try {
    state.projects = await api("/projects");
    if (!state.selectedId && state.projects.length > 0) {
      state.selectedId = state.projects[0].id;
    }

    const [notifs, unread] = await Promise.all([
      api("/notifications"),
      api("/notifications/unread-count"),
    ]);
    state.notifications = notifs;
    state.unreadCount = unread.count ?? 0;

    if (state.selectedId) {
      const pid = state.selectedId;
      let discovery = null;
      try {
        discovery = await api(`/projects/${pid}/discovery`);
      } catch (err) {
        if (err.status !== 404) throw err;
      }
      const [detail, tasks, events, progress] = await Promise.all([
        api(`/projects/${pid}/detail`),
        api(`/projects/${pid}/tasks`),
        api(`/events?limit=100&project_id=${pid}`),
        api(`/projects/${pid}/progress`),
      ]);
      state.detail = detail;
      state.tasks = tasks;
      state.events = events;
      state.progress = progress;
      state.discovery = discovery;

      if (discovery?.form_fields && Object.keys(state.intakeAnswers).length === 0) {
        const defaults = {};
        discovery.form_fields.forEach((f) => { if (f.default) defaults[f.id] = f.default; });
        state.intakeAnswers = defaults;
      }

      if (detail.state === "INTAKE_PENDING") {
        state.activeTab = "intake";
      }
    } else {
      state.detail = null;
    }

    renderProjectList();
    renderMain();
    renderEvents();
    renderNotifications();
  } catch (err) {
    showError(err.message || "Failed to load data");
  }
}

async function createProject(e) {
  e.preventDefault();
  const name = $("#new-name")?.value?.trim();
  const desc = $("#new-desc")?.value?.trim() || "";
  if (!name) return;

  state.loading = true;
  try {
    const p = await api("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description: desc, isolate_branch: true }),
    });
    $("#new-name").value = "";
    $("#new-desc").value = "";
    state.selectedId = p.id;
    await refresh();
  } catch (err) {
    showError(err.message || "Create failed");
  } finally {
    state.loading = false;
  }
}

async function runPipeline() {
  if (!state.selectedId) return;
  state.loading = true;
  try {
    await api(`/projects/${state.selectedId}/run`, { method: "POST" });
    await refresh();
  } catch (err) {
    showError(err.message || "Pipeline start failed");
  } finally {
    state.loading = false;
  }
}

async function promoteProject() {
  if (!state.selectedId) return;
  state.loading = true;
  try {
    await api(`/projects/${state.selectedId}/promote`, { method: "POST" });
    await refresh();
  } catch (err) {
    showError(err.message || "Promote failed");
  } finally {
    state.loading = false;
  }
}

async function submitIntake(e) {
  e.preventDefault();
  if (!state.selectedId || !state.discovery) return;

  const form = e.target;
  form.querySelectorAll("[data-field]").forEach((el) => {
    const id = el.dataset.field;
    if (el.type === "checkbox" && el.dataset.multi !== undefined) {
      if (!state.intakeAnswers[id]) state.intakeAnswers[id] = [];
      if (el.checked && !state.intakeAnswers[id].includes(el.value)) {
        state.intakeAnswers[id].push(el.value);
      }
    } else if (el.type !== "checkbox") {
      state.intakeAnswers[id] = el.value;
    }
  });

  form.querySelectorAll("[data-multi]").forEach((el) => {
    const id = el.dataset.field;
    if (!Array.isArray(state.intakeAnswers[id])) state.intakeAnswers[id] = [];
  });

  state.loading = true;
  try {
    await api(`/projects/${state.selectedId}/discovery/submit`, {
      method: "POST",
      body: JSON.stringify({ responses: state.intakeAnswers }),
    });
    state.activeTab = "overview";
    await refresh();
  } catch (err) {
    showError(err.message || "Intake submit failed");
  } finally {
    state.loading = false;
  }
}

async function handleNotification(id, projectId) {
  try {
    await api(`/notifications/${id}/read`, { method: "POST" });
    state.showNotifications = false;
    if (projectId) {
      state.selectedId = projectId;
      setMobilePanel("status");
    }
    await refresh();
  } catch { /* ignore */ }
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/events`);

  ws.onopen = () => {
    state.connected = true;
    $("#live-status")?.classList.add("live");
  };
  ws.onclose = () => {
    state.connected = false;
    $("#live-status")?.classList.remove("live");
    setTimeout(connectWebSocket, 5000);
  };
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "ping") return;
    state.events = [...state.events.slice(-199), data];
    renderEvents();
    if (state.refreshTimer) clearTimeout(state.refreshTimer);
    state.refreshTimer = setTimeout(refresh, 400);
  };
}

function init() {
  $("#create-form")?.addEventListener("submit", createProject);

  $("#notif-btn")?.addEventListener("click", () => {
    state.showNotifications = !state.showNotifications;
    $("#backdrop")?.classList.toggle("hidden", !state.showNotifications);
    renderNotifications();
  });

  $("#backdrop")?.addEventListener("click", () => {
    state.showNotifications = false;
    $("#backdrop")?.classList.add("hidden");
    renderNotifications();
  });

  document.querySelectorAll(".mobile-nav button").forEach((btn) => {
    btn.addEventListener("click", () => setMobilePanel(btn.dataset.panel));
  });

  setMobilePanel("status");
  refresh();
  connectWebSocket();

  setInterval(() => {
    refresh();
  }, state.detail?.pipeline_running ? 3000 : 15000);
}

document.addEventListener("DOMContentLoaded", init);
