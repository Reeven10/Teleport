import { memo } from 'react';
import type { DeviceInfo, Stats } from '@contract';
import type { MetricHistoryPoint } from '../../store/types.ts';
import { formatArch, formatMb, formatOs, formatPercent, formatRelativeTime } from '../../utils/formatters.ts';
import { LiveDot } from '../ui/Icon.tsx';
import { MetricSparkline } from './MetricSparkline.tsx';

interface DeviceCardProps {
  device?: DeviceInfo;
  stats?: Stats;
  history?: MetricHistoryPoint[];
  roleTitle: string;
  isSelf?: boolean;
}

function tone(pct: number, warn: number, bad: number): { text: string; stroke: string } {
  if (pct > bad) return { text: 'text-bad', stroke: 'var(--tp-bad)' };
  if (pct > warn) return { text: 'text-warn', stroke: 'var(--tp-warn)' };
  return { text: 'text-ink', stroke: 'var(--tp-ink)' };
}

export const DeviceCard = memo(function DeviceCard({ device, stats, history = [], roleTitle, isSelf = false }: DeviceCardProps) {
  if (!device) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center rounded-2xl border border-dashed border-line-strong p-8 text-center">
        <p className="font-serif text-2xl text-ink">No peer yet</p>
        <p className="mt-2 max-w-xs text-sm text-muted">
          Click Pair Device and pick the other laptop from Nearby devices. Its live stats show up here.
        </p>
      </div>
    );
  }

  const online = stats?.online ?? false;
  const simulated = device.simulated || stats?.simulated;
  const cpu = tone(stats?.cpuPct ?? 0, 60, 85);
  const mem = tone(stats?.memPct ?? 0, 75, 90);
  const battery = stats?.battery;

  return (
    <div data-testid={`device-card-${device.id}`} className="tp-card flex flex-col p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="tp-label">{roleTitle}</p>
          <h2 className="mt-1 truncate font-serif text-[1.65rem] leading-tight text-ink">{device.name}</h2>
          <p className="mt-0.5 font-mono text-[10.5px] text-faint">{device.id}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className={`flex items-center gap-1.5 text-xs ${online ? 'text-ok' : 'text-bad'}`}>
            <LiveDot tone={online ? 'ok' : 'bad'} live={online} />
            {online ? 'Online' : 'Offline'}
          </span>
          {simulated && <span className="tp-chip border-warn/40 bg-warn-soft py-0 text-warn">SIMULATED</span>}
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-4 gap-3 border-y border-line py-3.5 text-xs">
        <Spec label="System" value={formatOs(device.os)} sub={formatArch(device.arch)} />
        <Spec label="CPU" value={`${device.cpuCores} cores`} sub={`agent ${device.agentVersion}`} />
        <Spec label="Memory" value={formatMb(device.ramMb)} sub={stats ? `${formatMb(stats.memFreeMb)} free` : ''} />
        <Spec label="GPU" value={device.gpu ?? 'None'} sub={device.gpu ? 'accelerated' : 'CPU only'} />
      </dl>

      <div className="mt-5 grid grid-cols-2 gap-5">
        <Metric label="CPU" value={stats ? formatPercent(stats.cpuPct) : '—'} tone={cpu.text}>
          <MetricSparkline data={history} dataKey="cpuPct" color={cpu.stroke} domain={[0, 100]} />
        </Metric>
        <Metric label="Memory" value={stats ? formatPercent(stats.memPct) : '—'} tone={mem.text}>
          <MetricSparkline data={history} dataKey="memPct" color={mem.stroke} domain={[0, 100]} />
        </Metric>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-5 border-t border-line pt-4 text-xs">
        <div>
          <p className="tp-label">Free storage</p>
          <p className="mt-1 font-mono text-base text-ink">{formatMb(stats ? stats.diskFreeMb : device.diskFreeMb)}</p>
        </div>
        <div>
          <p className="tp-label">Power</p>
          {battery ? (
            <>
              <div className="mt-1 flex items-baseline gap-2">
                <span className={`font-mono text-base ${battery.pct <= 20 ? 'text-bad' : 'text-ink'}`}>
                  {formatPercent(battery.pct)}
                </span>
                <span className="text-faint">{battery.charging ? 'charging' : 'on battery'}</span>
              </div>
              <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-line">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${battery.pct <= 20 ? 'bg-bad' : 'bg-ok'}`}
                  style={{ width: `${Math.min(100, battery.pct)}%` }}
                />
              </div>
            </>
          ) : (
            <p className="mt-1 text-sm text-muted">Mains power</p>
          )}
        </div>
      </div>

      <p className="mt-auto pt-4 text-right text-[10.5px] text-faint">
        {isSelf ? 'This laptop · ' : ''}updated {stats ? formatRelativeTime(stats.ts) : 'never'}
      </p>
    </div>
  );
});

function Spec({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10.5px] text-faint">{label}</dt>
      <dd className="mt-0.5 truncate text-ink" title={value}>
        {value}
      </dd>
      <dd className="truncate font-mono text-[10px] text-faint">{sub}</dd>
    </div>
  );
}

function Metric({ label, value, tone, children }: { label: string; value: string; tone: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="tp-label">{label}</span>
        <span className="text-[10px] text-faint">last 60 s</span>
      </div>
      <p className={`mt-0.5 font-mono text-[1.75rem] leading-tight font-light ${tone}`}>{value}</p>
      <div className="mt-2">{children}</div>
    </div>
  );
}
