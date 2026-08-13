export type ProjectState =
  | "REQUESTED"
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
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  staging_url: string | null;
  production_url: string | null;
  artifacts: string[];
  pipeline_running: boolean;
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

export function getWebSocketUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
}
