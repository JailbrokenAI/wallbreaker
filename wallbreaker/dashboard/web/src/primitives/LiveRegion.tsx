import type { ReactNode } from "react";

/**
 * LiveRegion (accessibility) — an aria-live="polite" role="status" container for
 * announcing streaming/status updates. Defaults to visually hidden (screen-reader
 * only); pass `visible` to render it inline as well.
 */
export function LiveRegion({
  children,
  visible = false,
  className = "",
}: {
  children: ReactNode;
  visible?: boolean;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`${visible ? "live-region" : "live-region visually-hidden"} ${className}`.trim()}
    >
      {children}
    </div>
  );
}
