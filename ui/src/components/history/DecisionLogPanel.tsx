import { useState } from 'react';
import type { Decision, DecisionLog, Reason } from '@contract';

interface DecisionLogPanelProps {
  decisions: DecisionLog[];
}

export function DecisionLogPanel({ decisions }: DecisionLogPanelProps) {
  const [filterType, setFilterType] = useState<'ALL' | 'MIGRATE' | 'REMOTE_ACCESS' | 'STAY'>('ALL');

  const filtered = decisions.filter((d) => {
    if (filterType === 'ALL') return true;
    return d.decision === filterType;
  });

  const getDecisionBadge = (decision: Decision) => {
    switch (decision) {
      case 'MIGRATE':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-950/70 dark:text-blue-300';
      case 'REMOTE_ACCESS':
        return 'bg-sky-100 text-sky-800 dark:bg-sky-950/70 dark:text-sky-300';
      case 'STAY':
        return 'bg-amber-100 text-amber-800 dark:bg-amber-950/70 dark:text-amber-300';
    }
  };

  const getSeverityBadge = (sev: Reason['severity']) => {
    switch (sev) {
      case 'pass':
        return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border-emerald-200';
      case 'warn':
        return 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 border-amber-200';
      case 'block':
        return 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border-rose-200';
    }
  };

  const formatTimestamp = (ts: number) => {
    return new Date(ts).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div
      data-testid="decision-log-panel"
      className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-3 dark:border-slate-800">
        <div>
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            Feasibility & Orchestrator Decision Audit Log ({decisions.length})
          </h2>
          <p className="text-xs text-slate-500">
            Audit trail of rule evaluations including migrations, remote access cutovers, and decisions that led to nothing (STAY)
          </p>
        </div>

        {/* Filter buttons */}
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <button
            type="button"
            onClick={() => setFilterType('ALL')}
            className={`rounded-lg px-2.5 py-1 font-semibold ${
              filterType === 'ALL'
                ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            All ({decisions.length})
          </button>
          <button
            type="button"
            onClick={() => setFilterType('MIGRATE')}
            className={`rounded-lg px-2.5 py-1 font-semibold ${
              filterType === 'MIGRATE'
                ? 'bg-blue-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            Migrate
          </button>
          <button
            type="button"
            onClick={() => setFilterType('REMOTE_ACCESS')}
            className={`rounded-lg px-2.5 py-1 font-semibold ${
              filterType === 'REMOTE_ACCESS'
                ? 'bg-sky-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            Remote Access
          </button>
          <button
            type="button"
            data-testid="filter-stay-decisions"
            onClick={() => setFilterType('STAY')}
            className={`rounded-lg px-2.5 py-1 font-semibold ${
              filterType === 'STAY'
                ? 'bg-amber-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            Led to Nothing (Stay)
          </button>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {filtered.length === 0 ? (
          <p className="py-6 text-center text-xs italic text-slate-400">
            No decision audit records match the selected category.
          </p>
        ) : (
          filtered.map((log) => {
            const isStay = log.decision === 'STAY';

            return (
              <div
                key={log.id}
                data-testid={`decision-log-item-${log.id}`}
                className="rounded-xl border border-slate-200/90 bg-slate-50/40 p-4 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/30"
              >
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`rounded-md px-2.5 py-0.5 text-xs font-black uppercase ${getDecisionBadge(log.decision)}`}>
                      {log.decision}
                    </span>
                    <span className="font-semibold text-slate-800 dark:text-slate-200 text-xs">
                      Workload: <span className="font-mono text-indigo-600 dark:text-indigo-400">{log.workloadId}</span>
                    </span>
                    {isStay && (
                      <span className="rounded-md bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 dark:bg-amber-950/50 dark:text-amber-300 border border-amber-200">
                        No Action Taken (Stayed on Source)
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-3 font-mono text-[11px] text-slate-400">
                    <span>Trigger: <strong className="text-slate-600 dark:text-slate-300">{log.trigger}</strong></span>
                    <span>{formatTimestamp(log.ts)}</span>
                  </div>
                </div>

                <div className="mt-3 space-y-1.5 pl-1">
                  {log.reasons.map((r, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span className={`rounded px-1.5 py-0.2 font-mono text-[9px] font-bold uppercase border ${getSeverityBadge(r.severity)}`}>
                        {r.code}
                      </span>
                      <span className="text-slate-600 dark:text-slate-300 text-[11px]">{r.text}</span>
                    </div>
                  ))}
                </div>

                {log.migrationId && (
                  <div className="mt-2 text-[10px] font-mono text-slate-400">
                    Linked Migration: <span className="text-blue-500 font-semibold">{log.migrationId}</span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
