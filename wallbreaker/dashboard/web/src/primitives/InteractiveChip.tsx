import type { ReactNode } from "react";

/**
 * InteractiveChip (accessibility) — a real button styled like the existing `.chip`
 * class (visual parity with Arsenal.tsx's button chips), exposing selection state
 * via aria-pressed so a toggle chip is announced correctly.
 */
export function InteractiveChip({
  selected,
  onToggle,
  children,
  title,
  disabled = false,
  className = "",
}: {
  selected: boolean;
  onToggle: () => void;
  children: ReactNode;
  title?: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={`chip ${selected ? "on" : ""} ${className}`.trim()}
      aria-pressed={selected}
      title={title}
      disabled={disabled}
      onClick={onToggle}
    >
      {children}
    </button>
  );
}
