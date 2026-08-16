import ui from "./ui.module.css";

export function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <span className={ui.fieldError} role="alert">
      {message}
    </span>
  );
}

export function inputInvalidClass(hasError: boolean): string {
  return hasError ? ui.inputInvalid : "";
}
