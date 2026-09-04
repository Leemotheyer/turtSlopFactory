"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchRequirements,
  unwaiveRequirement,
  waiveRequirement,
  type RequirementsHealth,
  type RequirementWithEvidence,
} from "@/lib/api";
import { requirementStatusColor } from "@/lib/format";
import styles from "./RequirementsPanel.module.css";

type Props = {
  projectId: string;
};

export function RequirementsPanel({ projectId }: Props) {
  const [requirements, setRequirements] = useState<RequirementWithEvidence[]>([]);
  const [health, setHealth] = useState<RequirementsHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [busyReqId, setBusyReqId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchRequirements(projectId);
      setRequirements(data.requirements);
      setHealth(data.health);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch requirements");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    setExpandedId(null);
    void load();
  }, [load]);

  async function handleWaiveToggle(req: RequirementWithEvidence) {
    setBusyReqId(req.req_id);
    try {
      if (req.status === "waived") {
        await unwaiveRequirement(projectId, req.req_id);
      } else {
        await waiveRequirement(projectId, req.req_id);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update requirement");
    } finally {
      setBusyReqId(null);
    }
  }

  const percent =
    health?.health_percent != null ? Math.round(health.health_percent) : null;

  return (
    <section className={styles.panel} aria-label="Requirements">
      <header className={styles.header}>
        <h3>Requirements</h3>
        <button
          type="button"
          className={styles.refreshBtn}
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {error && <p className={styles.error}>{error}</p>}

      {health && (
        <div className={styles.health}>
          <div className={styles.healthLabel}>
            <span>
              {health.verified} / {health.total_requirements} verified
            </span>
            <span className={styles.healthPercent}>
              {percent != null ? `${percent}%` : "—"}
            </span>
          </div>
          <div
            className={styles.healthTrack}
            role="progressbar"
            aria-valuenow={percent ?? undefined}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className={styles.healthFill}
              style={{ width: `${percent ?? 0}%` }}
            />
          </div>
          {(health.failed > 0 || health.unverified > 0) && (
            <p className={styles.healthDetail}>
              {health.failed > 0 && <span>{health.failed} failed</span>}
              {health.failed > 0 && health.unverified > 0 && " · "}
              {health.unverified > 0 && <span>{health.unverified} unverified</span>}
            </p>
          )}
        </div>
      )}

      {loading && requirements.length === 0 ? (
        <p className={styles.muted}>Loading requirements…</p>
      ) : requirements.length === 0 ? (
        <p className={styles.muted}>
          No requirements tracked yet — they appear once a contract exists.
        </p>
      ) : (
        <ul className={styles.list}>
          {requirements.map((req) => {
            const expanded = expandedId === req.req_id;
            return (
              <li key={req.req_id} className={styles.row}>
                <button
                  type="button"
                  className={styles.rowHeader}
                  onClick={() => setExpandedId(expanded ? null : req.req_id)}
                  aria-expanded={expanded}
                >
                  <span
                    className={styles.statusPill}
                    style={{ background: requirementStatusColor(req.status) }}
                  >
                    {req.status}
                  </span>
                  <span className={styles.reqId}>{req.req_id}</span>
                  <span className={styles.reqDesc}>{req.description}</span>
                  <span className={styles.chevron} aria-hidden>
                    {expanded ? "▾" : "▸"}
                  </span>
                </button>

                {req.acceptance.length > 0 && (
                  <ul className={styles.acceptance}>
                    {req.acceptance.map((crit, i) => (
                      <li key={i}>{crit}</li>
                    ))}
                  </ul>
                )}

                {expanded && (
                  <div className={styles.evidence}>
                    <h4>Evidence</h4>
                    {req.evidence.length === 0 ? (
                      <p className={styles.muted}>No evidence recorded yet.</p>
                    ) : (
                      <ul className={styles.evidenceList}>
                        {req.evidence.map((ev, i) => (
                          <li key={i} className={styles.evidenceItem}>
                            <span
                              className={
                                ev.passed ? styles.evidencePass : styles.evidenceFail
                              }
                            >
                              {ev.passed ? "PASS" : "FAIL"}
                            </span>
                            <span className={styles.evidenceKind}>{ev.kind}</span>
                            <span className={styles.evidenceRef}>{ev.reference}</span>
                            <time className={styles.evidenceTime}>
                              {new Date(ev.created_at).toLocaleString()}
                            </time>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                <div className={styles.rowActions}>
                  <button
                    type="button"
                    className={styles.waiveBtn}
                    onClick={() => void handleWaiveToggle(req)}
                    disabled={busyReqId === req.req_id}
                    title={
                      req.status === "waived"
                        ? "Track this requirement again"
                        : "Exclude this requirement from verification"
                    }
                  >
                    {busyReqId === req.req_id
                      ? "Saving…"
                      : req.status === "waived"
                        ? "Unwaive"
                        : "Waive"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
