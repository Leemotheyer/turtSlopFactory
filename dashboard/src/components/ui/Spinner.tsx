import ui from "./ui.module.css";

type SpinnerProps = {
  size?: "sm" | "lg";
  className?: string;
  label?: string;
};

export function Spinner({ size = "sm", className = "", label }: SpinnerProps) {
  return (
    <span
      className={`${ui.spinner} ${size === "lg" ? ui.spinnerLg : ""} ${className}`.trim()}
      role="status"
      aria-label={label ?? "Loading"}
    />
  );
}
