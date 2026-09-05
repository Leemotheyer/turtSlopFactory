"use client";

import type { ProjectStats } from "@/lib/api";
import { formatPercent, humanizeDuration } from "@/lib/format";
import styles from "./ProjectStatsPanel.module.css";

function formatAvg(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return humanizeDuration(value);
}

type ProjectStatsPanelProps = {
  stats: ProjectStats;
};

export function ProjectStatsPanel({ stats }: ProjectStatsPanelProps) {
  const headline = stats.development_active
    ? `${humanizeDuration(stats.development_seconds)} · running`
    : humanizeDuration(stats.development_seconds);

  return (
    <details className={styles.panel} open>
      <summary className={styles.summary}>
        <span className={styles.title}>Project stats</span>
        <span className={styles.headline}>{headline} development</span>
      </summary>
      <div className={styles.body}>
        {stats.waiting_for_production && (
          <p className={styles.note}>
            Waiting for production approval — idle time here is not counted toward development time.
          </p>
        )}
        <dl className={styles.grid}>
          <div className={styles.metric}>
            <dt>Development time</dt>
            <dd>{humanizeDuration(stats.development_seconds)}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Total cycles</dt>
            <dd>{stats.total_cycles}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Improvement cycles</dt>
            <dd>{stats.improvement_cycles}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Build cycles</dt>
            <dd>{stats.build_cycles}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Feedback iterations</dt>
            <dd>{stats.feedback_iterations}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Pipeline runs</dt>
            <dd>
              {stats.pipeline_runs_total}
              {stats.pipeline_runs_completed > 0 && (
                <span className={styles.sub}>
                  {" "}
                  · {stats.pipeline_runs_completed} completed
                </span>
              )}
            </dd>
          </div>
          <div className={styles.metric}>
            <dt>Success rate</dt>
            <dd>{formatPercent(stats.success_rate)}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Avg cycle time</dt>
            <dd>{formatAvg(stats.mean_cycle_seconds)}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Avg improvement cycle</dt>
            <dd>{formatAvg(stats.mean_improvement_cycle_seconds)}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Tasks completed</dt>
            <dd>{stats.tasks_completed}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Deployments</dt>
            <dd>{stats.deployments}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Fix attempts</dt>
            <dd>{stats.total_fix_attempts}</dd>
          </div>
          <div className={styles.metric}>
            <dt>Human interventions</dt>
            <dd>{stats.total_human_interventions}</dd>
          </div>
        </dl>
      </div>
    </details>
  );
}
