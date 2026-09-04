import type { RequirementStatus } from "@/lib/api";

/** Map a requirement verification status to its display color. */
export function requirementStatusColor(status: RequirementStatus): string {
  switch (status) {
    case "verified":
      return "var(--success)";
    case "failed":
      return "var(--danger)";
    case "waived":
      return "#6b7280";
    case "pending":
    case "unverified":
    default:
      return "var(--warning)";
  }
}

/** Humanize a duration in seconds, e.g. 45s, 3m 20s, 2h 15m, 1d 4h. */
export function humanizeDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) {
    const rem = s % 60;
    return rem ? `${m}m ${rem}s` : `${m}m`;
  }
  const h = Math.floor(m / 60);
  if (h < 24) {
    const rem = m % 60;
    return rem ? `${h}h ${rem}m` : `${h}h`;
  }
  const d = Math.floor(h / 24);
  const remH = h % 24;
  return remH ? `${d}d ${remH}h` : `${d}d`;
}

/** Format a 0..1 ratio as a percentage string, e.g. 0.5 → "50%". */
export function formatPercent(ratio: number | null | undefined): string {
  if (ratio == null || !Number.isFinite(ratio)) return "—";
  return `${Math.round(ratio * 100)}%`;
}
