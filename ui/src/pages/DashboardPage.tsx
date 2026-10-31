import { useTeleport } from '../store/useTeleport.ts';
import { DeviceCard } from '../components/dashboard/DeviceCard.tsx';
import { LinkCard } from '../components/dashboard/LinkCard.tsx';
import { DemoControlPanel } from '../components/dashboard/DemoControlPanel.tsx';

export function DashboardPage() {
  const { state } = useTeleport();

  const thisDevice = state.devices[state.thisDeviceId];
  const peerDevice = state.peerDeviceId ? state.devices[state.peerDeviceId] : undefined;

  const statsA = state.stats[state.thisDeviceId];
  const statsB = state.peerDeviceId ? state.stats[state.peerDeviceId] : undefined;

  const historyA = state.history60s[state.thisDeviceId] ?? [];
  const historyB = state.peerDeviceId ? state.history60s[state.peerDeviceId] ?? [] : [];

  const rec = state.recommendation;
  const mig = state.migrationStatus;

  return (
    <div className="space-y-6">
      {/* Top Section Header */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
            Live Telemetry & Workload Mesh
          </h1>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Real-time node telemetry stream over encrypted WebSocket (/ws/events)
          </p>
        </div>

        {/* Quick Vitals Summary Pill */}
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-2xs dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
            Active Devices: {Object.keys(state.devices).length}
          </span>
          <span className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-2xs dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
            Epoch: {state.authority?.epoch ?? 1}
          </span>
        </div>
      </div>

      {/* Simulated Demo Control Panel & Fault Injector */}
      <DemoControlPanel />

      {/* Orchestrator Recommendation Alert Banner (if any) */}
      {rec && (
        <div className="rounded-xl border border-amber-300/80 bg-amber-50/90 p-4 shadow-sm dark:border-amber-700/60 dark:bg-amber-950/40">
          <div className="flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-500 text-white shadow-xs">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-amber-800 dark:text-amber-300">
                  Orchestrator Recommendation: {rec.decision}
                </span>
                <span className="rounded bg-amber-200/80 px-1.5 py-0.5 text-[10px] font-bold text-amber-900 dark:bg-amber-900 dark:text-amber-200">
                  TRIGGER: {rec.trigger.toUpperCase()}
                </span>
              </div>
              <ul className="mt-1.5 space-y-1 text-xs text-amber-900/90 dark:text-amber-200/90">
                {rec.reasons.map((r, i) => (
                  <li key={i} className="flex items-center gap-1.5">
                    <span className={r.severity === 'pass' ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}>
                      {r.severity === 'pass' ? '✓' : '⚠'}
                    </span>
                    <span>{r.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Migration Cutover Live Banner (if active) */}
      {mig && mig.phase !== 'IDLE' && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50/90 p-4 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/40">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-3 w-3">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex h-3 w-3 rounded-full bg-indigo-500"></span>
              </span>
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-300">
                  Migration Phase: {mig.phase}
                </span>
                <span className="ml-2 font-mono text-xs text-indigo-950 dark:text-indigo-200">
                  Authority: {mig.authority.state} @ Epoch {mig.authority.epoch}
                </span>
              </div>
            </div>

            {mig.interruptionMs && (
              <span className="text-xs font-semibold text-indigo-800 dark:text-indigo-300">
                Interruption time: <span className="font-mono font-bold">{mig.interruptionMs} ms</span>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Two Large Device Cards Side-by-Side + Link Card Between Them */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_auto_1fr]">
        {/* Device A (Host / This Device) */}
        <DeviceCard
          device={thisDevice}
          stats={statsA}
          history={historyA}
          roleTitle="Device A (This Node / Host)"
          isSelf={true}
        />

        {/* Link Quality Card (Between Them) */}
        <div className="flex items-center justify-center">
          <LinkCard link={state.link} peerOnline={statsB?.online ?? false} />
        </div>

        {/* Device B (Peer Device / Target) */}
        <DeviceCard
          device={peerDevice}
          stats={statsB}
          history={historyB}
          roleTitle="Device B (Peer Node / Target)"
          isSelf={false}
        />
      </div>
    </div>
  );
}
