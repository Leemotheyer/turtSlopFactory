export type ProjectState =
  | "REQUESTED"
  | "DISCOVERY"
  | "INTAKE_PENDING"
  | "PLANNING"
  | "IMPLEMENTING"
  | "UNIT_TESTING"
  | "INTEGRATION_TESTING"
  | "DOCKER_BUILD"
  | "STAGING_DEPLOY"
  | "SMOKE_TESTING"
  | "REVIEW"
  | "PRODUCTION"
  | "DIAGNOSING"
  | "FIXING"
  | "AUTONOMOUSLY_BLOCKED";

export type TaskStatus = "QUEUED" | "RUNNING" | "WAITING" | "COMPLETED" | "FAILED" | "BLOCKED";

export type AgentRole = "architect" | "developer" | "tester" | "reviewer";

export interface Project {
  id: string;
  name: string;
  description: string;
  repo_url: string | null;
  state: ProjectState;
  branch: string;
  base_branch: string;
  work_branch: string | null;
  isolate_branch: boolean;
  merge_status: string | null;
  image_tag: string | null;
  preview_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  staging_url: string | null;
  production_url: string | null;
  preview_url: string | null;
  preview_port: number | null;
  preview_type: string | null;
  preview_status: string | null;
  artifacts: string[];
  pipeline_running: boolean;
  pipeline_paused?: boolean;
  pipeline_paused_at?: string | null;
  failed_gate: string | null;
  failed_substage: string | null;
  discovery_status: string | null;
  intake_ready: boolean;
}

export type IntakeFieldType = "text" | "textarea" | "select" | "multiselect";

export interface IntakeField {
  id: string;
  label: string;
  type: IntakeFieldType;
  help: string;
  placeholder: string;
  options: string[];
  required: boolean;
  default: string | null;
}

export interface DiscoverySession {
  id: string;
  project_id: string;
  status: "generating" | "awaiting_user" | "submitted" | "auto_submitted";
  loose_plan: string;
  form_fields: IntakeField[];
  responses: Record<string, string | string[]>;
  created_at: string;
  submitted_at: string | null;
  expires_at: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  role: AgentRole;
  status: TaskStatus;
  attempt: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
}

export interface FactoryEvent {
  id: string;
  type: string;
  project_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Deployment {
  id: string;
  project_id: string;
  environment: string;
  image_tag: string;
  url: string | null;
  port: number | null;
  status: string;
  created_at: string;
}

export type NoteType = "instruction" | "feature" | "scope_out" | "general";

export interface ProjectNote {
  id: string;
  project_id: string;
  content: string;
  note_type: NoteType;
  created_at: string;
}

export interface ProgressEntry {
  id: string;
  project_id: string;
  category: string;
  title: string;
  summary: string;
  detail: string | null;
  created_at: string;
}

export interface ProgressDigest {
  project_id: string;
  current_state: string;
  pipeline_running: boolean;
  entries: ProgressEntry[];
  summary_lines: string[];
}

export type InputRequestStatus = "open" | "answered" | "auto_resolved";

export type NotificationType =
  | "env_required"
  | "agent_question"
  | "project_finished"
  | "intake_ready"
  | "review_ready"
  | "merge_ready"
  | "pipeline_blocked"
  | "preview_ready";

export interface Notification {
  id: string;
  project_id: string | null;
  type: NotificationType;
  title: string;
  message: string;
  action: string | null;
  reference_id: string | null;
  read: boolean;
  created_at: string;
}

export interface EnvRequirement {
  id: string;
  key_name: string;
  description: string;
  requested_by: string;
  status: string;
}

export interface ProjectSecret {
  key_name: string;
  masked_value: string;
  description: string;
  configured: boolean;
}

export interface ProjectSecrets {
  secrets: ProjectSecret[];
  pending_requirements: EnvRequirement[];
  configured_keys: string[];
}

export interface InputRequest {
  id: string;
  project_id: string;
  task_id: string | null;
  agent_id: string;
  role: string;
  question: string;
  context_detail: string;
  options: string[];
  default_decision: string;
  status: InputRequestStatus;
  human_response: string | null;
  resolved_decision: string | null;
  expires_at: string;
  created_at: string;
  resolved_at: string | null;
}

export interface PublicConfig {
  api_url: string;
  ws_url: string;
  preview_host: string;
  setup_complete: boolean;
  api_key_required: boolean;
  gateway_mode?: boolean;
}

export interface SetupStatus extends PublicConfig {
  api_port: number;
  dashboard_port: number;
  api_key_configured: boolean;
  cursor_connected: boolean;
  github_token_configured?: boolean;
  github_login?: string | null;
  masked_github_token?: string | null;
  github_token_source?: string | null;
  agent_backend: AgentBackend;
  valid_backends: AgentBackend[];
  auto_configured: {
    encryption_key: boolean;
    database: boolean;
  };
}

let publicConfig: PublicConfig | null = null;

function browserOrigin(): string {
  if (typeof window === "undefined") return "http://localhost:8000";
  return window.location.origin;
}

/** Rebase /preview/... links onto the current browser origin (fixes missing :8044 port). */
export function resolvePreviewUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (!parsed.pathname.startsWith("/preview/")) {
      return sanitizeApiUrl(url);
    }
    const origin = browserOrigin().replace(/\/$/, "");
    return `${origin}${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return url;
  }
}

/** Drop stale URLs that point at the internal API port or a different browser origin. */
function sanitizeApiUrl(url: string): string {
  const origin = browserOrigin();
  try {
    const parsed = new URL(url);
    const originParsed = new URL(origin);
    // Internal API port is never exposed in gateway deploys
    if (parsed.port === "8000" && originParsed.port !== "8000") {
      return origin;
    }
    // Stale host from another machine/session (e.g. localhost saved, now on LAN IP)
    if (parsed.hostname !== originParsed.hostname) {
      return origin;
    }
    // Same host but wrong port while browser is on the gateway port
    if (parsed.port !== originParsed.port && originParsed.port && originParsed.port !== "8000") {
      return origin;
    }
  } catch {
    return origin;
  }
  return url;
}

function resolveApiUrlFromConfig(): string {
  const origin = browserOrigin();
  if (publicConfig?.gateway_mode) {
    return origin;
  }
  if (publicConfig?.api_url) {
    return sanitizeApiUrl(publicConfig.api_url);
  }
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("factory_api_url");
    if (saved) return sanitizeApiUrl(saved);
  }
  return origin;
}

async function resolvedApiUrl(): Promise<string> {
  await ensurePublicConfig();
  return resolveApiUrlFromConfig();
}

async function discoverBootstrapUrl(): Promise<string> {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window === "undefined") return "http://localhost:8000";

  try {
    const origin = browserOrigin();
    const res = await fetch(`${origin}/api/settings/public`, { cache: "no-store" });
    if (res.ok) {
      const cfg = (await res.json()) as PublicConfig;
      const apiUrlResolved = cfg.gateway_mode ? origin : sanitizeApiUrl(cfg.api_url || origin);
      publicConfig = {
        ...cfg,
        api_url: apiUrlResolved,
        ws_url: cfg.gateway_mode
          ? origin.replace(/^http/, "ws")
          : cfg.ws_url || apiUrlResolved.replace(/^http/, "ws"),
      };
      localStorage.setItem("factory_api_url", publicConfig.api_url);
      return publicConfig.api_url;
    }
  } catch {
    /* fall through */
  }

  const saved = localStorage.getItem("factory_api_url");
  if (saved) return sanitizeApiUrl(saved);

  return browserOrigin();
}

function apiUrl(): string {
  return resolveApiUrlFromConfig();
}

export async function ensurePublicConfig(): Promise<PublicConfig> {
  if (publicConfig) return publicConfig;
  const bootstrap = await discoverBootstrapUrl();
  try {
    const res = await fetch(`${bootstrap}/api/settings/public`, { cache: "no-store" });
    if (res.ok) {
      const cfg = (await res.json()) as PublicConfig;
      const origin = browserOrigin();
      const apiUrlResolved = cfg.gateway_mode ? origin : sanitizeApiUrl(cfg.api_url || bootstrap);
      publicConfig = {
        ...cfg,
        api_url: apiUrlResolved,
        ws_url: cfg.gateway_mode
          ? origin.replace(/^http/, "ws")
          : cfg.ws_url || apiUrlResolved.replace(/^http/, "ws"),
      };
      if (typeof window !== "undefined") {
        localStorage.setItem("factory_api_url", publicConfig.api_url);
      }
      return publicConfig;
    }
  } catch {
    /* fall through */
  }
  const origin = browserOrigin();
  publicConfig = {
    api_url: sanitizeApiUrl(bootstrap),
    ws_url: sanitizeApiUrl(bootstrap).replace(/^http/, "ws"),
    preview_host: typeof window !== "undefined" ? window.location.hostname : "localhost",
    setup_complete: true,
    api_key_required: false,
    gateway_mode: bootstrap === origin,
  };
  return publicConfig;
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  await ensurePublicConfig();
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/setup`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch setup status");
  return res.json();
}

export async function completeSetup(body: {
  preview_host?: string;
  api_key?: string;
}): Promise<SetupStatus> {
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/setup`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Setup failed");
  }
  publicConfig = null;
  await ensurePublicConfig();
  return res.json();
}

export async function updatePreviewHost(previewHost: string): Promise<SetupStatus> {
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/factory/preview-host`, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify({ preview_host: previewHost }),
  });
  if (!res.ok) throw new Error("Failed to update preview host");
  publicConfig = null;
  return res.json();
}

export async function updateInstanceApiKey(apiKey: string | null): Promise<SetupStatus & { verified?: boolean; message?: string }> {
  const trimmed = apiKey?.trim() || "";
  const authKey = trimmed && !hasStoredFactoryApiKey() ? trimmed : undefined;
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/factory/api-key`, {
    method: "PUT",
    headers: headers(authKey),
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) {
    throw new Error(await parseApiError(res, "Failed to update API key"));
  }
  return res.json();
}

export async function verifyFactoryApiKey(apiKey: string): Promise<{ verified: boolean; message: string }> {
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/verify-key`, {
    cache: "no-store",
    headers: headers(apiKey),
  });
  if (!res.ok) {
    throw new Error(await parseApiError(res, "Factory API key was not accepted"));
  }
  return res.json();
}

export interface GitHubConnectionStatus {
  connected: boolean;
  verified?: boolean;
  message?: string;
  github_login?: string | null;
  masked_github_token?: string | null;
  source?: string;
}

export async function fetchGithubStatus(): Promise<GitHubConnectionStatus> {
  const res = await fetch(`${await resolvedApiUrl()}/api/github/status`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) {
    throw new Error(await parseApiError(res, "Failed to fetch GitHub status"));
  }
  return res.json();
}

export async function connectGithubToken(token: string): Promise<GitHubConnectionStatus> {
  const res = await fetch(`${await resolvedApiUrl()}/api/github/connect`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ token }),
  });
  if (!res.ok) {
    throw new Error(await parseApiError(res, "Failed to connect GitHub"));
  }
  return res.json();
}

export async function disconnectGithubToken(): Promise<void> {
  const res = await fetch(`${await resolvedApiUrl()}/api/github/disconnect`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) {
    throw new Error(await parseApiError(res, "Failed to disconnect GitHub"));
  }
}

function headers(overrideApiKey?: string | null): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  if (typeof window !== "undefined") {
    const key = overrideApiKey ?? localStorage.getItem("api_key");
    if (key) h["X-API-Key"] = key;
  }
  return h;
}

async function parseApiError(res: Response, fallback: string): Promise<string> {
  try {
    const err = await res.json();
    const detail = (err as { detail?: string | { msg?: string }[] }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  } catch {
    /* ignore */
  }
  if (res.status === 401) {
    return "Factory API key required or invalid — enter it in the Cursor menu under Deployment.";
  }
  if (res.status === 403) {
    return "Access denied — check your factory API key.";
  }
  return fallback;
}

export function hasStoredFactoryApiKey(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean(localStorage.getItem("api_key")?.trim());
}

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function fetchProjectDetail(id: string): Promise<ProjectDetail> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${id}/detail`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch project detail");
  return res.json();
}

export async function createProject(
  name: string,
  description: string,
  options?: { repo_url?: string | null; branch?: string; base_branch?: string; isolate_branch?: boolean }
): Promise<Project> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      name,
      description,
      repo_url: options?.repo_url || null,
      branch: options?.branch || options?.base_branch || "main",
      base_branch: options?.base_branch || options?.branch || "main",
      isolate_branch: options?.isolate_branch ?? true,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to create project");
  }
  return res.json();
}

export async function updateProjectRepo(
  projectId: string,
  params: {
    repo_url?: string | null;
    branch?: string;
    base_branch?: string;
    work_branch?: string;
    isolate_branch?: boolean;
    clear_repo?: boolean;
  }
): Promise<Project> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to update repository");
  }
  return res.json();
}

export interface GithubRepository {
  url: string;
  name: string;
}

export interface GithubRepositoriesResponse {
  connected: boolean;
  repositories: GithubRepository[];
  cached?: boolean;
  note?: string;
  error?: string;
}

export async function fetchGithubRepos(refresh = false): Promise<GithubRepositoriesResponse> {
  const query = refresh ? "?refresh=true" : "";
  const res = await fetch(`${await resolvedApiUrl()}/api/cursor/repositories${query}`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to fetch GitHub repositories");
  }
  return res.json();
}

export async function fetchDiscovery(projectId: string): Promise<DiscoverySession | null> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/discovery`, {
    cache: "no-store",
    headers: headers(),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to fetch discovery");
  const data = await res.json();
  return data;
}

export async function startDiscovery(projectId: string): Promise<DiscoverySession> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/discovery`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to start discovery");
  }
  return res.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to delete project");
  }
}

export async function submitIntake(
  projectId: string,
  responses: Record<string, string | string[]>
): Promise<DiscoverySession> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/discovery/submit`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ responses }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to submit intake");
  }
  return res.json();
}

export async function runPipeline(projectId: string): Promise<{ status: string; mode?: string }> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/run`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to start pipeline");
  }
  return res.json();
}

export async function stopPipeline(projectId: string): Promise<{ status: string }> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/stop`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to stop pipeline");
  }
  return res.json();
}

export interface AgentActivityItem {
  task_id: string;
  title: string;
  description: string;
  role: string;
  status: string;
  started_at: string;
  updated_at?: string;
  output_preview?: string | null;
  agent_id?: string | null;
  cursor_url?: string | null;
  live_status?: string | null;
  live_detail?: string | null;
}

export interface AgentActivityFeedItem {
  id: string;
  type: string;
  task_id: string | null;
  agent_id: string | null;
  created_at: string;
  summary: string;
  detail: string | null;
  cursor_url: string | null;
}

export interface AgentActivity {
  project_id: string;
  current_state: string;
  pipeline_running: boolean;
  stop_requested: boolean;
  active_agents: AgentActivityItem[];
  live_agents: Record<string, unknown>[];
  recent_tasks: AgentActivityItem[];
  activity_feed: AgentActivityFeedItem[];
  progress_entries: ProgressEntry[];
  pipeline_log_tail: string;
}

export async function fetchAgentActivity(projectId: string): Promise<AgentActivity> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/agent-activity`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to fetch agent activity");
  return res.json();
}

export async function promoteProject(projectId: string): Promise<{ production_url: string | null }> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/promote`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to promote");
  }
  return res.json();
}

export async function mergeToMain(
  projectId: string
): Promise<{ status: string; message: string; base_branch: string; work_branch: string }> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/merge-to-main`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to merge to main");
  }
  return res.json();
}

export async function fetchTasks(): Promise<Task[]> {
  const res = await fetch(`${await resolvedApiUrl()}/api/tasks`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch tasks");
  return res.json();
}

export async function fetchProjectTasks(projectId: string): Promise<Task[]> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/tasks`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch tasks");
  return res.json();
}

export async function fetchEvents(limit = 100, projectId?: string): Promise<FactoryEvent[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (projectId) params.set("project_id", projectId);
  const res = await fetch(`${await resolvedApiUrl()}/api/events?${params}`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function fetchDeployments(projectId: string): Promise<Deployment[]> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/deployments`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch deployments");
  return res.json();
}

export async function fetchArtifact(projectId: string, name: string): Promise<string> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/artifacts/${name}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch artifact");
  const data = await res.json();
  return data.content;
}

export async function fetchLog(projectId: string, name: string): Promise<string> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/logs/${name}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch log");
  const data = await res.json();
  return data.content;
}

export async function fetchProgress(projectId: string): Promise<ProgressDigest> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/progress`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch progress");
  return res.json();
}

export async function fetchNotes(projectId: string): Promise<ProjectNote[]> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/notes`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch notes");
  return res.json();
}

export async function addNote(
  projectId: string,
  content: string,
  noteType: NoteType = "instruction"
): Promise<ProjectNote> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/notes`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ content, note_type: noteType }),
  });
  if (!res.ok) throw new Error("Failed to add note");
  return res.json();
}

export async function fetchInputRequests(projectId: string): Promise<InputRequest[]> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/input-requests`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to fetch input requests");
  return res.json();
}

export async function respondToInput(
  projectId: string,
  requestId: string,
  response: string
): Promise<InputRequest> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/input-requests/${requestId}/respond`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ response }),
  });
  if (!res.ok) throw new Error("Failed to respond");
  return res.json();
}

export async function fetchNotifications(unreadOnly = false): Promise<Notification[]> {
  const params = new URLSearchParams();
  if (unreadOnly) params.set("unread_only", "true");
  const res = await fetch(`${await resolvedApiUrl()}/api/notifications?${params}`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to fetch notifications");
  return res.json();
}

export async function fetchUnreadCount(): Promise<number> {
  const res = await fetch(`${await resolvedApiUrl()}/api/notifications/unread-count`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to fetch unread count");
  const data = await res.json();
  return data.count;
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  const res = await fetch(`${await resolvedApiUrl()}/api/notifications/${notificationId}/read`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to mark notification read");
}

export async function markAllNotificationsRead(): Promise<void> {
  const res = await fetch(`${await resolvedApiUrl()}/api/notifications/read-all`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to mark all read");
}

export async function fetchSecrets(projectId: string): Promise<ProjectSecrets> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/secrets`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to fetch secrets");
  return res.json();
}

export async function setSecret(
  projectId: string,
  keyName: string,
  value: string,
  description = ""
): Promise<ProjectSecret> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/secrets`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ key_name: keyName, value, description }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to set secret");
  }
  return res.json();
}

export async function deleteSecret(projectId: string, keyName: string): Promise<void> {
  const res = await fetch(`${await resolvedApiUrl()}/api/projects/${projectId}/secrets/${encodeURIComponent(keyName)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to delete secret");
}

export interface ConcurrencyBudget {
  max_parallel: number;
  active_cursor_agents: number;
  cursor_slot_limit: number;
  available_cursor_slots: number;
  backend: AgentBackend;
  factory_cap: number;
  strategy: string;
  idle_agents?: number;
}

export interface CursorConnectionStatus {
  connected: boolean;
  verified?: boolean;
  message?: string;
  models_available?: number;
  user_email?: string | null;
  api_key_name?: string | null;
  masked_api_key?: string | null;
  enterprise_billing?: boolean;
  connected_at?: string;
  last_synced_at?: string | null;
  agent_backend?: AgentBackend;
  default_agent_backend?: AgentBackend;
  valid_backends?: AgentBackend[];
  agent_model?: string;
  agent_models?: AgentRoleModels;
  default_agent_model?: string;
  cursor_model?: string;
  max_parallel_agents?: number;
  cursor_concurrent_limit?: number;
  concurrency?: ConcurrencyBudget;
}

export interface CursorModel {
  id: string;
  display_name: string;
  description?: string | null;
  aliases?: string[];
  default_params?: { id: string; value: string }[] | null;
}

export interface CursorModelsResponse {
  connected: boolean;
  models: CursorModel[];
  note?: string;
  error?: string;
}

export type AgentRoleModelKey = "architect" | "developer" | "reviewer";

export interface AgentRoleModels {
  architect: string;
  developer: string;
  reviewer: string;
}

export type AgentBackend = "cursor_cloud" | "cursor_local" | "local";

export interface CursorTokenUsage {
  input_tokens: number;
  output_tokens: number;
  cache_write_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
}

export interface CursorAgentSummary {
  id: string;
  name: string | null;
  status: string | null;
  url: string | null;
  created_at: string | null;
  total_tokens: number;
}

export interface CursorUsage {
  connected: boolean;
  user_email?: string | null;
  api_key_name?: string | null;
  enterprise_billing?: boolean;
  spend_cents?: number | null;
  overall_spend_cents?: number | null;
  spend_limit_dollars?: number | null;
  remaining_budget_dollars?: number | null;
  subscription_cycle_start?: string | null;
  tokens?: CursorTokenUsage;
  agents?: CursorAgentSummary[];
  note?: string | null;
  error?: string;
}

export async function fetchCursorStatus(): Promise<CursorConnectionStatus> {
  const res = await fetch(`${await resolvedApiUrl()}/api/cursor/status`, { cache: "no-store", headers: headers() });
  if (!res.ok) {
    throw new Error(await parseApiError(res, "Failed to fetch Cursor status"));
  }
  return res.json();
}

export async function connectCursor(apiKey: string): Promise<CursorConnectionStatus> {
  const res = await fetch(`${await resolvedApiUrl()}/api/cursor/connect`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) {
    throw new Error(await parseApiError(res, "Failed to connect Cursor"));
  }
  return res.json();
}

export async function disconnectCursor(): Promise<void> {
  const res = await fetch(`${await resolvedApiUrl()}/api/cursor/disconnect`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to disconnect Cursor");
}

export async function fetchCursorUsage(): Promise<CursorUsage> {
  const res = await fetch(`${await resolvedApiUrl()}/api/cursor/usage`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch Cursor usage");
  return res.json();
}

export async function updateAgentBackend(agentBackend: AgentBackend): Promise<{
  agent_backend: AgentBackend;
  valid_backends: AgentBackend[];
  agent_model?: string;
}> {
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/factory/agent-backend`, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify({ agent_backend: agentBackend }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to update agent backend");
  }
  return res.json();
}

export async function updateAgentModel(agentModel: string): Promise<{
  agent_model: string;
  agent_models?: AgentRoleModels;
  default_agent_model?: string;
}> {
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/factory/agent-model`, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify({ agent_model: agentModel }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to update agent model");
  }
  return res.json();
}

export async function updateAgentModels(
  models: Partial<AgentRoleModels>
): Promise<{
  agent_models: AgentRoleModels;
  agent_model: string;
}> {
  const res = await fetch(`${await resolvedApiUrl()}/api/settings/factory/agent-models`, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify(models),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to update agent models");
  }
  return res.json();
}

export async function fetchCursorModels(): Promise<CursorModelsResponse> {
  const res = await fetch(`${await resolvedApiUrl()}/api/cursor/models`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to fetch Cursor models");
  }
  return res.json();
}

export function agentBackendLabel(backend: AgentBackend): string {
  switch (backend) {
    case "cursor_cloud":
      return "Cursor Cloud Agents";
    case "cursor_local":
      return "Cursor Local Agents";
    case "local":
      return "Local scaffold (no API)";
    default:
      return backend;
  }
}

export function getWebSocketUrl(): string {
  if (publicConfig?.gateway_mode) {
    return browserOrigin().replace(/^http/, "ws");
  }
  if (publicConfig?.ws_url) return publicConfig.ws_url;
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  return browserOrigin().replace(/^http/, "ws");
}
