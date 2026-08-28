"use client";

import type { DiscoverySession, IntakeField } from "@/lib/api";
import styles from "./IntakePanel.module.css";

type Props = {
  discovery: DiscoverySession | null;
  detailState: string | undefined;
  intakeAnswers: Record<string, string | string[]>;
  loading: boolean;
  onChange: (fieldId: string, value: string | string[]) => void;
  onSubmit: (e: React.FormEvent) => void;
};

const CATEGORY_ORDER = [
  "existing",
  "vision",
  "users",
  "features",
  "technical",
  "domain",
  "general",
  "wrapup",
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  existing: "Existing codebase",
  vision: "Your vision",
  users: "Users & access",
  features: "Features & scope",
  technical: "Technical choices",
  domain: "Project-specific details",
  general: "Additional details",
  wrapup: "Wrap-up",
};

function isPrefilled(field: IntakeField, discovery: DiscoverySession): boolean {
  const saved = discovery.responses?.[field.id];
  return saved !== undefined && saved !== "" && saved !== null;
}

function prefillLabel(field: IntakeField, discovery: DiscoverySession): string | null {
  if (field.prefill_source === "description") return "From your description";
  if (field.prefill_source === "readme") return "From README / repo";
  if (field.prefill_source === "inferred") return "Factory suggestion";
  if (isPrefilled(field, discovery)) return "From README / repo";
  return null;
}

function fieldVisible(field: IntakeField, answers: Record<string, string | string[]>): boolean {
  if (!field.show_when) return true;
  for (const [key, expected] of Object.entries(field.show_when)) {
    const val = answers[key];
    const normalized = Array.isArray(val) ? val.join(", ") : String(val ?? "");
    if (Array.isArray(expected)) {
      if (!expected.some((e) => normalized.includes(e))) return false;
    } else if (normalized !== expected) {
      return false;
    }
  }
  return true;
}

function groupFields(fields: IntakeField[]): Map<string, IntakeField[]> {
  const groups = new Map<string, IntakeField[]>();
  for (const field of fields) {
    const cat = field.category || "general";
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat)!.push(field);
  }
  return groups;
}

function renderField(
  field: IntakeField,
  value: string | string[],
  onChange: (v: string | string[]) => void
) {
  if (field.type === "textarea") {
    return (
      <textarea
        className={styles.input}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.placeholder}
        rows={4}
        required={field.required}
      />
    );
  }
  if (field.type === "select") {
    return (
      <select
        className={styles.input}
        value={typeof value === "string" ? value : field.options[0] ?? ""}
        onChange={(e) => onChange(e.target.value)}
        required={field.required}
      >
        {field.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === "multiselect") {
    const selected = Array.isArray(value) ? value : value ? [value] : [];
    return (
      <div className={styles.multiSelect}>
        {field.options.map((opt) => (
          <label key={opt} className={styles.checkLabel}>
            <input
              type="checkbox"
              checked={selected.includes(opt)}
              onChange={(e) => {
                if (e.target.checked) onChange([...selected, opt]);
                else onChange(selected.filter((s) => s !== opt));
              }}
            />
            {opt}
          </label>
        ))}
      </div>
    );
  }
  return (
    <input
      className={styles.input}
      type="text"
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder={field.placeholder}
      required={field.required}
    />
  );
}

export function IntakePanel({
  discovery,
  detailState,
  intakeAnswers,
  loading,
  onChange,
  onSubmit,
}: Props) {
  if (
    detailState === "REQUESTED" ||
    detailState === "DISCOVERY" ||
    discovery?.status === "generating"
  ) {
    return (
      <div className={styles.waiting}>
        <div className={styles.spinner} aria-hidden />
        <p>Analyzing your project description and preparing tailored intake questions…</p>
      </div>
    );
  }

  if (!discovery) {
    return <p className={styles.muted}>No discovery session yet.</p>;
  }

  const visibleFields = discovery.form_fields.filter((f) => fieldVisible(f, intakeAnswers));
  const answeredCount = visibleFields.filter((f) => {
    const v = intakeAnswers[f.id];
    return v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);
  }).length;

  const grouped = groupFields(visibleFields);
  const orderedCategories = [
    ...CATEGORY_ORDER.filter((c) => grouped.has(c)),
    ...[...grouped.keys()].filter((c) => !CATEGORY_ORDER.includes(c as (typeof CATEGORY_ORDER)[number])),
  ];

  let questionIndex = 0;

  return (
    <div className={styles.panel}>
      <section className={styles.planCard}>
        <h3>Discovery summary</h3>
        <div className={styles.planBody}>{discovery.loose_plan}</div>
      </section>

      {discovery.status === "awaiting_user" ? (
        <form className={styles.form} onSubmit={onSubmit}>
          <header className={styles.formHeader}>
            <div>
              <h3>Tailored scope intake</h3>
              <p className={styles.hint}>
                Questions are generated from your project description
                {Object.keys(discovery.responses || {}).length > 0
                  ? " — review auto-filled answers and adjust anything that is wrong"
                  : ""}
                .
              </p>
            </div>
            <span className={styles.progress}>
              {answeredCount} / {visibleFields.length} answered
            </span>
          </header>

          {orderedCategories.map((category) => {
            const fields = grouped.get(category) ?? [];
            if (!fields.length) return null;
            return (
              <section key={category} className={styles.section}>
                <h4 className={styles.sectionTitle}>
                  {CATEGORY_LABELS[category] ?? category.replace(/_/g, " ")}
                </h4>
                {fields.map((field) => {
                  questionIndex += 1;
                  const badge = prefillLabel(field, discovery);
                  return (
                    <div key={field.id} className={styles.field}>
                      <label className={styles.label}>
                        <span>
                          {questionIndex}. {field.label}
                          {field.required ? " *" : ""}
                        </span>
                        {badge && <span className={styles.prefillBadge}>{badge}</span>}
                      </label>
                      {field.help && <p className={styles.help}>{field.help}</p>}
                      {renderField(
                        field,
                        intakeAnswers[field.id] ?? field.default ?? "",
                        (v) => onChange(field.id, v)
                      )}
                    </div>
                  );
                })}
              </section>
            );
          })}

          <button type="submit" className={styles.submit} disabled={loading}>
            {loading ? "Submitting…" : "Lock scope & start build"}
          </button>
        </form>
      ) : (
        <div className={styles.done}>
          <strong>Intake submitted.</strong> The build pipeline is running or queued.
        </div>
      )}
    </div>
  );
}
