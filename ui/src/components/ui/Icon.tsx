/** Teleport's own small icon set: one 1.5px stroke, 20px grid, drawn to sit quietly next to text. */
const PATHS = {
  overview: 'M3.5 4.5h5v5h-5zM11.5 4.5h5v3h-5zM11.5 10.5h5v5h-5zM3.5 12.5h5v3h-5z',
  workloads: 'M10 3.5l6.5 3.25L10 10 3.5 6.75zM3.5 10.25L10 13.5l6.5-3.25M3.5 13.75L10 17l6.5-3.25',
  migrate: 'M3.5 7h11m0 0l-3-3m3 3l-3 3M16.5 13h-11m0 0l3-3m-3 3l3 3',
  remote: 'M3 4.5h14v9H3zM7.5 16.5h5M10 13.5v3',
  history: 'M10 6v4l2.5 2M3.6 10a6.4 6.4 0 1 0 1.9-4.55M3.5 3.5v2.5H6',
  settings: 'M4 6h7m3 0h2M4 14h2m3 0h7M11 4v4M6 12v4',
  plus: 'M10 4.5v11M4.5 10h11',
  arrow: 'M4 10h12m0 0l-4-4m4 4l-4 4',
  check: 'M4.5 10.5l3.5 3.5 7.5-8',
  x: 'M5.5 5.5l9 9m0-9l-9 9',
  alert: 'M10 7v4m0 2.5v.01M10 3.5l7 12.5H3z',
  sun: 'M10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM10 2.5v1.5M10 16v1.5M2.5 10H4M16 10h1.5M4.7 4.7l1 1M14.3 14.3l1 1M4.7 15.3l1-1M14.3 5.7l1-1',
  moon: 'M15.5 12.2A6 6 0 0 1 7.8 4.5a6 6 0 1 0 7.7 7.7z',
  link: 'M8.5 11.5l3-3M7 9.5l-1.5 1.5a2.5 2.5 0 0 0 3.5 3.5L10.5 13M13 10.5l1.5-1.5A2.5 2.5 0 0 0 11 5.5L9.5 7',
  laptop: 'M4.5 5h11v7.5h-11zM2.5 15h15',
  folder: 'M3 5.5h5l1.5 1.5H17v8.5H3z',
  play: 'M7 5l8 5-8 5z',
  stop: 'M6 6h8v8H6z',
  pause: 'M7 5.5v9M13 5.5v9',
  bolt: 'M11 3L5 11h4.5L9 17l6-8h-4.5z',
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = 'h-4 w-4' }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/** A dot that breathes while something is live. */
export function LiveDot({ tone = 'ok', live = true }: { tone?: 'ok' | 'warn' | 'bad' | 'accent' | 'idle'; live?: boolean }) {
  const color = {
    ok: 'bg-ok',
    warn: 'bg-warn',
    bad: 'bg-bad',
    accent: 'bg-accent',
    idle: 'bg-faint',
  }[tone];
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0">
      {live && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${color}`} />}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${color}`} />
    </span>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col justify-between gap-4 border-b border-line pb-5 sm:flex-row sm:items-end">
      <div>
        {eyebrow && <p className="tp-label mb-1.5">{eyebrow}</p>}
        <h1 className="tp-title">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
