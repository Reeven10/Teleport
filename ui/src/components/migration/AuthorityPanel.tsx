import type { Authority, DeviceInfo } from '@contract';

interface AuthorityPanelProps {
  authority?: Authority | null;
  deviceA?: DeviceInfo;
  deviceB?: DeviceInfo;
}

export function AuthorityPanel({ authority, deviceA, deviceB }: AuthorityPanelProps) {
  const state = authority?.state ?? 'SOURCE';
  const epoch = authority?.epoch ?? 1;

  const isSource = state === 'SOURCE';
  const isFenced = state === 'FENCED';
  const isTarget = state === 'TARGET';

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      {/* Header */}
      <div className="flex flex-col justify-between gap-2 border-b border-slate-100 pb-3 sm:flex-row sm:items-center dark:border-slate-800">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Single-Lease Distributed Authority
          </span>
          <h3 className="text-base font-bold text-slate-900 dark:text-white mt-0.5">
            Workload Authority & Monotonic Epoch
          </h3>
        </div>

        {/* Epoch Counter */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Lease Epoch:</span>
          <span
            data-testid="authority-epoch"
            className="rounded-lg bg-slate-100 px-3 py-1 font-mono text-base font-extrabold text-slate-900 dark:bg-slate-800 dark:text-white shadow-2xs"
          >
            Epoch {epoch}
          </span>
        </div>
      </div>

      {/* Live Diagram of Device A and Device B */}
      <div className="mt-6 grid grid-cols-1 items-center gap-6 md:grid-cols-[1fr_auto_1fr]">
        {/* Device A Node */}
        <div
          data-testid="authority-node-a"
          className={`flex flex-col rounded-2xl border p-5 transition-all duration-500 ${
            isSource
              ? 'border-blue-400 bg-blue-50/70 shadow-md ring-2 ring-blue-500/30 dark:border-blue-700 dark:bg-blue-950/40'
              : isFenced
                ? 'border-amber-400 bg-amber-50/70 shadow-md ring-2 ring-amber-500/30 dark:border-amber-700 dark:bg-amber-950/40'
                : 'border-slate-200 bg-slate-50/50 opacity-60 dark:border-slate-800 dark:bg-slate-800/30'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Source Node
            </span>
            <span
              data-testid="authority-state-source"
              className={`rounded-full px-2.5 py-0.5 text-xs font-black tracking-wide ${
                isSource
                  ? 'bg-blue-500 text-white shadow-xs'
                  : isFenced
                    ? 'bg-amber-500 text-white animate-pulse'
                    : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
              }`}
            >
              {isFenced ? 'FENCED' : isSource ? 'SOURCE' : 'RELEASED'}
            </span>
          </div>

          <h4 className="mt-2 text-base font-bold text-slate-900 dark:text-white">
            {deviceA?.name ?? 'Device A (Host)'}
          </h4>
          <span className="font-mono text-xs text-slate-400 dark:text-slate-500">
            {deviceA?.id ?? 'device-a'}
          </span>

          {/* Active Workload Execution Banner */}
          <div className="mt-4 rounded-lg bg-white/80 p-2.5 text-xs dark:bg-slate-900/80">
            {isSource ? (
              <div className="flex items-center gap-2 font-semibold text-blue-700 dark:text-blue-300">
                <span className="h-2.5 w-2.5 rounded-full bg-blue-500 animate-ping" />
                <span>Workload Running Here (Active Authority)</span>
              </div>
            ) : isFenced ? (
              <div className="flex items-center gap-2 font-semibold text-amber-700 dark:text-amber-300">
                <span className="h-2.5 w-2.5 rounded-full bg-amber-500 animate-pulse" />
                <span>Execution Fenced (I/O Frozen for Cutover)</span>
              </div>
            ) : (
              <div className="text-slate-400 dark:text-slate-500 italic">
                Execution Terminated (Cleaned Up Post-Handover)
              </div>
            )}
          </div>
        </div>

        {/* Central Handover Animation Vector */}
        <div className="flex flex-col items-center justify-center py-2 text-center">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Handover Vector
          </span>
          <div className="my-2 flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${isSource ? 'bg-blue-500 animate-ping' : 'bg-slate-300'}`} />
            <div className="h-0.5 w-16 bg-gradient-to-r from-blue-500 via-amber-500 to-emerald-500" />
            <div className={`h-2 w-2 rounded-full ${isTarget ? 'bg-emerald-500 animate-ping' : 'bg-slate-300'}`} />
          </div>
          <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400">
            {isFenced ? 'Fencing & Verifying' : isTarget ? 'Authority Transfer Complete' : 'Pre-Cutover Transfer'}
          </span>
        </div>

        {/* Device B Node */}
        <div
          data-testid="authority-node-b"
          className={`flex flex-col rounded-2xl border p-5 transition-all duration-500 ${
            isTarget
              ? 'border-emerald-400 bg-emerald-50/70 shadow-md ring-2 ring-emerald-500/30 dark:border-emerald-700 dark:bg-emerald-950/40'
              : 'border-slate-200 bg-slate-50/50 opacity-60 dark:border-slate-800 dark:bg-slate-800/30'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Target Node
            </span>
            <span
              data-testid="authority-state-target"
              className={`rounded-full px-2.5 py-0.5 text-xs font-black tracking-wide ${
                isTarget
                  ? 'bg-emerald-500 text-white shadow-xs animate-pulse'
                  : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
              }`}
            >
              {isTarget ? 'TARGET' : 'STANDBY'}
            </span>
          </div>

          <h4 className="mt-2 text-base font-bold text-slate-900 dark:text-white">
            {deviceB?.name ?? 'Device B (Target)'}
          </h4>
          <span className="font-mono text-xs text-slate-400 dark:text-slate-500">
            {deviceB?.id ?? 'device-b'}
          </span>

          {/* Active Workload Execution Banner */}
          <div className="mt-4 rounded-lg bg-white/80 p-2.5 text-xs dark:bg-slate-900/80">
            {isTarget ? (
              <div className="flex items-center gap-2 font-semibold text-emerald-700 dark:text-emerald-300">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500 animate-ping" />
                <span>Workload Running Here (Holder at Epoch {epoch})</span>
              </div>
            ) : (
              <div className="text-slate-400 dark:text-slate-500 italic">
                Awaiting Final Checkpoint Validation
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
