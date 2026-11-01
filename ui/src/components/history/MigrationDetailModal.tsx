import type { MigrationStatus, Reason } from '@contract';
import { Icon } from '../ui/Icon.tsx';
import { formatBytes } from '../../utils/formatters.ts';

interface MigrationDetailModalProps {
  migration: MigrationStatus | null;
  onClose: () => void;
}

export function MigrationDetailModal({ migration, onClose }: MigrationDetailModalProps) {
  if (!migration) return null;

  const isCompleted = migration.phase === 'COMPLETED';
  const isRolledBack = migration.phase === 'ROLLED_BACK';
  const isRemote = migration.phase === 'REMOTE_ACCESS';

  const formatTimestamp = (ts?: number) => {
    if (!ts) return '—';
    return new Date(ts).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getSeverityIcon = (sev: Reason['severity']) => {
    switch (sev) {
      case 'pass':
        return (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
            <Icon name="check" className="h-3 w-3" />
          </span>
        );
      case 'warn':
        return (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-600 dark:bg-amber-950/60 dark:text-amber-400">
            !
          </span>
        );
      case 'block':
        return (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-rose-100 text-rose-600 dark:bg-rose-950/60 dark:text-rose-400">
            <Icon name="x" className="h-3 w-3" />
          </span>
        );
    }
  };

  // Phases reconstruction for timeline replay
  const timelineSteps = [
    { name: 'CONNECTING', desc: 'Secure peer transport link handshake', status: 'done' },
    { name: 'EVALUATING', desc: 'Hardware & state feasibility verification', status: 'done' },
    { name: 'TRANSFERRING', desc: 'Checkpoint chunk serialization and transport', status: 'done' },
    {
      name: 'VALIDATING',
      desc: 'SHA-256 integrity verification across boundary',
      status: isRolledBack ? 'failed' : 'done',
    },
    {
      name: 'FENCING',
      desc: 'Single-lease epoch cutover',
      status: isCompleted ? 'done' : isRolledBack ? 'reverted' : 'skipped',
    },
    {
      name: isRolledBack ? 'ROLLED_BACK' : isRemote ? 'REMOTE_ACCESS' : 'COMPLETED',
      desc: isRolledBack
        ? 'Workload safely unfenced and resumed on Source'
        : isRemote
        ? 'Viewport stream activated for operator'
        : 'Workload execution claimed on Target node',
      status: isRolledBack ? 'reverted' : 'done',
    },
  ];

  return (
    <div
      data-testid="migration-detail-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4 overflow-y-auto"
    >
      <div className="relative my-8 w-full max-w-3xl rounded-2xl border border-line bg-surface p-6 shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-line pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-ink">
                Migration Post-Mortem & Step Replay
              </h2>
              <span
                data-testid="detail-phase-badge"
                className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase ${
                  isCompleted
                    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300'
                    : isRolledBack
                    ? 'bg-rose-100 text-rose-800 dark:bg-rose-950/70 dark:text-rose-300'
                    : isRemote
                    ? 'bg-sky-100 text-sky-800 dark:bg-sky-950/70 dark:text-sky-300'
                    : 'border border-line text-ink'
                }`}
              >
                {migration.phase}
              </span>
            </div>
            <p className="mt-1 font-mono text-xs text-faint">
              ID: {migration.id} · Workload: <span className="font-bold text-ink/85">{migration.workloadId}</span>
            </p>
          </div>

          <button
            type="button"
            data-testid="btn-close-detail"
            onClick={onClose}
            className="rounded-xl p-2 text-faint hover:bg-raised hover:text-slate-600"
          >
            <Icon name="x" className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 space-y-6 max-h-[75vh] overflow-y-auto pr-1">
          {/* Key Metric Banners: Interruption, Bytes, Route, Epoch */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl bg-raised p-3">
              <span className="tp-label">Cutover Interruption</span>
              <p data-testid="detail-interruption" className="mt-1 font-mono text-lg font-semibold text-emerald-600 dark:text-emerald-400">
                {migration.interruptionMs !== undefined && migration.interruptionMs !== null
                  ? `${migration.interruptionMs} ms`
                  : 'N/A (Rolled back)'}
              </p>
            </div>

            <div className="rounded-xl bg-raised p-3">
              <span className="tp-label">State Volume</span>
              <p className="mt-1 font-mono text-lg font-semibold text-ink">
                {formatBytes(migration.bytesDone)}
              </p>
            </div>

            <div className="rounded-xl bg-raised p-3">
              <span className="tp-label">Route & Transport</span>
              <p className="mt-1 text-xs font-semibold text-ink">
                <span className="text-ink font-mono">{migration.sourceId}</span> →{' '}
                <span className="text-emerald-600 dark:text-emerald-400 font-mono">{migration.targetId}</span>
              </p>
              <span className="tp-label">{migration.link} link</span>
            </div>

            <div className="rounded-xl bg-raised p-3">
              <span className="tp-label">Authority Epoch</span>
              <p data-testid="detail-epoch" className="mt-1 font-mono text-lg font-semibold text-ink">
                Epoch {migration.authority.epoch}
              </p>
              <span className="text-[10px] font-semibold text-muted">
                Holder: {migration.authority.holder} ({migration.authority.state})
              </span>
            </div>
          </div>

          {/* Migration Detailed Performance Metrics (if available) */}
          {migration.metrics && (
            <div className="rounded-xl border border-line bg-raised p-3.5">
              <h4 className="tp-label">
                Wire Metrics & Deduplication
              </h4>
              <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs font-mono">
                <div>
                  <span className="text-[10px] text-faint">Throughput:</span>
                  <p className="font-bold text-ink">
                    {migration.metrics.throughputMbps.toFixed(1)} Mbps
                  </p>
                </div>
                <div>
                  <span className="text-[10px] text-faint">Wire Duration:</span>
                  <p className="font-bold text-ink">
                    {migration.metrics.durationMs} ms
                  </p>
                </div>
                <div>
                  <span className="text-[10px] text-faint">Skipped/Dedup:</span>
                  <p className="font-bold text-ink">
                    {formatBytes(migration.metrics.bytesSkipped)}
                  </p>
                </div>
                <div>
                  <span className="text-[10px] text-faint">Chunk Buffer:</span>
                  <p className="font-bold text-ink">
                    {Math.round(migration.metrics.chunkSize / 1024)} KB
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Error Banner if rolled back */}
          {migration.error && (
            <div data-testid="detail-error-banner" className="rounded-xl border border-rose-200 bg-rose-50 p-3.5 text-xs text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
              <div className="flex items-center gap-2 font-bold uppercase tracking-wide">
                <span className="h-2 w-2 rounded-full bg-rose-500" />
                Rollback & Integrity Abort Trigger
              </div>
              <p className="mt-1 font-semibold">{migration.error}</p>
            </div>
          )}

          {/* Step-by-Step Phase Timeline Replay */}
          <div>
            <h3 className="tp-label">
              Execution Phase Progression Timeline
            </h3>
            <div className="mt-3 space-y-2">
              {timelineSteps.map((step, idx) => {
                const isFail = step.status === 'failed';
                const isRev = step.status === 'reverted';
                const isSkip = step.status === 'skipped';

                return (
                  <div
                    key={step.name}
                    className={`flex items-start gap-3 rounded-xl border p-3 text-xs ${
                      isFail
                        ? 'border-rose-200 bg-rose-50/70 text-rose-900 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200'
                        : isRev
                        ? 'border-amber-200 bg-amber-50/70 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200'
                        : isSkip
                        ? 'border-slate-100 bg-slate-50/40 text-slate-400 opacity-60 dark:border-slate-800 dark:bg-slate-900/20'
                        : 'border-slate-200 bg-white text-slate-800 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-200'
                    }`}
                  >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold text-ink/85">
                      {idx + 1}
                    </span>
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="font-bold uppercase tracking-wider">{step.name}</span>
                        <span className="font-mono text-[10px] uppercase font-semibold opacity-75">
                          {step.status}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] opacity-80">{step.desc}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Decision Evaluation & Reasons */}
          <div>
            <h3 className="tp-label">
              Feasibility Decision & Rule Evidence
            </h3>
            <div className="mt-2 space-y-2">
              {migration.reasons.map((r, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2.5 rounded-xl border border-line bg-raised p-2.5 text-xs"
                >
                  {getSeverityIcon(r.severity)}
                  <div>
                    <span className="font-mono text-[10px] font-bold uppercase text-faint">
                      {r.code}
                    </span>
                    <p className="text-ink/85">{r.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Checkpoint Validation Results */}
          {migration.checkpoints.length > 0 && (
            <div>
              <h3 className="tp-label">
                Transferred State Checkpoints ({migration.checkpoints.length})
              </h3>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-line text-[11px] font-medium text-faint">
                      <th className="pb-2">Seq</th>
                      <th className="pb-2">Checkpoint ID</th>
                      <th className="pb-2">Size</th>
                      <th className="pb-2">SHA-256 Digest</th>
                      <th className="pb-2">State</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {migration.checkpoints.map((ck) => (
                      <tr key={ck.id}>
                        <td className="py-2 font-mono text-[11px] text-faint">{ck.seq}</td>
                        <td className="py-2 font-semibold text-ink">{ck.id}</td>
                        <td className="py-2 font-mono text-[11px] text-muted">
                          {formatBytes(ck.sizeBytes)}
                        </td>
                        <td className="py-2 font-mono text-[10px] text-faint max-w-[200px] truncate">
                          {ck.sha256}
                        </td>
                        <td className="py-2">
                          <span
                            className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${
                              ck.validated
                                ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300'
                                : ck.sent
                                ? 'bg-rose-100 text-rose-800 dark:bg-rose-950/70 dark:text-rose-300'
                                : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                            }`}
                          >
                            {ck.validated ? 'VALIDATED' : ck.sent ? 'CORRUPT' : 'WAITING'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Timestamps */}
          <div className="flex justify-between text-[11px] text-faint pt-2 border-t border-line">
            <span>Started: {formatTimestamp(migration.startedAt)}</span>
            <span>Ended: {formatTimestamp(migration.endedAt)}</span>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            Close Replay
          </button>
        </div>
      </div>
    </div>
  );
}
