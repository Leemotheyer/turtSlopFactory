import type { FactoryEvent } from "@/lib/api";

export function formatEvent(ev: FactoryEvent): string {
  const p = ev.payload;
  if (ev.type === "state.transition") return `${p.from ?? "—"} → ${p.to}`;
  if (ev.type === "task.status.changed") return String(p.title ?? p.status);
  if (ev.type === "test.completed") return `${p.stage}: ${p.passed ? "PASS" : "FAIL"}`;
  if (ev.type === "deployment.finished") {
    const env = String(p.environment ?? "");
    const url = String(p.url ?? "");
    return url ? `${env} preview: ${url}` : `${env} deploy`;
  }
  if (ev.type === "agent.command.started") {
    const role = String(p.role ?? "agent");
    const title = String(p.title ?? p.command ?? "task");
    return `${role} started: ${title}`;
  }
  if (ev.type === "agent.command.output") {
    const role = String(p.role ?? "agent");
    const status = String(p.status ?? "working");
    const detail = p.detail ? ` — ${String(p.detail).slice(0, 60)}` : "";
    return `${role} ${status}${detail}`;
  }
  if (ev.type === "agent.command.finished") return String(p.output ?? p.command ?? "").slice(0, 80);
  if (ev.type === "pipeline.stopped") return "Pipeline stopped by user";
  if (ev.type === "progress.updated") return `${p.title}: ${p.summary}`;
  if (ev.type === "note.added") return String(p.content ?? "").slice(0, 80);
  if (ev.type === "note.updated") return `Updated: ${String(p.content ?? "").slice(0, 72)}`;
  if (ev.type === "note.deleted") return `Deleted note: ${String(p.content ?? "").slice(0, 64)}`;
  if (ev.type === "input.requested") return String(p.question ?? "").slice(0, 80);
  if (ev.type === "input.resolved") return `${p.status}: ${p.decision ?? ""}`.slice(0, 80);
  if (ev.type === "discovery.started") return "Discovery started";
  if (ev.type === "discovery.completed") return `Intake ready (${p.field_count} questions)`;
  if (ev.type === "intake.submitted") return "Scope locked in";
  if (ev.type === "notification.created") return String(p.title ?? "");
  if (ev.type === "env.required") return `Secret needed: ${p.key_name ?? ""}`;
  return JSON.stringify(p).slice(0, 80);
}
