export function HistoryPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
          Migration & Decision History
        </h1>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Persistent audit logs of past device connections, feasibility decisions with reasons, and transfer metrics
        </p>
      </div>

      <div className="flex min-h-[440px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/50 p-8 text-center dark:border-slate-800 dark:bg-slate-900/30">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h2 className="mt-4 text-base font-bold text-slate-900 dark:text-white">Audit History Store (Phase 4 Placeholder)</h2>
        <p className="mx-auto mt-2 max-w-lg text-xs text-slate-600 dark:text-slate-400">
          Historical records stored in SQLite by P3 (/api/history/*) will be browseable here with step-by-step
          post-mortem replay and interruption analytics.
        </p>
      </div>
    </div>
  );
}

