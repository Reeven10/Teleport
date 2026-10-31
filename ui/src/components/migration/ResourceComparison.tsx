import type { DeviceInfo, Stats } from '@contract';
import { useTeleport } from '../../store/useTeleport.ts';

interface DeviceTelemetryCardProps {
  role: 'SOURCE' | 'TARGET';
  device?: DeviceInfo;
  stats?: Stats;
}

function DeviceTelemetryCard({ role, device, stats }: DeviceTelemetryCardProps) {
  const isSource = role === 'SOURCE';
  const roleColor = isSource
    ? 'border-blue-300 dark:border-blue-800 bg-blue-50/30 dark:bg-blue-950/20 text-blue-700 dark:text-blue-300'
    : 'border-emerald-300 dark:border-emerald-800 bg-emerald-50/30 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300';

  const cpu = stats ? Math.round(stats.cpuPct) : 0;
  const memPct = stats ? Math.round(stats.memPct) : 0;
  const memTotalMb = device?.ramMb || 16384;
  const memTotalGb = (memTotalMb / 1024).toFixed(1);
  const memUsedGb = ((memTotalMb * (memPct / 100)) / 1024).toFixed(1);
  const diskFreeGb = stats ? (stats.diskFreeMb / 1024).toFixed(1) : '0';

  const getBarColor = (pct: number) => {
    if (pct >= 85) return 'bg-rose-500';
    if (pct >= 70) return 'bg-amber-500';
    return isSource ? 'bg-blue-500' : 'bg-emerald-500';
  };

  const isOnline = stats?.online ?? true;

  return (
    <div
      data-testid={`resource-card-${role.toLowerCase()}`}
      className="flex flex-col rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex items-center justify-between border-b border-slate-100 pb-3 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <span className={`rounded-md px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ${roleColor}`}>
            {role}
          </span>
          <div>
            <h4 className="text-xs font-bold text-slate-800 dark:text-slate-100">
              {device?.name || (isSource ? 'Local Source Node' : 'Remote Peer Node')}
            </h4>
            <p className="font-mono text-[10px] text-slate-400">
              {device?.id || 'unassigned'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              isOnline ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'
            }`}
          />
          <span className="text-[11px] font-medium text-slate-500">
            {isOnline ? 'Active' : 'Offline'}
          </span>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {/* CPU Usage */}
        <div>
          <div className="flex justify-between text-[11px] font-semibold text-slate-600 dark:text-slate-300">
            <span>CPU Compute</span>
            <span className="font-mono">{cpu}%</span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className={`h-full transition-all duration-300 ${getBarColor(cpu)}`}
              style={{ width: `${Math.min(cpu, 100)}%` }}
            />
          </div>
        </div>

        {/* Memory Usage */}
        <div>
          <div className="flex justify-between text-[11px] font-semibold text-slate-600 dark:text-slate-300">
            <span>Memory Allocated</span>
            <span className="font-mono">
              {memUsedGb} / {memTotalGb} GB ({memPct}%)
            </span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className={`h-full transition-all duration-300 ${getBarColor(memPct)}`}
              style={{ width: `${Math.min(memPct, 100)}%` }}
            />
          </div>
        </div>

        {/* Secondary metrics */}
        <div className="grid grid-cols-2 gap-2 pt-1 text-[11px]">
          <div className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800/50">
            <span className="text-[10px] uppercase text-slate-400">Free Storage</span>
            <p className="font-mono font-semibold text-slate-700 dark:text-slate-200">
              {diskFreeGb} GB
            </p>
          </div>
          <div className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800/50">
            <span className="text-[10px] uppercase text-slate-400">Battery Level</span>
            <p className="font-mono font-semibold text-slate-700 dark:text-slate-200">
              {stats?.battery
                ? `${Math.round(stats.battery.pct)}%${stats.battery.charging ? ' ⚡' : ''}`
                : 'AC Powered'}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ResourceComparison() {
  const { state } = useTeleport();
  const thisDev = state.devices[state.thisDeviceId];
  const peerDev = state.peerDeviceId ? state.devices[state.peerDeviceId] : undefined;
  const thisStats = state.stats[state.thisDeviceId];
  const peerStats = state.peerDeviceId ? state.stats[state.peerDeviceId] : undefined;

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/50 p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900/40">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
            Live Node Telemetry Comparison
          </h3>
          <p className="text-[11px] text-slate-500">
            Real-time compute and memory footprints across the migration boundary
          </p>
        </div>
        <span className="rounded-full bg-slate-200/70 px-2.5 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          Dual Telemetry Monitored
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <DeviceTelemetryCard role="SOURCE" device={thisDev} stats={thisStats} />
        <DeviceTelemetryCard role="TARGET" device={peerDev} stats={peerStats} />
      </div>
    </div>
  );
}
