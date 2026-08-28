import { ReactNode } from "react";
import styles from "./CollapsibleSection.module.css";

type Props = {
  title: string;
  summary?: string;
  defaultOpen?: boolean;
  children: ReactNode;
};

export function CollapsibleSection({ title, summary, defaultOpen = false, children }: Props) {
  return (
    <details className={styles.section} open={defaultOpen}>
      <summary className={styles.summary}>
        <span className={styles.title}>{title}</span>
        {summary && <span className={styles.hint}>{summary}</span>}
      </summary>
      <div className={styles.body}>{children}</div>
    </details>
  );
}
