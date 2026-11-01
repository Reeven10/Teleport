import type { Phase } from '@contract';
import { Icon } from '../ui/Icon.tsx';

interface PhaseStepperProps {
  phase: Phase;
  /** The step that was running when the migration rolled back or failed. */
  failedAt?: Phase | null;
  /** When each step started (ms since epoch), as seen by this dashboard. */
  startedAt?: Partial<Record<Phase, number>>;
  now?: number;
}

const STEPS: { key: Phase; label: string; hint: string }[] = [
  { key: 'CONNECTING', label: 'Connect', hint: 'open the encrypted link' },
  { key: 'EVALUATING', label: 'Evaluate', hint: 'can the target run it?' },
  { key: 'TRANSFERRING', label: 'Transfer', hint: 'send checkpoints, live' },
  { key: 'VALIDATING', label: 'Validate', hint: 'target checks SHA-256' },
  { key: 'FENCING', label: 'Fence', hint: 'pause source, epoch + 1' },
  { key: 'STARTING_TARGET', label: 'Start target', hint: 'resume from state' },
  { key: 'COMPLETED', label: 'Done', hint: 'authority moved' },
];

function seconds(ms: number): string {
  return ms < 1000 ? `${Math.max(0, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function PhaseStepper({ phase, failedAt, startedAt = {}, now = Date.now() }: PhaseStepperProps) {
  const rolledBack = phase === 'ROLLED_BACK' || phase === 'ROLLING_BACK' || phase === 'FAILED';
  const remote = phase === 'REMOTE_ACCESS';
  const stopIdx = rolledBack ? STEPS.findIndex((s) => s.key === (failedAt ?? 'TRANSFERRING')) : -1;
  const currentIdx = rolledBack ? stopIdx : STEPS.findIndex((s) => s.key === phase);
  const done = phase === 'COMPLETED';

  return (
    <div className="tp-card p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="tp-label">Cutover</p>
        {rolledBack && (
          <p className="text-xs text-bad">
            {phase === 'FAILED' ? 'Not migrated' : 'Rolled back'} during {STEPS[stopIdx]?.label.toLowerCase() ?? 'the transfer'}.
            The workload kept running on the source.
          </p>
        )}
        {remote && <p className="text-xs text-steel">Remote access instead: the workload stays where it is.</p>}
      </div>

      <ol className="relative mt-5 grid grid-cols-7">
        <li className="absolute top-[11px] right-[7%] left-[7%] h-px bg-line" aria-hidden="true" />
        {currentIdx > 0 && (
          <li
            className={`absolute top-[11px] left-[7%] h-px transition-all duration-500 ${rolledBack ? 'bg-bad/50' : 'bg-ink'}`}
            style={{ width: `${(Math.min(currentIdx, STEPS.length - 1) / (STEPS.length - 1)) * 86}%` }}
            aria-hidden="true"
          />
        )}
        {STEPS.map((step, idx) => {
          const passed = !remote && currentIdx >= 0 && (idx < currentIdx || (done && idx === currentIdx));
          const current = !remote && !done && idx === currentIdx;
          const failed = rolledBack && idx === stopIdx;
          const t0 = startedAt[step.key];
          const t1 = STEPS.slice(idx + 1).map((s) => startedAt[s.key]).find((t) => t != null);
          const took = t0 != null ? (t1 ?? (current ? now : undefined)) : undefined;

          return (
            <li key={step.key} data-testid={`step-${step.key.toLowerCase()}`} className="relative flex flex-col items-center px-1 text-center">
              <span
                className={`relative z-10 flex h-[23px] w-[23px] items-center justify-center rounded-full border transition-colors ${
                  failed
                    ? 'border-bad bg-bad text-canvas'
                    : passed
                      ? 'border-ink bg-ink text-canvas'
                      : current
                        ? 'border-accent bg-surface'
                        : 'border-line-strong bg-surface'
                }`}
              >
                {failed ? (
                  <Icon name="x" className="h-3 w-3" />
                ) : passed ? (
                  <Icon name="check" className="h-3 w-3" />
                ) : current ? (
                  <>
                    <span className="absolute inset-0 animate-ping rounded-full border border-accent" />
                    <span className="h-2 w-2 rounded-full bg-accent" />
                  </>
                ) : null}
              </span>
              <span className={`mt-2.5 text-[13px] ${current || failed ? 'font-medium text-ink' : passed ? 'text-ink' : 'text-faint'}`}>
                {step.label}
              </span>
              <span className="mt-0.5 hidden text-[10.5px] leading-tight text-faint lg:block">{step.hint}</span>
              <span className="mt-1 h-3.5 font-mono text-[10.5px] text-muted">
                {t0 != null && took != null && step.key !== 'COMPLETED' ? seconds(took - t0) : ''}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
