import { useTeleport } from '../store/useTeleport.ts';

export function MigrationPage() {
  const { state } = useTeleport();
  const mig = state.migrationStatus;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
          Migration Engine & Authority Cutover
        </h1>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Stateful checkpoint transfer pipeline, SHA-256 validation, and single-lease epoch fencing
        </p>
      </div>

      <div className="rounded-2xl border border-dashed border-indigo-300 bg-indigo-50/40 p-8 text-center dark:border-indigo-900 dark:bg-indigo-950/20">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-100 text-indigo-600 dark:bg-indigo-900/60 dark:text-indigo-400">
          <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
          </svg>
        </div>
        <h2 className="mt-4 text-base font-bold text-slate-900 dark:text-white">Migration Engine (Phase 2 Placeholder)</h2>
        <p className="mx-auto mt-2 max-w-lg text-xs text-slate-600 dark:text-slate-400">
          This view will host the live 6-stage Checkpoint Grid, chunk-by-chunk validation progress,
          and the millisecond interruption timer during epoch fencing cutover.
        </p>

        {mig && (
          <div className="mt-6 inline-block rounded-xl border border-indigo-200 bg-white p-4 text-left shadow-sm dark:border-indigo-800 dark:bg-slate-900">
            <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
              Mock Stream Status Detected
            </span>
            <p className="mt-1 text-xs font-semibold text-slate-800 dark:text-slate-200">
              Active Phase: <span className="font-mono text-indigo-500">{mig.phase}</span> · Authority: {mig.authority.state} (Epoch {mig.authority.epoch})
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
