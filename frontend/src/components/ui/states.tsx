import type { ReactNode } from "react";
export function LoadingState({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="flex items-center gap-3 text-sm text-muted">
      <span className="spinner" />
      {children}
    </div>
  );
}
export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div role="alert" className="error-state">
      <p>{message}</p>
      {retry && (
        <button className="btn-secondary mt-3" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="mt-3 max-w-2xl text-muted leading-relaxed">
          {description}
        </p>
      </div>
      {action}
    </header>
  );
}
