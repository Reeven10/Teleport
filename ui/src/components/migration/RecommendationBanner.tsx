import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTeleport } from '../../store/useTeleport.ts';
import { apiStartMigration } from '../../api.ts';

export function RecommendationBanner() {
  const { state, clearRecommendation } = useTeleport();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const rec = state.recommendation;
  if (!rec) return null;

  const isMigrate = rec.decision === 'MIGRATE';
  const isRemote = rec.decision === 'REMOTE_ACCESS';

  const badgeColor =
    rec.decision === 'MIGRATE'
      ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300'
      : rec.decision === 'REMOTE_ACCESS'
      ? 'bg-sky-100 text-sky-700 dark:bg-sky-900/50 dark:text-sky-300'
      : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';

  const handleAccept = async () => {
    setErrorMsg(null);
    if (isRemote) {
      clearRecommendation();
      navigate('/remote');
      return;
    }

    if (isMigrate) {
      setSubmitting(true);
      try {
        const target = rec.targetId || state.peerDeviceId || 'device-b';
        if (state.agentReachable) {
          await apiStartMigration(rec.workloadId, target, 'user_command');
        }
        clearRecommendation();
      } catch (err: unknown) {
        setErrorMsg(err instanceof Error ? err.message : 'Failed to start migration');
      } finally {
        setSubmitting(false);
      }
    } else {
      clearRecommendation();
    }
  };

  const handleDismiss = () => {
    clearRecommendation();
  };

  return (
    <div
      data-testid="recommendation-banner"
      className="relative overflow-hidden rounded-2xl border border-indigo-200/90 bg-gradient-to-r from-indigo-50/90 via-sky-50/70 to-purple-50/90 p-4 shadow-sm dark:border-indigo-800/80 dark:from-indigo-950/40 dark:via-slate-900/40 dark:to-purple-950/40"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm dark:bg-indigo-500">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-400">
                Orchestrator Proactive Recommendation
              </span>
              <span className={`rounded-md px-2 py-0.5 text-[10px] font-extrabold uppercase ${badgeColor}`}>
                {rec.decision}
              </span>
              <span className="text-[10px] font-medium text-slate-500">
                Triggered by <span className="font-semibold text-slate-700 dark:text-slate-300">{rec.trigger}</span>
              </span>
            </div>
            <p className="mt-0.5 text-xs font-semibold text-slate-800 dark:text-slate-200">
              Workload <span className="font-mono text-indigo-600 dark:text-indigo-400">{rec.workloadId}</span>
              {rec.targetId ? ` → Target ${rec.targetId}` : ''}:{' '}
              {rec.reasons[0]?.text || 'Automated policy recommendation'}
            </p>
            {errorMsg && (
              <p className="mt-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400">
                {errorMsg}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 self-end sm:self-center">
          <button
            type="button"
            data-testid="recommendation-dismiss"
            onClick={handleDismiss}
            className="rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-200/60 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Dismiss
          </button>
          <button
            type="button"
            data-testid="recommendation-accept"
            disabled={submitting}
            onClick={handleAccept}
            className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-bold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-600"
          >
            {submitting ? 'Executing...' : isRemote ? 'Launch Remote' : 'Accept & Proceed'}
          </button>
        </div>
      </div>
    </div>
  );
}
