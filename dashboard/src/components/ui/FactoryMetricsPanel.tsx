"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchFactoryMetrics, type FactoryMetrics } from "@/lib/api";
import { formatPercent, humanizeDuration } from "@/lib/format";
import styles from "./FactoryMetricsPanel.module.css";

function formatAvg(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(1);
}

export function FactoryMetricsPanel() {
  const [metrics, setMetrics] = useState<FactoryMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMetrics(await fetchFactoryMetrics());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch metrics");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <details className={styles.panel}>
      <summary className={styles.summary}>
        <span className={styles.title}>Factory metrics</span>
        {metrics && (
          <span className={styles.headline}>
            {formatPercent(metrics.success_rate)} success
          </span>
        )}
      </summary>
      <div className={styles.body}>
        {error && <p className={styles.error}>{error}</p>}
        {!metrics && !error && <p className={styles.muted}>Loading…</p>}
        {metrics && (
          <dl className={styles.grid}>
            <div className={styles.metric}>
              <dt>Success rate</dt>
              <dd>{formatPercent(metrics.success_rate)}</dd>
            </div>
            <div className={styles.metric}>
              <dt>Runs completed</dt>
              <dd>{metrics.runs_completed}</dd>
            </div>
            <div className={styles.metric}>
              <dt>Runs blocked</dt>
              <dd>{metrics.runs_blocked}</dd>
            </div>
            <div className={styles.metric}>
              <dt>Avg fix attempts</dt>
              <dd>{formatAvg(metrics.avg_fix_attempts_per_run)}</dd>
            </div>
            <div className={styles.metric}>
              <dt>Avg human interventions</dt>
              <dd>{formatAvg(metrics.avg_human_interventions_per_completed_run)}</dd>
            </div>
            <div className={styles.metric}>
              <dt>Mean time to success</dt>
              <dd>{humanizeDuration(metrics.mean_seconds_to_successful_run)}</dd>
            </div>
          </dl>
        )}
      </div>
    </details>
  );
}
