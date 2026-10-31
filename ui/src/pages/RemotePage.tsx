export function RemotePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
          Remote Access Viewport
        </h1>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Zero-install adaptive screen capture (mss) and remote input injection (pynput) with mutual consent
        </p>
      </div>

      <div className="flex min-h-[440px] flex-col items-center justify-center rounded-2xl border border-dashed border-sky-300 bg-sky-50/40 p-8 text-center dark:border-sky-900 dark:bg-sky-950/20">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-100 text-sky-600 dark:bg-sky-900/60 dark:text-sky-400">
          <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        </div>
        <h2 className="mt-4 text-base font-bold text-slate-900 dark:text-white">Remote Access Service (Phase 3 Placeholder)</h2>
        <p className="mx-auto mt-2 max-w-lg text-xs text-slate-600 dark:text-slate-400">
          When the Feasibility Engine blocks migration (e.g. pinned GPU or incompatible OS),
          this HTML5 canvas viewport streams low-latency JPEG frames and passes mouse/keyboard events over WebSockets.
        </p>
      </div>
    </div>
  );
}

