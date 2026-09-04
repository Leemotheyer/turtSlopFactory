import { PIPELINE_PHASES, STATE_COLORS, type PipelineState } from "@/lib/constants";
import { verificationSubstageLabel } from "@/lib/pipelineSubstages";
import styles from "./PipelineTimeline.module.css";

type Props = {
  currentState: string;
  failedGate?: string | null;
  activeSubstage?: string | null;
};

function phaseStatus(
  phaseStates: PipelineState[],
  currentState: string,
  failedGate: string | null | undefined
): "done" | "active" | "failed" | "upcoming" {
  const order = PIPELINE_PHASES.flatMap((p) => p.states);
  const currentIdx = order.indexOf(currentState as PipelineState);
  const phaseStart = order.indexOf(phaseStates[0]);
  const phaseEnd = order.indexOf(phaseStates[phaseStates.length - 1]);

  if (["DIAGNOSING", "FIXING", "AUTONOMOUSLY_BLOCKED"].includes(currentState)) {
    if (failedGate && phaseStates.includes(failedGate as PipelineState)) return "failed";
    if (currentIdx > phaseEnd) return "done";
    if (currentIdx >= phaseStart && currentIdx <= phaseEnd) return "failed";
  }

  if (currentIdx > phaseEnd) return "done";
  if (currentIdx >= phaseStart && currentIdx <= phaseEnd) return "active";
  return "upcoming";
}

export function PipelineTimeline({ currentState, failedGate, activeSubstage }: Props) {
  return (
    <div className={styles.track} role="list" aria-label="Project journey">
      {PIPELINE_PHASES.map((phase, index) => {
        const status = phaseStatus(phase.states, currentState, failedGate);
        const isLast = index === PIPELINE_PHASES.length - 1;
        const color =
          status === "active"
            ? STATE_COLORS[currentState] ?? "var(--accent)"
            : status === "done"
              ? "var(--success)"
              : status === "failed"
                ? "var(--danger)"
                : undefined;

        return (
          <div
            key={phase.id}
            className={`${styles.phase} ${styles[status]}`}
            role="listitem"
            style={color ? ({ "--phase-color": color } as React.CSSProperties) : undefined}
          >
            <div className={styles.marker}>
              <span className={styles.dot} />
              {!isLast && <span className={styles.connector} />}
            </div>
            <div className={styles.content}>
              <span className={styles.label}>{phase.label}</span>
              {status === "active" && (
                <span className={styles.substate}>
                  {currentState === "SMOKE_TESTING" && activeSubstage
                    ? verificationSubstageLabel(activeSubstage)
                    : currentState.replace(/_/g, " ")}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
