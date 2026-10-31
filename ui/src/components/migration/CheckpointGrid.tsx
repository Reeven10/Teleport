import type { Authority, CheckpointRecord } from '@contract';
import { formatBytes } from '../../utils/formatters.ts';

interface CheckpointGridProps {
  checkpoints: CheckpointRecord[];
  authority?: Authority;
}

export function CheckpointGrid({ checkpoints, authority }: CheckpointGridProps) {
  const total = checkpoints.length;
  const validatedCount = checkpoints.filter((c) => c.validated).length;
  const isAuthorityOnSource = !authority || authority.state === 'SOURCE';
  const isAuthorityFenced = authority?.state === 'FENCED';

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      {/* Header with Counter and Critical Authority Invariant Note */}
      <div className="flex flex-col justify-between gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-center dark:border-slate-800">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            State Checkpoint Pipeline
          </span>
          <div className="flex items-center gap-2 mt-0.5">
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              Validation Progress:
            </h3>
            <span
              data-testid="checkpoint-counter"
              className="rounded-lg bg-indigo-50 px-2.5 py-1 font-mono text-sm font-extrabold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
            >
              {validatedCount} of {total} validated
            </span>
          </div>
        </div>

        {/* Visible Authority Invariant Callout Note */}
        <div className="rounded-lg border px-3 py-2 text-xs font-semibold">
          {isAuthorityOnSource ? (
            <div
              data-testid="authority-invariant-note"
              className="flex items-center gap-2 text-indigo-800 dark:text-indigo-300"
            >
              <span className="h-2 w-2 rounded-full bg-indigo-500 animate-pulse" />
              <span>Authority has not moved yet. Workload remains active on Source.</span>
            </div>
          ) : isAuthorityFenced ? (
            <div
              data-testid="authority-invariant-note"
              className="flex items-center gap-2 text-amber-800 dark:text-amber-300"
            >
              <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
              <span>Source FENCED (paused at cutover). Handover in progress.</span>
            </div>
          ) : (
            <div
              data-testid="authority-invariant-note"
              className="flex items-center gap-2 text-emerald-800 dark:text-emerald-300"
            >
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span>Authority handed over to Target. Workload active on Target.</span>
            </div>
          )}
        </div>
      </div>

      {/* Grid of Checkpoint Tiles */}
      <div className="mt-4">
        {total === 0 ? (
          <p className="text-xs italic text-slate-400 dark:text-slate-500 py-4 text-center">
            No checkpoints active. Start migration to initiate checkpoint serialization.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {checkpoints.map((chk, idx) => {
              const isValidated = chk.validated === true;
              const isSent = chk.sent === true && !isValidated;
              const isFailed = chk.sent === true && chk.validated === false;

              let cardStyle = 'border-slate-200 bg-slate-50/70 text-slate-600 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400';
              let badgeStyle = 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300';
              let statusLabel = 'Waiting';

              if (isValidated) {
                cardStyle = 'border-emerald-300 bg-emerald-50/80 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-200';
                badgeStyle = 'bg-emerald-200 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-200';
                statusLabel = 'Validated';
              } else if (isFailed) {
                cardStyle = 'border-rose-400 bg-rose-50/90 text-rose-950 ring-2 ring-rose-400/40 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-200';
                badgeStyle = 'bg-rose-200 text-rose-900 dark:bg-rose-900 dark:text-rose-200';
                statusLabel = 'Failed';
              } else if (isSent) {
                cardStyle = 'border-indigo-300 bg-indigo-50/80 text-indigo-950 ring-1 ring-indigo-300 dark:border-indigo-900/60 dark:bg-indigo-950/40 dark:text-indigo-200';
                badgeStyle = 'bg-indigo-200 text-indigo-900 dark:bg-indigo-900 dark:text-indigo-200';
                statusLabel = 'In Transit';
              }

              return (
                <div
                  key={chk.id}
                  data-testid={`checkpoint-tile-${chk.id}`}
                  className={`flex flex-col justify-between rounded-xl border p-3.5 transition-all ${cardStyle}`}
                >
                  {/* Sequence and Status */}
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold opacity-75">#{idx + 1}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${badgeStyle}`}>
                      {statusLabel}
                    </span>
                  </div>

                  {/* Checkpoint Name */}
                  <div className="my-2">
                    <h4 className="text-xs font-bold truncate" title={chk.id}>
                      {chk.id.replace('chk-', '').replace(/-/g, ' ')}
                    </h4>
                    <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                      {formatBytes(chk.sizeBytes)}
                    </span>
                  </div>

                  {/* Progress bar or Checksum */}
                  <div className="mt-auto pt-1">
                    {isValidated ? (
                      <div className="flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400 font-mono truncate">
                        <span>✓</span>
                        <span className="truncate">{chk.sha256.slice(0, 16)}...</span>
                      </div>
                    ) : isSent ? (
                      <div>
                        <div className="flex justify-between text-[10px] mb-1">
                          <span>Verifying</span>
                          <span>65%</span>
                        </div>
                        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                          <div className="h-full bg-indigo-500 animate-pulse" style={{ width: '65%' }} />
                        </div>
                      </div>
                    ) : isFailed ? (
                      <span className="text-[10px] font-bold text-rose-600 dark:text-rose-400">
                        SHA-256 Hash Mismatch
                      </span>
                    ) : (
                      <span className="text-[10px] text-slate-400 dark:text-slate-500">
                        Queued for transfer
                      </span>
                    )}
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
