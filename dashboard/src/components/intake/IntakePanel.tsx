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

function isPrefilled(field: IntakeField, discovery: DiscoverySession): boolean {
  const saved = discovery.responses?.[field.id];
  return saved !== undefined && saved !== "" && saved !== null;
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
        <p>Discovery agent is preparing a bespoke intake form for your project…</p>
      </div>
    );
  }

  if (!discovery) {
    return <p className={styles.muted}>No discovery session yet.</p>;
  }

  const answeredCount = discovery.form_fields.filter((f) => {
    const v = intakeAnswers[f.id];
    return v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);
  }).length;

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
              <h3>Scope intake</h3>
              <p className={styles.hint}>
                Questions are tailored to your project
                {Object.keys(discovery.responses || {}).length > 0
                  ? " — review auto-filled answers from your README and description"
                  : ""}
                .
              </p>
            </div>
            <span className={styles.progress}>
              {answeredCount} / {discovery.form_fields.length} answered
            </span>
          </header>

          {discovery.form_fields.map((field, index) => {
            const prefilled = isPrefilled(field, discovery);
            return (
              <div key={field.id} className={styles.field}>
                <label className={styles.label}>
                  <span>
                    {index + 1}. {field.label}
                    {field.required ? " *" : ""}
                  </span>
                  {prefilled && (
                    <span className={styles.prefillBadge}>From README / repo</span>
                  )}
                </label>
                {field.help && <p className={styles.help}>{field.help}</p>}
                {renderField(
                  field,
                  intakeAnswers[field.id] ?? "",
                  (v) => onChange(field.id, v)
                )}
              </div>
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
