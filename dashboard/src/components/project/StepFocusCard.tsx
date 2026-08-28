import type { StepFocus } from "@/lib/stepFocus";
import type { ProjectTab } from "@/lib/constants";
import styles from "./StepFocusCard.module.css";

type Props = {
  focus: StepFocus;
  onAction?: (action: "run" | "promote") => void | Promise<void>;
  onNavigate?: (tab: ProjectTab) => void;
  previewUrl?: string | null;
};

export function StepFocusCard({ focus, onAction, onNavigate, previewUrl }: Props) {
  function handleClick() {
    if (!focus.action) return;
    if (focus.action === "preview" && previewUrl) {
      window.open(previewUrl, "_blank", "noopener,noreferrer");
      return;
    }
    if (focus.action === "intake") onNavigate?.("intake");
    else if (focus.action === "notes") onNavigate?.("notes");
    else if (focus.action === "secrets") onNavigate?.("secrets");
    else if (focus.action === "run" || focus.action === "promote") onAction?.(focus.action);
  }

  return (
    <section className={`${styles.card} ${styles[focus.tone]}`}>
      <div className={styles.text}>
        <h3 className={styles.title}>{focus.title}</h3>
        <p className={styles.body}>{focus.body}</p>
      </div>
      {focus.action && focus.actionLabel && (
        <button type="button" className={styles.action} onClick={handleClick}>
          {focus.actionLabel}
        </button>
      )}
    </section>
  );
}
