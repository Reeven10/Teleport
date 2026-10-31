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
        return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300';
      case 'ROLLED_BACK':
        return 'bg-rose-100 text-rose-800 dark:bg-rose-950/70 dark:text-rose-300';
      case 'REMOTE_ACCESS':
        return 'bg-sky-100 text-sky-800 dark:bg-sky-950/70 dark:text-sky-300';
      case 'FAILED':
        return 'bg-red-100 text-red-800 dark:bg-red-950/70 dark:text-red-300';
      default:
        return 'bg-blue-100 text-blue-800 dark:bg-blue-950/70 dark:text-blue-300';
    }
  };

  const getDecisionBadge = (decision?: Decision) => {
    switch (decision) {
      case 'MIGRATE':
        return 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900';
      case 'REMOTE_ACCESS':
        return 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-900';
      case 'STAY':
        return 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700';
      default:
        return 'bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700';
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
    <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-4 dark:border-slate-800">
        <div>
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            Migration Execution History ({filteredMigrations.length})
          </h2>
          <p className="text-xs text-slate-500">
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
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-800 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />

          <select
            data-testid="select-filter-decision"
            value={filterDecision}
            onChange={(e) => setFilterDecision(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-800 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
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
            className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-800 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
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
            <tr className="border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:border-slate-800">
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
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
            {filteredMigrations.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-xs italic text-slate-400">
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
                    className="cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  >
                    <td className="py-3 pl-2 font-mono text-[11px] text-slate-500 whitespace-nowrap">
                      {formatTimestamp(m.startedAt)}
                    </td>
                    <td className="py-3 font-semibold text-slate-800 dark:text-slate-200">
                      <div>{m.workloadId}</div>
                      <div className="font-mono text-[10px] text-slate-400">{m.id}</div>
                    </td>
                    <td className="py-3">
                      <div className="flex items-center gap-1.5 font-mono text-[11px]">
                        <span className="font-semibold text-blue-600 dark:text-blue-400">{m.sourceId}</span>
                        <span className="text-slate-400">→</span>
                        <span className="font-semibold text-emerald-600 dark:text-emerald-400">{m.targetId}</span>
                      </div>
                      <div className="text-[10px] uppercase font-bold text-slate-400">
                        {m.link} · {formatBytes(m.bytesDone)}
                      </div>
                    </td>
                    <td className="py-3">
                      <span className={`rounded-md border px-2 py-0.5 text-[10px] font-extrabold uppercase ${getDecisionBadge(m.decision)}`}>
                        {m.decision || 'MIGRATE'}
                      </span>
                    </td>
                    <td className="py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-extrabold uppercase ${getPhaseBadge(m.phase)}`}>
                        {m.phase}
                      </span>
                    </td>
                    <td className="py-3 font-mono text-[11px]">
                      {totalCheckpoints > 0 ? (
                        <span>
                          {validatedCount} / {totalCheckpoints} ok
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
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
                        <span className="text-slate-400">—</span>
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
                        className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
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
