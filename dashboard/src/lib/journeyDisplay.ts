import type { ProjectDetail } from "@/lib/api";
import type { PipelineState } from "@/lib/constants";

export const POST_PRODUCTION_SUBSTAGES = [
  { id: "enrichment", label: "Improve" },
  { id: "testing", label: "Test" },
  { id: "redeploy", label: "Redeploy" },
] as const;

export type JourneyDisplay = {
  /** State shown on the main journey timeline. */
  state: PipelineState | string;
  /** Whether a self-propelling improvement cycle is active or queued. */
  postProductionCycle: boolean;
  /** Active post-production substage, when applicable. */
  postProductionStep: string | null;
  /** Optional override for the active phase substate label. */
  substateLabel: string | null;
};

export function isPostProductionCycleActive(detail: ProjectDetail): boolean {
  if (detail.state !== "PRODUCTION") return false;
  return Boolean(
    detail.post_production_cycle_active ||
      (detail.pipeline_running && detail.self_propelling?.enabled) ||
      detail.pipeline_substage?.gate === "PRODUCTION"
  );
}

export function postProductionStepLabel(step: string | null | undefined): string {
  return POST_PRODUCTION_SUBSTAGES.find((s) => s.id === step)?.label ?? step?.replace(/_/g, " ") ?? "Improve";
}

/** Map an active post-production cycle onto the main journey timeline. */
export function getJourneyDisplay(detail: ProjectDetail): JourneyDisplay {
  const base: JourneyDisplay = {
    state: detail.state,
    postProductionCycle: false,
    postProductionStep: null,
    substateLabel: null,
  };

  if (!isPostProductionCycleActive(detail)) {
    return base;
  }

  const step =
    detail.pipeline_substage?.gate === "PRODUCTION" ? detail.pipeline_substage.step ?? null : null;

  let mappedState: PipelineState | string = detail.state;
  if (step === "enrichment" || (!step && detail.pipeline_running)) {
    mappedState = "IMPLEMENTING";
  } else if (step === "testing") {
    mappedState = "SMOKE_TESTING";
  } else if (step === "redeploy") {
    mappedState = "DOCKER_BUILD";
  }

  const cycleLabel = detail.self_propelling?.rapid_iterations
    ? "Rapid improvement cycle"
    : "Improvement cycle";

  return {
    state: mappedState,
    postProductionCycle: true,
    postProductionStep: step,
    substateLabel: `${cycleLabel} · ${postProductionStepLabel(step)}`,
  };
}
