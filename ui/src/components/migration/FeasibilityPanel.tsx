import { Icon } from '../ui/Icon.tsx';
import type { Decision, Reason } from '@contract';

interface FeasibilityPanelProps {
  decision?: Decision;
  reasons: Reason[];
  headline?: string;
}

export function FeasibilityPanel({ decision = 'MIGRATE', reasons, headline }: FeasibilityPanelProps) {
  // Sort reasons: block first, then warn, then pass
  const sortedReasons = [...reasons].sort((a, b) => {
    const order: Record<string, number> = { block: 0, warn: 1, pass: 2 };
    return (order[a.severity] ?? 9) - (order[b.severity] ?? 9);
  });

  const isMigrate = decision === 'MIGRATE';
  const isRemote = decision === 'REMOTE_ACCESS';

  return (
    <div className="tp-card p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="tp-label">Decision</p>
          <h2 className="mt-1 font-serif text-2xl leading-tight text-ink">
            {headline ??
              (isMigrate ? 'Migrate with checkpoints' : isRemote ? 'Remote access instead' : 'Stay on this laptop')}
          </h2>
        </div>
        <span
          data-testid="feasibility-decision-badge"
          className={`tp-chip shrink-0 font-mono ${isMigrate ? 'border-ok/40 text-ok' : isRemote ? 'border-steel/40 text-steel' : 'border-warn/40 text-warn'}`}
        >
          {decision}
        </span>
      </div>

      {sortedReasons.length === 0 ? (
        <p className="mt-5 text-sm text-faint">Reasons appear here once Teleport has compared both laptops.</p>
      ) : (
        <ul className="mt-4 divide-y divide-line border-t border-line">
          {sortedReasons.map((r, i) => {
            const tone = r.severity === 'block' ? 'text-bad' : r.severity === 'warn' ? 'text-warn' : 'text-ok';
            return (
              <li key={i} className="flex items-start gap-3 py-2.5 text-sm">
                <Icon
                  name={r.severity === 'block' ? 'x' : r.severity === 'warn' ? 'alert' : 'check'}
                  className={`mt-0.5 h-4 w-4 shrink-0 ${tone}`}
                />
                <span className="flex-1 text-ink">{r.text}</span>
                <span className="font-mono text-[10.5px] text-faint">{r.code}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
