import ui from "./ui.module.css";

type SkeletonProps = {
  variant?: "text" | "textSm" | "block" | "card";
  className?: string;
};

export function Skeleton({ variant = "text", className = "" }: SkeletonProps) {
  const variantClass =
    variant === "textSm"
      ? ui.skeletonTextSm
      : variant === "block"
        ? ui.skeletonBlock
        : variant === "card"
          ? ui.skeletonCard
          : ui.skeletonText;

  return (
    <div
      className={`${ui.skeleton} ${variantClass} ${className}`.trim()}
      aria-hidden="true"
    />
  );
}

export function ProjectListSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading projects">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} variant="card" />
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading project">
      <div className={`${ui.skeleton} ${ui.skeletonTitle}`} aria-hidden="true" />
      <Skeleton variant="textSm" />
      <Skeleton variant="block" />
      <Skeleton variant="block" />
      <div className={ui.skeletonTabRow}>
        <div className={`${ui.skeleton} ${ui.skeletonTab}`} aria-hidden="true" />
        <div className={`${ui.skeleton} ${ui.skeletonTab}`} aria-hidden="true" />
        <div className={`${ui.skeleton} ${ui.skeletonTab}`} aria-hidden="true" />
      </div>
      <div className={`${ui.skeleton} ${ui.skeletonBlock} ${ui.skeletonPanel}`} aria-hidden="true" />
    </div>
  );
}
