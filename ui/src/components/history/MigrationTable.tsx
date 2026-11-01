import { useState, useMemo } from 'react';
import type { Decision, MigrationStatus, Phase } from '@contract';
import { formatBytes } from '../../utils/formatters.ts';

interface MigrationTableProps {
  migrations: MigrationStatus[];
  onSelectMigration: (migration: MigrationStatus) => void;
  selectedDeviceId: string | null;
  onClearDeviceFilter: () => void;
}

export function MigrationTable({
  migrations,
  onSelectMigration,
  selectedDeviceId,
  onClearDeviceFilter,
}: MigrationTableProps) {
  const [filterDecision, setFilterDecision] = useState<string>('ALL');
  const [filterOutcome, setFilterOutcome] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const filteredMigrations = useMemo(() => {
    return migrations.filter((m) => {
      if (selectedDeviceId && m.sourceId !== selectedDeviceId && m.targetId !== selectedDeviceId) {
        return false;
      }
      if (filterDecision !== 'ALL' && m.decision !== filterDecision) {
        return false;
      }
      if (filterOutcome !== 'ALL' && m.phase !== filterOutcome) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesWorkload = m.workloadId.toLowerCase().includes(q);
        const matchesId = m.id.toLowerCase().includes(q);
        const matchesSource = m.sourceId.toLowerCase().includes(q);
        const matchesTarget = m.targetId.toLowerCase().includes(q);
        if (!matchesWorkload && !matchesId && !matchesSource && !matchesTarget) {
          return false;
        }
      }
      return true;
    });
  }, [migrations, selectedDeviceId, filterDecision, filterOutcome, searchQuery]);

  const getPhaseBadge = (phase: Phase) => {
    switch (phase) {
      case 'COMPLETED':
        return 'bg-ok-soft text-ok';
      case 'ROLLED_BACK':
        return 'bg-bad-soft text-bad';
      case 'REMOTE_ACCESS':
        return 'bg-raised text-steel';
      case 'FAILED':
        return 'bg-bad-soft text-bad';
      default:
        return 'border border-line text-ink';
    }
  };

  const getDecisionBadge = (decision?: Decision) => {
    switch (decision) {
      case 'MIGRATE':
        return 'border-line-strong text-ink';
      case 'REMOTE_ACCESS':
        return 'border-steel/40 text-steel';
      case 'STAY':
        return 'border-line text-muted';
      default:
        return 'border-line text-muted';
    }
  };

  const formatTimestamp = (ts: number) => {
    return new Date(ts).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-line pb-4">
        <div>
          <h2 className="font-serif text-xl text-ink">
            Migration Execution History ({filteredMigrations.length})
          </h2>
          <p className="text-xs text-muted">
            Recorded cutovers, rollback events, checkpoint verifications, and downtime metrics
          </p>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2">
          {selectedDeviceId && (
            <span className="flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700 dark:bg-blue-950/60 dark:text-blue-300">
              Device: {selectedDeviceId}
              <button
                type="button"
                onClick={onClearDeviceFilter}
                className="ml-1 font-bold hover:text-blue-900"
              >
                ×
              </button>
            </span>
          )}

          <input
            type="text"
            data-testid="input-history-search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search workload or ID..."
            className="rounded-lg border border-line-strong bg-surface px-2.5 py-1 text-xs text-ink/85 focus:border-ink/40 focus:outline-hidden"
          />

          <select
            data-testid="select-filter-decision"
            value={filterDecision}
            onChange={(e) => setFilterDecision(e.target.value)}
            className="rounded-lg border border-line-strong bg-surface px-2 py-1 text-xs font-semibold text-ink/85 focus:border-ink/40 focus:outline-hidden"
          >
            <option value="ALL">All Decisions</option>
            <option value="MIGRATE">MIGRATE</option>
            <option value="REMOTE_ACCESS">REMOTE_ACCESS</option>
            <option value="STAY">STAY</option>
          </select>

          <select
            data-testid="select-filter-outcome"
            value={filterOutcome}
            onChange={(e) => setFilterOutcome(e.target.value)}
            className="rounded-lg border border-line-strong bg-surface px-2 py-1 text-xs font-semibold text-ink/85 focus:border-ink/40 focus:outline-hidden"
          >
            <option value="ALL">All Outcomes</option>
            <option value="COMPLETED">COMPLETED</option>
            <option value="ROLLED_BACK">ROLLED_BACK</option>
            <option value="REMOTE_ACCESS">REMOTE_ACCESS</option>
            <option value="FAILED">FAILED</option>
          </select>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-line text-[11px] font-medium text-faint">
              <th className="pb-3 pl-2">Started</th>
              <th className="pb-3">Workload</th>
              <th className="pb-3">Route (Source → Target)</th>
              <th className="pb-3">Decision</th>
              <th className="pb-3">Outcome</th>
              <th className="pb-3">Checkpoints</th>
              <th className="pb-3">Interruption</th>
              <th className="pb-3 pr-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/60">
            {filteredMigrations.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-xs italic text-faint">
                  No migration history records match current filters.
                </td>
              </tr>
            ) : (
              filteredMigrations.map((m) => {
                const validatedCount = m.checkpoints.filter((c) => c.validated).length;
                const totalCheckpoints = m.checkpoints.length;

                return (
                  <tr
                    key={m.id}
                    data-testid={`migration-row-${m.id}`}
                    onClick={() => onSelectMigration(m)}
                    className="cursor-pointer transition-colors hover:bg-raised"
                  >
                    <td className="py-3 pl-2 font-mono text-[11px] text-muted whitespace-nowrap">
                      {formatTimestamp(m.startedAt)}
                    </td>
                    <td className="py-3 font-semibold text-ink">
                      <div>{m.workloadId}</div>
                      <div className="font-mono text-[10px] text-faint">{m.id}</div>
                    </td>
                    <td className="py-3">
                      <div className="flex items-center gap-1.5 font-mono text-[11px]">
                        <span className="font-semibold text-ink">{m.sourceId}</span>
                        <span className="text-faint">→</span>
                        <span className="font-semibold text-ink">{m.targetId}</span>
                      </div>
                      <div className="tp-label">
                        {m.link} · {formatBytes(m.bytesDone)}
                      </div>
                    </td>
                    <td className="py-3">
                      <span className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase ${getDecisionBadge(m.decision)}`}>
                        {m.decision || 'MIGRATE'}
                      </span>
                    </td>
                    <td className="py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase ${getPhaseBadge(m.phase)}`}>
                        {m.phase}
                      </span>
                    </td>
                    <td className="py-3 font-mono text-[11px]">
                      {totalCheckpoints > 0 ? (
                        <span>
                          {validatedCount} / {totalCheckpoints} ok
                        </span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="py-3 font-mono text-[11px]">
                      {m.interruptionMs !== undefined && m.interruptionMs !== null ? (
                        <span className="font-bold text-emerald-600 dark:text-emerald-400">
                          {m.interruptionMs} ms
                        </span>
                      ) : m.error ? (
                        <span className="text-rose-500 font-semibold">Aborted</span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-2 text-right">
                      <button
                        type="button"
                        data-testid={`btn-inspect-${m.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectMigration(m);
                        }}
                        className="rounded-lg bg-raised px-2.5 py-1 text-xs font-semibold text-ink/85 hover:bg-slate-200"
                      >
                        Replay
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
