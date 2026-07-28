import type { ReactNode } from "react";

/** Minimal line icons — Codex-like, 16×16 stroke */
type IconProps = { size?: number; className?: string };

function Svg({ size = 16, className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

export const Icons = {
  agent: (p: IconProps) => (
    <Svg {...p}>
      <circle cx="8" cy="5.5" r="2.5" />
      <path d="M3 13.5c.8-2.2 2.5-3.5 5-3.5s4.2 1.3 5 3.5" />
    </Svg>
  ),
  overview: (p: IconProps) => (
    <Svg {...p}>
      <path d="M2.5 2.5h4v4h-4zM9.5 2.5h4v4h-4zM2.5 9.5h4v4h-4zM9.5 9.5h4v4h-4z" />
    </Svg>
  ),
  console: (p: IconProps) => (
    <Svg {...p}>
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <path d="M5 7.5l1.5 1.5L5 10.5M8.5 10.5H11" />
    </Svg>
  ),
  terminal: (p: IconProps) => (
    <Svg {...p}>
      <path d="M3 4.5L6.5 8 3 11.5M8 11.5h5" />
    </Svg>
  ),
  findings: (p: IconProps) => (
    <Svg {...p}>
      <path d="M8 2.5l1.6 3.3 3.6.5-2.6 2.5.6 3.6L8 10.7l-3.2 1.7.6-3.6-2.6-2.5 3.6-.5L8 2.5z" />
    </Svg>
  ),
  runs: (p: IconProps) => (
    <Svg {...p}>
      <path d="M3 3.5h10M3 8h10M3 12.5h7" />
    </Svg>
  ),
  arsenal: (p: IconProps) => (
    <Svg {...p}>
      <path d="M8 2.5v11M4.5 5.5L8 2.5l3.5 3M4.5 10.5L8 13.5l3.5-3" />
    </Svg>
  ),
  profiles: (p: IconProps) => (
    <Svg {...p}>
      <rect x="3" y="2.5" width="10" height="11" rx="1.5" />
      <path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" />
    </Svg>
  ),
  settings: (p: IconProps) => (
    <Svg {...p}>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 2.5v1.5M8 12v1.5M2.5 8H4M12 8h1.5M4.1 4.1l1.1 1.1M10.8 10.8l1.1 1.1M11.9 4.1l-1.1 1.1M5.2 10.8l-1.1 1.1" />
    </Svg>
  ),
  search: (p: IconProps) => (
    <Svg {...p}>
      <circle cx="7" cy="7" r="3.5" />
      <path d="M10 10l3 3" />
    </Svg>
  ),
  chevron: (p: IconProps) => (
    <Svg {...p}>
      <path d="M6 3.5L10.5 8 6 12.5" />
    </Svg>
  ),
  panelLeft: (p: IconProps) => (
    <Svg {...p}>
      <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
      <path d="M6.5 2.5v11" />
    </Svg>
  ),
};
