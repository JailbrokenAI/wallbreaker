import type { ReactNode } from "react";

export type AsyncStatus = "loading" | "error" | "empty" | "data";

/**
 * AsyncView<T> (REL-9) — renders exactly one of loading | empty | error | data.
 * CRITICAL: `error` is a DISTINCT status from loading, so a failed fetch shows an
 * error card with a Retry button instead of an indefinite spinner. Callers must
 * set status to "error" in their catch, never fall back to a null/loading state.
 *
 * When status is "data", `children(data)` is invoked with the resolved value so
 * the render tree is typed by T.
 */
export function AsyncView<T>({
  status,
  data,
  error,
  onRetry,
  empty,
  loadingLabel = "Loading…",
  children,
}: {
  status: AsyncStatus;
  data?: T;
  error?: string | null;
  onRetry?: () => void;
  empty?: ReactNode;
  loadingLabel?: string;
  children: (data: T) => ReactNode;
}) {
  if (status === "error") {
    return (
      <div className="async-error err" role="alert">
        <div className="async-error-msg">{error || "Something went wrong."}</div>
        {onRetry && (
          <button type="button" className="mini-btn" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    );
  }
  if (status === "loading") {
    return <div className="empty">{loadingLabel}</div>;
  }
  if (status === "empty") {
    return <>{empty ?? <div className="empty">Nothing to show.</div>}</>;
  }
  return <>{children(data as T)}</>;
}
