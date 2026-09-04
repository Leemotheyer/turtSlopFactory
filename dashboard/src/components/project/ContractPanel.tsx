"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchContract,
  updateContract,
  type Contract,
  type ContractRequirement,
} from "@/lib/api";
import styles from "./ContractPanel.module.css";

type Props = {
  projectId: string;
};

type RequirementDraft = {
  id: string;
  description: string;
  acceptanceText: string;
  priority: string;
};

function toDrafts(requirements: ContractRequirement[]): RequirementDraft[] {
  return requirements.map((req) => ({
    id: req.id,
    description: req.description,
    acceptanceText: req.acceptance.join("\n"),
    priority: req.priority,
  }));
}

function nextRequirementId(drafts: RequirementDraft[]): string {
  let max = 0;
  for (const d of drafts) {
    const m = /^R(\d+)$/i.exec(d.id.trim());
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `R${max + 1}`;
}

function splitLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function ContractPanel({ projectId }: Props) {
  const [contract, setContract] = useState<Contract | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const [feedbackScheduled, setFeedbackScheduled] = useState(false);

  const [goalDraft, setGoalDraft] = useState("");
  const [nonGoalsDraft, setNonGoalsDraft] = useState("");
  const [reqDrafts, setReqDrafts] = useState<RequirementDraft[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await fetchContract(projectId);
      setContract(data.contract);
      setVersion(data.version);
      setSource(data.source);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch contract");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    setEditing(false);
    setSaveNote(null);
    setFeedbackScheduled(false);
    void load();
  }, [load]);

  function startEditing() {
    if (!contract) return;
    setGoalDraft(contract.goal);
    setNonGoalsDraft(contract.non_goals.join("\n"));
    setReqDrafts(toDrafts(contract.requirements));
    setSaveNote(null);
    setFeedbackScheduled(false);
    setEditing(true);
  }

  function updateDraft(index: number, patch: Partial<RequirementDraft>) {
    setReqDrafts((prev) => prev.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  function addRequirement() {
    setReqDrafts((prev) => [
      ...prev,
      { id: nextRequirementId(prev), description: "", acceptanceText: "", priority: "must" },
    ]);
  }

  function removeRequirement(index: number) {
    setReqDrafts((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!contract) return;
    setSaving(true);
    setError(null);
    try {
      const body: Contract = {
        ...contract,
        goal: goalDraft.trim(),
        non_goals: splitLines(nonGoalsDraft),
        requirements: reqDrafts
          .filter((d) => d.description.trim())
          .map((d) => ({
            id: d.id.trim(),
            description: d.description.trim(),
            acceptance: splitLines(d.acceptanceText),
            priority: d.priority,
          })),
      };
      const result = await updateContract(projectId, body);
      setContract(result.contract);
      setVersion(result.version);
      setSource(result.source);
      setFeedbackScheduled(result.feedback_scheduled);
      setSaveNote(`Saved as v${result.version}`);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save contract");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className={styles.panel} aria-label="Contract">
        <p className={styles.muted}>Loading contract…</p>
      </section>
    );
  }

  return (
    <section className={styles.panel} aria-label="Contract">
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h3>Product contract</h3>
          {version != null && <span className={styles.versionBadge}>v{version}</span>}
          {source && <span className={styles.sourceBadge}>{source}</span>}
        </div>
        {contract && !editing && (
          <button type="button" className={styles.editBtn} onClick={startEditing}>
            Edit contract
          </button>
        )}
      </header>

      {error && <p className={styles.error}>{error}</p>}
      {saveNote && !editing && (
        <p className={styles.saveNote}>
          {saveNote}
          {feedbackScheduled && (
            <span className={styles.feedbackNote}> — Factory will apply contract changes</span>
          )}
        </p>
      )}

      {!contract ? (
        <p className={styles.muted}>
          No contract yet — one is drafted automatically after intake.
        </p>
      ) : editing ? (
        <form className={styles.form} onSubmit={handleSave}>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Goal</span>
            <textarea
              className={styles.input}
              value={goalDraft}
              onChange={(e) => setGoalDraft(e.target.value)}
              rows={3}
              required
            />
          </label>

          <div className={styles.field}>
            <span className={styles.fieldLabel}>Requirements</span>
            {reqDrafts.map((draft, index) => (
              <div key={index} className={styles.reqEditor}>
                <div className={styles.reqEditorHeader}>
                  <span className={styles.reqId}>{draft.id}</span>
                  <button
                    type="button"
                    className={styles.removeBtn}
                    onClick={() => removeRequirement(index)}
                    aria-label={`Remove requirement ${draft.id}`}
                  >
                    Remove
                  </button>
                </div>
                <textarea
                  className={styles.input}
                  value={draft.description}
                  onChange={(e) => updateDraft(index, { description: e.target.value })}
                  placeholder="Requirement description"
                  rows={2}
                />
                <textarea
                  className={styles.input}
                  value={draft.acceptanceText}
                  onChange={(e) => updateDraft(index, { acceptanceText: e.target.value })}
                  placeholder="Acceptance criteria — one per line"
                  rows={3}
                />
              </div>
            ))}
            <button type="button" className={styles.addBtn} onClick={addRequirement}>
              + Add requirement
            </button>
          </div>

          <label className={styles.field}>
            <span className={styles.fieldLabel}>Non-goals (one per line)</span>
            <textarea
              className={styles.input}
              value={nonGoalsDraft}
              onChange={(e) => setNonGoalsDraft(e.target.value)}
              rows={3}
            />
          </label>

          <div className={styles.formActions}>
            <button type="submit" className={styles.saveBtn} disabled={saving}>
              {saving ? "Saving…" : "Save contract"}
            </button>
            <button
              type="button"
              className={styles.cancelBtn}
              onClick={() => setEditing(false)}
              disabled={saving}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className={styles.view}>
          <div className={styles.section}>
            <h4>Goal</h4>
            <p>{contract.goal}</p>
          </div>

          <div className={styles.section}>
            <h4>Requirements</h4>
            {contract.requirements.length === 0 ? (
              <p className={styles.muted}>No requirements defined.</p>
            ) : (
              <ul className={styles.reqList}>
                {contract.requirements.map((req) => (
                  <li key={req.id} className={styles.reqItem}>
                    <div className={styles.reqItemHeader}>
                      <span className={styles.reqId}>{req.id}</span>
                      <span className={styles.priorityBadge}>{req.priority}</span>
                      <span className={styles.reqDesc}>{req.description}</span>
                    </div>
                    {req.acceptance.length > 0 && (
                      <ul className={styles.acceptance}>
                        {req.acceptance.map((crit, i) => (
                          <li key={i}>{crit}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {contract.non_goals.length > 0 && (
            <div className={styles.section}>
              <h4>Non-goals</h4>
              <ul className={styles.bulletList}>
                {contract.non_goals.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {contract.constraints.length > 0 && (
            <div className={styles.section}>
              <h4>Constraints</h4>
              <ul className={styles.bulletList}>
                {contract.constraints.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
