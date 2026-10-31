import type { DeviceInfo, Stats } from '@contract';
import type { MetricHistoryPoint } from '../../store/types.ts';
import {
  formatArch,
  formatMb,
  formatOs,
  formatPercent,
  formatRelativeTime,
} from '../../utils/formatters.ts';
import { MetricSparkline } from './MetricSparkline.tsx';

interface DeviceCardProps {
  device?: DeviceInfo;
  stats?: Stats;
  history?: MetricHistoryPoint[];
  roleTitle: string;
  isSelf?: boolean;
}

export function DeviceCard({ device, stats, history = [], roleTitle, isSelf = false }: DeviceCardProps) {
  const isOnline = stats?.online ?? false;
  const isSimulated = device?.simulated || stats?.simulated;

  if (!device) {
    return (
      <div className="flex min-h-[460px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white/50 p-8 text-center dark:border-slate-800 dark:bg-slate-900/40">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <h3 className="mt-4 text-base font-semibold text-slate-700 dark:text-slate-200">No Peer Device Selected</h3>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Pair with a remote Teleport agent or select a peer to view live metrics.
        </p>
      </div>
    );
  }

  const cpuColor = (stats?.cpuPct ?? 0) > 85 ? '#f43f5e' : (stats?.cpuPct ?? 0) > 60 ? '#f59e0b' : '#10b981';
  const memColor = (stats?.memPct ?? 0) > 85 ? '#f43f5e' : (stats?.memPct ?? 0) > 70 ? '#f59e0b' : '#38bdf8';

  return (
    <div
      data-testid={`device-card-${device.id}`}
      className={`relative flex flex-col rounded-xl border transition-all ${
        isSelf
          ? 'border-indigo-200 bg-white/90 shadow-sm dark:border-indigo-900/50 dark:bg-slate-900/80'
          : 'border-slate-200 bg-white/90 shadow-sm dark:border-slate-800 dark:bg-slate-900/80'
      } p-6 backdrop-blur-sm`}
    >
      {/* Header */}
      <div className="flex items-start justify-between border-b border-slate-100 pb-4 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ${
                isSelf
                  ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950/80 dark:text-indigo-300'
                  : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/80 dark:text-emerald-300'
              }`}
            >
              {roleTitle}
            </span>
            {isSimulated && (
              <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-bold text-amber-800 dark:bg-amber-950/80 dark:text-amber-300">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                SIMULATED
              </span>
            )}
          </div>
          <h2 className="mt-1 text-xl font-bold tracking-tight text-slate-900 dark:text-white">{device.name}</h2>
          <p className="font-mono text-xs text-slate-500 dark:text-slate-400">ID: {device.id}</p>
        </div>

        {/* Online / Offline Status */}
        <div className="flex items-center gap-2">
          {isOnline ? (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500"></span>
              </span>
              ONLINE
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-rose-500 dark:text-rose-400">
              <span className="h-2.5 w-2.5 rounded-full bg-rose-500" />
              OFFLINE
            </span>
          )}
        </div>
      </div>

      {/* Hardware / Platform Specs Strip */}
      <div className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div className="rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/50">
          <span className="text-slate-500 dark:text-slate-400">OS & Platform</span>
          <p className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{formatOs(device.os)}</p>
          <p className="font-mono text-[10px] text-slate-400 dark:text-slate-500">{formatArch(device.arch)}</p>
        </div>

        <div className="rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/50">
          <span className="text-slate-500 dark:text-slate-400">CPU Compute</span>
          <p className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{device.cpuCores} Cores</p>
          <p className="text-[10px] text-slate-400 dark:text-slate-500">Agent v{device.agentVersion}</p>
        </div>

        <div className="rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/50">
          <span className="text-slate-500 dark:text-slate-400">RAM Installed</span>
          <p className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{formatMb(device.ramMb)}</p>
          <p className="text-[10px] text-slate-400 dark:text-slate-500">
            {stats ? `${formatMb(stats.memFreeMb)} free` : '—'}
          </p>
        </div>

        <div className="rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/50">
          <span className="text-slate-500 dark:text-slate-400">GPU Device</span>
          <p className="mt-0.5 truncate font-medium text-slate-800 dark:text-slate-200" title={device.gpu ?? 'None'}>
            {device.gpu ?? 'None (CPU only)'}
          </p>
          <p className="text-[10px] text-slate-400 dark:text-slate-500">
            {device.gpu ? 'Accelerated' : 'Unaccelerated'}
          </p>
        </div>
      </div>

      {/* Live Gauges & 60s Sparklines */}
      <div className="mt-5 space-y-4">
        {/* CPU Gauge & Sparkline */}
        <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 dark:border-slate-800/60 dark:bg-slate-800/30">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              CPU Load
            </span>
            <span className="font-mono text-lg font-bold" style={{ color: cpuColor }}>
              {stats ? formatPercent(stats.cpuPct) : '—'}
            </span>
          </div>
          {/* Progress bar */}
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div
              className="h-full transition-all duration-500"
              style={{
                width: `${Math.min(100, stats?.cpuPct ?? 0)}%`,
                backgroundColor: cpuColor,
              }}
            />
          </div>
          {/* 60s Recharts Sparkline */}
          <div className="mt-2">
            <div className="flex items-center justify-between text-[10px] text-slate-400 dark:text-slate-500 mb-1">
              <span>60s Trend</span>
              <span>Live Recharts</span>
            </div>
            <MetricSparkline data={history} dataKey="cpuPct" color={cpuColor} domain={[0, 100]} />
          </div>
        </div>

        {/* Memory Gauge & Sparkline */}
        <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 dark:border-slate-800/60 dark:bg-slate-800/30">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Memory
              </span>
              <span className="ml-2 text-[11px] text-slate-400 dark:text-slate-500">
                {stats ? `${formatMb(device.ramMb * (stats.memPct / 100))} / ${formatMb(device.ramMb)}` : ''}
              </span>
            </div>
            <span className="font-mono text-lg font-bold text-sky-500 dark:text-sky-400">
              {stats ? formatPercent(stats.memPct) : '—'}
            </span>
          </div>
          {/* Progress bar */}
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div
              className="h-full bg-sky-500 transition-all duration-500 dark:bg-sky-400"
              style={{ width: `${Math.min(100, stats?.memPct ?? 0)}%` }}
            />
          </div>
          {/* 60s Recharts Sparkline */}
          <div className="mt-2">
            <div className="flex items-center justify-between text-[10px] text-slate-400 dark:text-slate-500 mb-1">
              <span>60s Trend</span>
              <span>{stats ? `${formatMb(stats.memFreeMb)} Free` : ''}</span>
            </div>
            <MetricSparkline data={history} dataKey="memPct" color={memColor} domain={[0, 100]} />
          </div>
        </div>

        {/* Disk Space */}
        <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 dark:border-slate-800/60 dark:bg-slate-800/30">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Storage Available
            </span>
            <span className="font-mono text-base font-bold text-slate-800 dark:text-slate-200">
              {stats ? formatMb(stats.diskFreeMb) : formatMb(device.diskFreeMb)}
            </span>
          </div>
          <div className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
            Snapshot partition headroom for checkpoint validation
          </div>
        </div>

        {/* Battery with Charging State / Honest Desktop State */}
        <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 dark:border-slate-800/60 dark:bg-slate-800/30">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Power & Battery
            </span>
            {stats?.battery ? (
              <span
                className={`flex items-center gap-1 font-mono text-base font-bold ${
                  stats.battery.pct <= 20
                    ? 'text-rose-500 dark:text-rose-400'
                    : stats.battery.pct <= 40
                      ? 'text-amber-500 dark:text-amber-400'
                      : 'text-emerald-500 dark:text-emerald-400'
                }`}
              >
                {stats.battery.charging && (
                  <svg className="h-4 w-4 animate-bounce text-amber-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clipRule="evenodd" />
                  </svg>
                )}
                {formatPercent(stats.battery.pct)}
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">
                <svg className="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                AC Power
              </span>
            )}
          </div>

          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {stats?.battery ? (
              stats.battery.charging ? (
                <span className="text-emerald-600 dark:text-emerald-400">Connected to charger (Charging)</span>
              ) : (
                <span className={stats.battery.pct <= 20 ? 'font-semibold text-rose-500 animate-pulse' : ''}>
                  {stats.battery.pct <= 20 ? 'Battery Critical (< 20%) — Triggering migration' : 'Running on battery'}
                </span>
              )
            ) : (
              <span className="italic text-slate-400 dark:text-slate-500">
                Desktop workstation (No internal battery sensor)
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Footer / Stale Timestamp */}
      <div className="mt-auto pt-4 text-right text-[11px] text-slate-400 dark:text-slate-500">
        Last updated: {stats ? formatRelativeTime(stats.ts) : 'Awaiting data'}
      </div>
    </div>
  );
}
