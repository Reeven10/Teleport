import type { Phase } from '@contract';

interface PhaseStepperProps {
  phase: Phase;
}

const ORDERED_STEPS: { key: Phase; label: string }[] = [
  { key: 'CONNECTING', label: '1. Connecting' },
  { key: 'EVALUATING', label: '2. Evaluating' },
  { key: 'TRANSFERRING', label: '3. Transferring' },
  { key: 'VALIDATING', label: '4. Validating' },
  { key: 'FENCING', label: '5. Fencing' },
  { key: 'STARTING_TARGET', label: '6. Starting Target' },
  { key: 'COMPLETED', label: '7. Completed' },
];

export function PhaseStepper({ phase }: PhaseStepperProps) {
  const isRolledBack = phase === 'ROLLED_BACK' || phase === 'ROLLING_BACK';
  const isRemoteAccess = phase === 'REMOTE_ACCESS';
  const isFailed = phase === 'FAILED';

  const currentIdx = ORDERED_STEPS.findIndex((s) => s.key === phase);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center border-b border-slate-100 pb-3 dark:border-slate-800">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Cutover Pipeline Stepper
          </span>
          <div className="flex items-center gap-2 mt-0.5">
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              Phase: <span className="font-mono text-indigo-600 dark:text-indigo-400">{phase}</span>
            </h3>
          </div>
        </div>

        {/* Branch alerts */}
        {isRolledBack && (
          <div className="flex items-center gap-2 rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700 dark:bg-rose-950/60 dark:text-rose-300">
            <span className="h-2 w-2 rounded-full bg-rose-500 animate-ping" />
            BRANCH: ROLLED BACK TO SOURCE (Authority Retained)
          </div>
        )}
        {isRemoteAccess && (
          <div className="flex items-center gap-2 rounded-lg bg-cyan-50 px-3 py-1.5 text-xs font-bold text-cyan-700 dark:bg-cyan-950/60 dark:text-cyan-300">
            <span className="h-2 w-2 rounded-full bg-cyan-500 animate-pulse" />
            BRANCH: REMOTE ACCESS STREAMING ACTIVE
          </div>
        )}
        {isFailed && (
          <div className="flex items-center gap-2 rounded-lg bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700 dark:bg-rose-950/60 dark:text-rose-300">
            MIGRATION FAILED
          </div>
        )}
      </div>

      {/* Normal Progression Stepper */}
      <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {ORDERED_STEPS.map((step, idx) => {
          const isPassed = !isRolledBack && !isRemoteAccess && currentIdx >= 0 && idx < currentIdx;
          const isCurrent = !isRolledBack && !isRemoteAccess && step.key === phase;
          const isFuture = !isRolledBack && !isRemoteAccess && (currentIdx < 0 || idx > currentIdx);

          let stepStyle = 'border-slate-200 bg-slate-50 text-slate-400 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-500';
          let dotStyle = 'bg-slate-300 dark:bg-slate-700';

          if (isPassed) {
            stepStyle = 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300';
            dotStyle = 'bg-emerald-500';
          } else if (isCurrent) {
            stepStyle = 'border-indigo-400 bg-indigo-50/90 text-indigo-900 shadow-xs ring-1 ring-indigo-400/50 dark:border-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-200';
            dotStyle = 'bg-indigo-500 animate-pulse';
          } else if (isRolledBack && step.key === 'TRANSFERRING') {
            stepStyle = 'border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300';
            dotStyle = 'bg-rose-500';
          }

          return (
            <div
              key={step.key}
              data-testid={`step-${step.key.toLowerCase()}`}
              className={`flex flex-col items-start rounded-lg border p-2.5 transition-all ${stepStyle}`}
            >
              <div className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${dotStyle}`} />
                <span className="text-[11px] font-bold truncate">{step.label}</span>
              </div>
              <span className="mt-1 text-[10px] opacity-80">
                {isPassed ? 'Validated' : isCurrent ? 'Active...' : isFuture ? 'Pending' : isRolledBack ? 'Aborted' : 'Bypassed'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
