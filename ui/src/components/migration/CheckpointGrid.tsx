import type { Authority, CheckpointMetric, CheckpointRecord, Phase } from '@contract';
import { formatBytes } from '../../utils/formatters.ts';
import { Icon } from '../ui/Icon.tsx';

interface CheckpointGridProps {
  checkpoints: CheckpointRecord[];
  authority?: Authority;
  phase?: Phase;
  metrics?: CheckpointMetric[];
}

const FRIENDLY: Record<string, string> = {
  code: 'Launcher code',
  project: 'Project files',
  session: 'Editor session',
  counter: 'Counter state',
};

const STAGE: Record<CheckpointMetric['stage'], string> = {
  initial: 'full copy',
  catchup: 'live catch-up',
  delta: 'final delta',
  precopy: 'pre-copied',
};

type UnitState = 'queued' | 'moving' | 'verified' | 'failed' | 'skipped';

function unitState(c: CheckpointRecord, phase: Phase | undefined, skipped: boolean): UnitState {
  if (skipped) return 'skipped';
  if (c.validated) return 'verified';
  if ((phase === 'ROLLED_BACK' || phase === 'FAILED') && c.sent) return 'failed';
  return c.sent ? 'moving' : 'queued';
}

const SEGMENT: Record<UnitState, string> = {
  queued: 'bg-line',
  moving: 'bg-accent animate-pulse',
  verified: 'bg-ink',
  failed: 'bg-bad',
  skipped: 'bg-ok/60',
};

const LABEL: Record<UnitState, string> = {
  queued: 'queued',
  moving: 'sending',
  verified: 'verified',
  failed: 'not verified',
  skipped: 'already there',
};

/**
 * The workload as a train of checkpoint units. Each unit is sent in 256 KB chunks, hashed (SHA-256) and
 * verified on the target; units the target already holds are skipped, so migrating back only sends diffs.
 */
export function CheckpointGrid({ checkpoints, authority, phase, metrics = [] }: CheckpointGridProps) {
  const total = checkpoints.length;
  const validatedCount = checkpoints.filter((c) => c.validated).length;
  const onSource = !authority || authority.state === 'SOURCE';
  const fenced = authority?.state === 'FENCED';
  const skippedIds = new Set(metrics.filter((m) => m.skipped).map((m) => m.id));
  const stagesById = new Map<string, Set<string>>();
  for (const m of metrics) {
    if (m.skipped) continue;
    const set = stagesById.get(m.id) ?? new Set<string>();
    set.add(STAGE[m.stage]);
    stagesById.set(m.id, set);
  }
  const weight = (c: CheckpointRecord) => Math.max(1, Math.sqrt(c.sizeBytes));

  return (
    <div className="tp-card p-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="tp-label">Checkpoints</p>
          <p className="mt-1 font-serif text-2xl text-ink">
            <span data-testid="checkpoint-counter">
              {validatedCount} of {total} validated
            </span>
          </p>
        </div>
        <p
          data-testid="authority-invariant-note"
          className={`max-w-sm text-xs sm:text-right ${onSource ? 'text-muted' : fenced ? 'text-warn' : 'text-ok'}`}
        >
          {onSource
            ? 'Authority has not moved yet. Workload remains active on Source.'
            : fenced
              ? 'Source fenced (paused at cutover). Handover in progress.'
              : 'Authority handed over to Target. Workload active on Target.'}
        </p>
      </div>

      {total === 0 ? (
        <p className="mt-6 border-t border-dashed border-line pt-6 text-center text-sm text-faint">
          Start a migration to see each checkpoint travel and get verified.
        </p>
      ) : (
        <>
          <div className="mt-5 flex h-2.5 w-full gap-1" aria-hidden="true">
            {checkpoints.map((c) => {
              const st = unitState(c, phase, skippedIds.has(c.id));
              return (
                <div
                  key={c.id}
                  className={`h-full rounded-full transition-colors duration-500 ${SEGMENT[st]}`}
                  style={{ flexGrow: weight(c), flexBasis: 0, minWidth: 10 }}
                  title={`${FRIENDLY[c.id] ?? c.id}: ${LABEL[st]}`}
                />
              );
            })}
          </div>

          <ul className="mt-5 divide-y divide-line border-t border-line">
            {checkpoints.map((c) => {
              const st = unitState(c, phase, skippedIds.has(c.id));
              const stages = [...(stagesById.get(c.id) ?? [])];
              return (
                <li key={c.id} data-testid={`checkpoint-tile-${c.id}`} className="grid grid-cols-[1.2rem_1fr_auto_auto] items-center gap-3 py-2.5 text-sm">
                  <span className={`h-2 w-2 rounded-full ${SEGMENT[st].replace(' animate-pulse', '')}`} />
                  <span className="min-w-0">
                    <span className="text-ink">{FRIENDLY[c.id] ?? c.id.replace('chk-', '').replace(/-/g, ' ')}</span>
                    <span className="ml-2 font-mono text-[10.5px] text-faint">
                      {c.id} · {c.sha256 ? `sha ${c.sha256.slice(0, 10)}` : 'not hashed yet'}
                    </span>
                    {stages.length > 0 && <span className="ml-2 text-[11px] text-muted">{stages.join(' + ')}</span>}
                  </span>
                  <span className="font-mono text-xs text-muted">{formatBytes(c.sizeBytes)}</span>
                  <span
                    className={`flex w-28 items-center justify-end gap-1 text-xs ${
                      st === 'verified' ? 'text-ink' : st === 'failed' ? 'text-bad' : st === 'moving' ? 'text-accent' : st === 'skipped' ? 'text-ok' : 'text-faint'
                    }`}
                  >
                    {st === 'verified' && <Icon name="check" className="h-3.5 w-3.5" />}
                    {LABEL[st]}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
