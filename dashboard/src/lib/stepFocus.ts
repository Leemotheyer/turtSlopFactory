import type { AgentActivity, ProgressDigest, ProjectDetail } from "@/lib/api";
import { AUTO_START_PIPELINE_STATES } from "@/lib/constants";

export type StepFocus = {
  title: string;
  body: string;
  tone: "neutral" | "action" | "success" | "warning" | "danger";
  action?: "intake" | "notes" | "secrets" | "run" | "promote" | "preview";
  actionLabel?: string;
};

export function getStepFocus(
  detail: ProjectDetail,
  opts: {
    openInputs: number;
    pendingSecrets: number;
    progress: ProgressDigest | null;
    agentActivity: AgentActivity | null;
    livePreviewUrl: string | null;
  }
): StepFocus {
  const { openInputs, pendingSecrets, progress, agentActivity, livePreviewUrl } = opts;
  const state = detail.state;
  const latest = progress?.summary_lines?.[progress.summary_lines.length - 1];

  if (state === "REQUESTED" || state === "DISCOVERY") {
    return {
      title: "Analyzing your project",
      body: "The factory is reading your description and preparing a tailored intake form with the right follow-up questions.",
      tone: "neutral",
    };
  }

  if (state === "INTAKE_PENDING") {
    return {
      title: "Scope intake ready",
      body: "Answer bespoke questions so agents know exactly what to build — and what to skip.",
      tone: "action",
      action: "intake",
      actionLabel: "Complete intake form",
    };
  }

  if (detail.pipeline_running || agentActivity?.stop_requested) {
    return {
      title: agentActivity?.stop_requested ? "Stopping pipeline" : "Pipeline running",
      body: latest ?? "Agents are working through the current stage. Watch live activity below or open Deep dive for tasks and logs.",
      tone: "neutral",
    };
  }

  if (detail.pipeline_paused) {
    return {
      title: "Pipeline paused",
      body: "You stopped the pipeline. Resume when ready to continue from the last gate.",
      tone: "warning",
      action: "run",
      actionLabel: "Resume pipeline",
    };
  }

  if (state === "AUTONOMOUSLY_BLOCKED") {
    return {
      title: "Build blocked",
      body: detail.failed_gate
        ? `Repeated failures at ${detail.failed_gate.replace(/_/g, " ").toLowerCase()}. Check logs, add guidance notes, then resume.`
        : "The pipeline hit repeated failures. Review logs and resume with a fresh fix budget.",
      tone: "danger",
      action: "run",
      actionLabel: "Resume pipeline",
    };
  }

  if (state === "PLANNING" && !detail.pipeline_running) {
    return {
      title: "Ready to plan",
      body: "Start the pipeline to turn your intake answers into architecture and build tasks.",
      tone: "action",
      action: "run",
      actionLabel: "Start planning",
    };
  }

  if (AUTO_START_PIPELINE_STATES.has(state)) {
    return {
      title: "Build starting",
      body: "The pipeline is queuing the next stage automatically.",
      tone: "neutral",
    };
  }

  if (state === "REVIEW") {
    if (openInputs > 0) {
      return {
        title: "Reviewer needs input",
        body: `${openInputs} open question${openInputs > 1 ? "s" : ""} from agents. Answer in Notes before promoting.`,
        tone: "action",
        action: "notes",
        actionLabel: "Answer questions",
      };
    }
    return {
      title: "Ready for review",
      body: "Staging looks good. Promote to production when satisfied, or add notes to trigger another build cycle.",
      tone: "success",
      action: "promote",
      actionLabel: "Promote to production",
    };
  }

  if (state === "PRODUCTION") {
    return {
      title: "Live in production",
      body: livePreviewUrl
        ? "Your app is deployed. Add notes anytime to request improvements, or enable self-propelling cycles in Configure."
        : "Project reached production. Open Configure for post-production settings.",
      tone: "success",
      action: livePreviewUrl ? "preview" : undefined,
      actionLabel: livePreviewUrl ? "Open live app" : undefined,
    };
  }

  if (openInputs > 0) {
    return {
      title: "Agent questions waiting",
      body: `${openInputs} question${openInputs > 1 ? "s" : ""} need your answer to continue.`,
      tone: "action",
      action: "notes",
      actionLabel: "Go to notes",
    };
  }

  if (pendingSecrets > 0) {
    return {
      title: "Secrets required",
      body: `${pendingSecrets} secret${pendingSecrets > 1 ? "s" : ""} needed before preview testing can finish.`,
      tone: "action",
      action: "secrets",
      actionLabel: "Add secrets",
    };
  }

  return {
    title: state.replace(/_/g, " "),
    body: latest ?? "Track progress on the journey timeline below.",
    tone: "neutral",
  };
}
