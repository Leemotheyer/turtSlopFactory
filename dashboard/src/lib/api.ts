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

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${API_URL}/api/projects`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function createProject(name: string, description: string): Promise<Project> {
  const res = await fetch(`${API_URL}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) throw new Error("Failed to create project");
  return res.json();
}

export async function fetchTasks(): Promise<Task[]> {
  const res = await fetch(`${API_URL}/api/tasks`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch tasks");
  return res.json();
}

export async function fetchEvents(limit = 50): Promise<FactoryEvent[]> {
  const res = await fetch(`${API_URL}/api/events?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function advanceProject(projectId: string): Promise<Project> {
  const res = await fetch(`${API_URL}/api/projects/${projectId}/advance`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to advance project");
  return res.json();
}

export function getWebSocketUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
}
