import {
  substageStatus,
  type SubstageStep,
  type SubstageStatus,
} from "@/lib/pipelineSubstages";
import styles from "./SubstageTrack.module.css";

type Props = {
  title: string;
  steps: SubstageStep[];
  activeStep?: string | null;
  failedSubstage?: string | null;
  phaseComplete?: boolean;
  stepEnabled?: (step: SubstageStep) => boolean;
  stepMeta?: (step: SubstageStep) => string | null;
};

function statusClass(status: SubstageStatus): string {
  switch (status) {
    case "done":
      return styles.stepDone;
    case "active":
      return styles.stepActive;
    case "failed":
      return styles.stepFailed;
    case "skipped":
      return styles.stepSkipped;
    default:
      return styles.stepUpcoming;
  }
}

export function SubstageTrack({
  title,
  steps,
  activeStep,
  failedSubstage,
  phaseComplete = false,
  stepEnabled,
  stepMeta,
}: Props) {
  return (
    <div className={styles.track}>
      <h4>{title}</h4>
      <div className={styles.steps} role="list" aria-label={title}>
        {steps.map((step) => {
          const enabled = stepEnabled ? stepEnabled(step) : step.enabled !== false;
          const status = substageStatus(step.id, steps, {
            activeStep,
            failedSubstage,
            phaseComplete,
            enabled,
          });
          const meta = stepMeta?.(step);

          return (
            <div
              key={step.id}
              role="listitem"
              className={`${styles.step} ${statusClass(status)}`}
              aria-current={status === "active" ? "step" : undefined}
            >
              <span className={styles.label}>{step.label}</span>
              {status === "skipped" && <span className={styles.meta}>Skipped</span>}
              {meta && status !== "skipped" && <span className={styles.meta}>{meta}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
