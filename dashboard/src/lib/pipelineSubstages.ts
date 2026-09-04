export type SubstageStep = {
  id: string;
  label: string;
  /** When false, the step may be skipped by factory settings. */
  enabled?: boolean;
};

export const BUILD_SUBSTAGES: SubstageStep[] = [
  { id: "implementing", label: "Build" },
  { id: "unit_testing", label: "Unit tests" },
  { id: "enrichment", label: "Enrichment" },
];

export const VERIFICATION_SUBSTAGES: SubstageStep[] = [
  { id: "smoke_testing", label: "Smoke tests" },
  { id: "enrichment", label: "Polish" },
  { id: "adversary", label: "Adversary", enabled: true },
  { id: "acceptance", label: "Acceptance" },
  { id: "user_journey", label: "User journey", enabled: true },
  { id: "review", label: "Code review" },
];

export type SubstageStatus = "done" | "active" | "upcoming" | "failed" | "skipped";

export function substageStatus(
  stepId: string,
  orderedSteps: SubstageStep[],
  opts: {
    activeStep?: string | null;
    failedSubstage?: string | null;
    phaseComplete?: boolean;
    enabled?: boolean;
  }
): SubstageStatus {
  if (opts.enabled === false) return "skipped";

  const ids = orderedSteps.map((s) => s.id);
  const stepIdx = ids.indexOf(stepId);
  const activeIdx = opts.activeStep ? ids.indexOf(opts.activeStep) : -1;

  if (opts.failedSubstage === stepId) return "failed";
  if (opts.phaseComplete) return "done";
  if (opts.activeStep === stepId) return "active";
  if (activeIdx >= 0 && stepIdx >= 0 && stepIdx < activeIdx) return "done";
  return "upcoming";
}

export function verificationSubstageLabel(stepId: string): string {
  return VERIFICATION_SUBSTAGES.find((s) => s.id === stepId)?.label ?? stepId.replace(/_/g, " ");
}
