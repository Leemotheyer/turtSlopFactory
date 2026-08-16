import ui from "./ui.module.css";

type EmptyStateProps = {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  compact?: boolean;
};

export function EmptyState({ icon, title, description, action, compact }: EmptyStateProps) {
  return (
    <div
      className={ui.emptyState}
      style={compact ? { padding: "1.25rem 1rem" } : undefined}
    >
      {icon && <span className={ui.emptyIcon} aria-hidden="true">{icon}</span>}
      <p className={ui.emptyTitle}>{title}</p>
      {description && <p className={ui.emptyDescription}>{description}</p>}
      {action && <div className={ui.emptyAction}>{action}</div>}
    </div>
  );
}
