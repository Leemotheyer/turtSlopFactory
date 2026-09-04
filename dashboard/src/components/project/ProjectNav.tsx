import type { DeepTab, ProjectTab } from "@/lib/constants";
import styles from "./ProjectNav.module.css";

type Props = {
  tab: ProjectTab;
  deepTab: DeepTab;
  onTabChange: (tab: ProjectTab) => void;
  onDeepTabChange: (tab: DeepTab) => void;
  badges: {
    intakePending?: boolean;
    openInputs?: number;
    pendingSecrets?: number;
    runningTasks?: number;
  };
};

const MAIN_TABS: { id: ProjectTab; label: string }[] = [
  { id: "journey", label: "Journey" },
  { id: "intake", label: "Intake" },
  { id: "contract", label: "Contract" },
  { id: "notes", label: "Notes" },
  { id: "secrets", label: "Secrets" },
  { id: "deep", label: "Deep dive" },
];

const DEEP_TABS: { id: DeepTab; label: string }[] = [
  { id: "tasks", label: "Tasks" },
  { id: "artifacts", label: "Artifacts" },
  { id: "logs", label: "Logs" },
  { id: "deployments", label: "Deploys" },
];

export function ProjectNav({ tab, deepTab, onTabChange, onDeepTabChange, badges }: Props) {
  return (
    <nav className={styles.nav} aria-label="Project sections">
      <div className={styles.mainTabs}>
        {MAIN_TABS.map((t) => {
          let badge: string | null = null;
          if (t.id === "intake" && badges.intakePending) badge = "•";
          if (t.id === "notes" && badges.openInputs) badge = String(badges.openInputs);
          if (t.id === "secrets" && badges.pendingSecrets) badge = String(badges.pendingSecrets);
          if (t.id === "deep" && badges.runningTasks) badge = String(badges.runningTasks);

          return (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? styles.tabActive : styles.tab}
              onClick={() => onTabChange(t.id)}
            >
              {t.label}
              {badge && <span className={styles.badge}>{badge}</span>}
            </button>
          );
        })}
      </div>
      {tab === "deep" && (
        <div className={styles.subTabs}>
          {DEEP_TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={deepTab === t.id ? styles.subActive : styles.subTab}
              onClick={() => onDeepTabChange(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
    </nav>
  );
}
