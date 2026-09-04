export const PIPELINE_STATES = [
  "REQUESTED",
  "DISCOVERY",
  "INTAKE_PENDING",
  "PLANNING",
  "IMPLEMENTING",
  "INTEGRATION_TESTING",
  "DOCKER_BUILD",
  "STAGING_DEPLOY",
  "SMOKE_TESTING",
  "REVIEW",
  "PRODUCTION",
] as const;

export type PipelineState = (typeof PIPELINE_STATES)[number];

export const PIPELINE_PHASES: {
  id: string;
  label: string;
  states: PipelineState[];
}[] = [
  { id: "discover", label: "Discover", states: ["REQUESTED", "DISCOVERY", "INTAKE_PENDING"] },
  { id: "plan", label: "Plan", states: ["PLANNING"] },
  {
    id: "build",
    label: "Build",
    states: ["IMPLEMENTING", "INTEGRATION_TESTING"],
  },
  {
    id: "ship",
    label: "Ship",
    states: ["DOCKER_BUILD", "STAGING_DEPLOY", "SMOKE_TESTING"],
  },
  { id: "review", label: "Review", states: ["REVIEW"] },
  { id: "live", label: "Live", states: ["PRODUCTION"] },
];

export const STATE_COLORS: Record<string, string> = {
  REQUESTED: "#6b7280",
  DISCOVERY: "#5b8def",
  INTAKE_PENDING: "#f5a623",
  PLANNING: "#5b8def",
  IMPLEMENTING: "#5b8def",
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

export const AUTO_START_PIPELINE_STATES = new Set([
  "PLANNING",
  "DIAGNOSING",
  "FIXING",
  "IMPLEMENTING",
  "INTEGRATION_TESTING",
  "DOCKER_BUILD",
  "STAGING_DEPLOY",
  "SMOKE_TESTING",
]);

export type ProjectTab = "journey" | "intake" | "contract" | "notes" | "secrets" | "deep";
export type DeepTab = "tasks" | "artifacts" | "logs" | "deployments";

export const PROJECT_NAME_MAX = 200;
export const PROJECT_DESC_MAX = 10000;
export const NOTE_CONTENT_MAX = 5000;
