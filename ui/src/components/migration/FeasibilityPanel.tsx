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
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col justify-between gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-center dark:border-slate-800">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Feasibility Engine Evaluation
          </span>
          <h2 className="text-base font-bold text-slate-900 dark:text-white mt-0.5">
            {headline ?? (isMigrate
              ? 'Workload Pre-Flight: Validated for Checkpointed Cutover'
              : isRemote
                ? 'Workload Infeasible for Migration: Remote Access Handoff'
                : 'Workload Migration Blocked: Retained on Local Node')}
          </h2>
        </div>

        {/* Large Decision Badge */}
        <div>
          <span
            data-testid="feasibility-decision-badge"
            className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-black tracking-wide shadow-xs ${
              isMigrate
                ? 'bg-emerald-100 text-emerald-800 ring-2 ring-emerald-500/30 dark:bg-emerald-950 dark:text-emerald-300'
                : isRemote
                  ? 'bg-cyan-100 text-cyan-800 ring-2 ring-cyan-500/30 dark:bg-cyan-950 dark:text-cyan-300'
                  : 'bg-amber-100 text-amber-800 ring-2 ring-amber-500/30 dark:bg-amber-950 dark:text-amber-300'
            }`}
          >
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                isMigrate ? 'bg-emerald-500' : isRemote ? 'bg-cyan-500' : 'bg-amber-500'
              } animate-pulse`}
            />
            {decision}
          </span>
        </div>
      </div>

      {/* Reasons Table / Rows */}
      <div className="mt-4 space-y-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Reason Analysis ({sortedReasons.length} criteria evaluated — blocks prioritized)
        </span>

        {sortedReasons.length === 0 ? (
          <p className="text-xs italic text-slate-400 dark:text-slate-500 pt-1">
            No specific reason records available for this evaluation.
          </p>
        ) : (
          <div className="mt-2 space-y-1.5">
            {sortedReasons.map((r, i) => {
              const isBlock = r.severity === 'block';
              const isWarn = r.severity === 'warn';

              return (
                <div
                  key={i}
                  className={`flex items-start gap-3 rounded-lg border p-2.5 text-xs transition-all ${
                    isBlock
                      ? 'border-rose-300 bg-rose-50/80 text-rose-900 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200'
                      : isWarn
                        ? 'border-amber-200 bg-amber-50/80 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200'
                        : 'border-slate-200 bg-slate-50 text-slate-800 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-200'
                  }`}
                >
                  {/* Icon */}
                  <div className="mt-0.5 shrink-0">
                    {isBlock ? (
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-white font-bold text-[10px]">
                        ✕
                      </span>
                    ) : isWarn ? (
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-white font-bold text-[10px]">
                        ⚠
                      </span>
                    ) : (
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-white font-bold text-[10px]">
                        ✓
                      </span>
                    )}
                  </div>

                  {/* Code and Text */}
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-wider opacity-75">
                        {r.code}
                      </span>
                      <span className="rounded px-1.5 py-0.2 text-[9px] font-bold uppercase tracking-wider bg-white/70 dark:bg-slate-900/70">
                        {r.severity}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs font-medium leading-relaxed">{r.text}</p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

