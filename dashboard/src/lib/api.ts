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

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function headers(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  if (typeof window !== "undefined") {
    const key = localStorage.getItem("api_key");
    if (key) h["X-API-Key"] = key;
  }
  return h;
}

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${API_URL}/api/projects`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function fetchProjectDetail(id: string): Promise<ProjectDetail> {
  const res = await fetch(`${API_URL}/api/projects/${id}/detail`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch project detail");
  return res.json();
}

export async function createProject(name: string, description: string): Promise<Project> {
  const res = await fetch(`${API_URL}/api/projects`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) throw new Error("Failed to create project");
  return res.json();
}

export async function fetchDiscovery(projectId: string): Promise<DiscoverySession | null> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/discovery`, {
    cache: "no-store",
    headers: headers(),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to fetch discovery");
  const data = await res.json();
  return data;
}

export async function submitIntake(
  projectId: string,
  responses: Record<string, string | string[]>
): Promise<DiscoverySession> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/discovery/submit`, {
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

export async function runPipeline(projectId: string): Promise<{ status: string }> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/run`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to start pipeline");
  return res.json();
}

export async function promoteProject(projectId: string): Promise<{ production_url: string | null }> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/promote`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to promote");
  }
  return res.json();
}

export async function fetchTasks(): Promise<Task[]> {
  const res = await fetch(`${API_URL}/api/tasks`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch tasks");
  return res.json();
}

export async function fetchProjectTasks(projectId: string): Promise<Task[]> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/tasks`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch tasks");
  return res.json();
}

export async function fetchEvents(limit = 100, projectId?: string): Promise<FactoryEvent[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (projectId) params.set("project_id", projectId);
  const res = await fetch(`${API_URL}/api/events?${params}`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function fetchDeployments(projectId: string): Promise<Deployment[]> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/deployments`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch deployments");
  return res.json();
}

export async function fetchArtifact(projectId: string, name: string): Promise<string> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/artifacts/${name}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch artifact");
  const data = await res.json();
  return data.content;
}

export async function fetchLog(projectId: string, name: string): Promise<string> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/logs/${name}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch log");
  const data = await res.json();
  return data.content;
}

export async function fetchProgress(projectId: string): Promise<ProgressDigest> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/progress`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch progress");
  return res.json();
}

export async function fetchNotes(projectId: string): Promise<ProjectNote[]> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/notes`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch notes");
  return res.json();
}

export async function addNote(
  projectId: string,
  content: string,
  noteType: NoteType = "instruction"
): Promise<ProjectNote> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/notes`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ content, note_type: noteType }),
  });
  if (!res.ok) throw new Error("Failed to add note");
  return res.json();
}

export async function fetchInputRequests(projectId: string): Promise<InputRequest[]> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/input-requests`, {
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
  const res = await fetch(`${API_URL}/api/projects/${projectId}/input-requests/${requestId}/respond`, {
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
  const res = await fetch(`${API_URL}/api/notifications?${params}`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to fetch notifications");
  return res.json();
}

export async function fetchUnreadCount(): Promise<number> {
  const res = await fetch(`${API_URL}/api/notifications/unread-count`, {
    cache: "no-store",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to fetch unread count");
  const data = await res.json();
  return data.count;
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/notifications/${notificationId}/read`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to mark notification read");
}

export async function markAllNotificationsRead(): Promise<void> {
  const res = await fetch(`${API_URL}/api/notifications/read-all`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to mark all read");
}

export async function fetchSecrets(projectId: string): Promise<ProjectSecrets> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/secrets`, {
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
  const res = await fetch(`${API_URL}/api/projects/${projectId}/secrets`, {
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
  const res = await fetch(`${API_URL}/api/projects/${projectId}/secrets/${encodeURIComponent(keyName)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to delete secret");
}

export interface CursorConnectionStatus {
  connected: boolean;
  user_email?: string | null;
  api_key_name?: string | null;
  masked_api_key?: string | null;
  enterprise_billing?: boolean;
  connected_at?: string;
  last_synced_at?: string | null;
  agent_backend?: AgentBackend;
  default_agent_backend?: AgentBackend;
  valid_backends?: AgentBackend[];
  cursor_model?: string;
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
  const res = await fetch(`${API_URL}/api/cursor/status`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch Cursor status");
  return res.json();
}

export async function connectCursor(apiKey: string): Promise<CursorConnectionStatus> {
  const res = await fetch(`${API_URL}/api/cursor/connect`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to connect Cursor");
  }
  return res.json();
}

export async function disconnectCursor(): Promise<void> {
  const res = await fetch(`${API_URL}/api/cursor/disconnect`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to disconnect Cursor");
}

export async function fetchCursorUsage(): Promise<CursorUsage> {
  const res = await fetch(`${API_URL}/api/cursor/usage`, { cache: "no-store", headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch Cursor usage");
  return res.json();
}

export async function updateAgentBackend(agentBackend: AgentBackend): Promise<{
  agent_backend: AgentBackend;
  valid_backends: AgentBackend[];
}> {
  const res = await fetch(`${API_URL}/api/settings/factory/agent-backend`, {
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
  return process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
}
