import type { ReactNode } from "react";

export function LoadingView({ label = "Đang tải dữ liệu" }: { label?: string }) {
  return (
    <div className="panel" role="status" aria-live="polite">
      <p className="muted">{label}…</p>
    </div>
  );
}

export function EmptyView({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="panel" role="status">
      <h2 className="panel__title">{title}</h2>
      {hint ? <p className="muted">{hint}</p> : null}
      {action ? <div className="row">{action}</div> : null}
    </div>
  );
}

export function ErrorView({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="panel" role="alert">
      <h2 className="panel__title">Không tải được dữ liệu</h2>
      <p>{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Thử lại
        </button>
      ) : null}
    </div>
  );
}
