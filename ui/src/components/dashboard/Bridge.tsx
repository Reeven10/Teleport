import type { DeviceInfo, LinkQuality, MigrationStatus, Stats } from '@contract';
import { formatMbps, formatMs, formatOs, formatPercent } from '../../utils/formatters.ts';
import { LiveDot } from '../ui/Icon.tsx';

const ACTIVE = ['CONNECTING', 'EVALUATING', 'TRANSFERRING', 'VALIDATING', 'FENCING', 'STARTING_TARGET', 'ROLLING_BACK'];
const PHASE_LABEL: Record<string, string> = {
  CONNECTING: 'Connecting',
  EVALUATING: 'Evaluating',
  TRANSFERRING: 'Transferring checkpoints',
  VALIDATING: 'Validating on target',
  FENCING: 'Fencing the source',
  STARTING_TARGET: 'Starting on target',
  ROLLING_BACK: 'Rolling back',
  COMPLETED: 'Moved',
  ROLLED_BACK: 'Rolled back',
  FAILED: 'Not migrated',
};

interface BridgeProps {
  self?: DeviceInfo;
  peer?: DeviceInfo;
  selfStats?: Stats;
  peerStats?: Stats;
  link: LinkQuality | null;
  migration: MigrationStatus | null;
}

function Node({ device, stats, align }: { device?: DeviceInfo; stats?: Stats; align: 'left' | 'right' }) {
  const online = stats?.online ?? false;
  return (
    <div className={`min-w-0 ${align === 'right' ? 'text-right' : ''}`}>
      <p className={`tp-label flex items-center gap-2 ${align === 'right' ? 'justify-end' : ''}`}>
        {align === 'left' ? 'This laptop' : 'Peer'}
        {device && <LiveDot tone={online ? 'ok' : 'bad'} live={online} />}
      </p>
      <p className="mt-1 truncate font-serif text-2xl leading-tight text-ink">{device?.name ?? 'Not paired'}</p>
      <p className="mt-0.5 font-mono text-[11px] text-faint">
        {device ? `${formatOs(device.os)} · ${device.arch} · ${device.cpuCores} cores` : 'Pair a device to start'}
      </p>
    </div>
  );
}

/** Both laptops and the live link between them; while a migration runs, packets travel across it. */
export function Bridge({ self, peer, selfStats, peerStats, link, migration }: BridgeProps) {
  const peerOnline = peerStats?.online ?? false;
  const active = Boolean(migration && ACTIVE.includes(migration.phase));
  const outgoing = migration ? migration.sourceId === self?.id : true;
  const pct = migration && migration.bytesTotal > 0 ? Math.min(100, (migration.bytesDone / migration.bytesTotal) * 100) : 0;
  const path = outgoing ? 'M 24 40 C 180 4, 420 4, 576 40' : 'M 576 40 C 420 4, 180 4, 24 40';
  const lineTone = !peer ? 'text-line' : peerOnline ? 'text-faint' : 'text-bad/40';

  return (
    <section data-testid="link-bridge" className="tp-card overflow-hidden">
      <div className="grid grid-cols-1 items-center gap-6 p-6 md:grid-cols-[1fr_minmax(260px,1.4fr)_1fr] md:p-7">
        <Node device={self} stats={selfStats} align="left" />

        <div className="relative">
          <svg viewBox="0 0 600 56" className={`h-14 w-full ${lineTone}`} aria-hidden="true">
            <path
              d="M 24 40 C 180 4, 420 4, 576 40"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeDasharray="3 6"
              style={peerOnline ? { animation: `tp-dash ${active ? 0.5 : 1.6}s linear infinite` } : undefined}
            />
            {active && (
              <path
                d={path}
                fill="none"
                className="stroke-accent"
                strokeWidth="2"
                strokeLinecap="round"
                pathLength={100}
                strokeDasharray={`${pct} 100`}
                style={{ transition: 'stroke-dasharray 400ms ease' }}
              />
            )}
            {active &&
              [0, 0.45, 0.9].map((delay) => (
                <circle key={delay} r="3" className="fill-accent">
                  <animateMotion dur="1.4s" begin={`${delay}s`} repeatCount="indefinite" path={path} />
                </circle>
              ))}
            <circle cx="24" cy="40" r="5" className="fill-ink" />
            <circle cx="576" cy="40" r="5" className={peerOnline ? 'fill-accent' : 'fill-line-strong'} />
          </svg>
          <div className="mt-1 flex items-baseline justify-center gap-5 text-center">
            {active && migration ? (
              <p className="text-xs text-ink">
                <span className="font-medium">{PHASE_LABEL[migration.phase] ?? migration.phase}</span>
                <span className="ml-2 font-mono text-faint">{pct.toFixed(0)}%</span>
              </p>
            ) : link && peerOnline ? (
              <>
                <Readout label="round trip" value={formatMs(link.rttMs)} />
                <Readout label={link.link} value={formatMbps(link.mbps)} />
                <Readout label="loss" value={formatPercent(link.lossPct, 1)} />
              </>
            ) : (
              <p className="text-xs text-faint">{peer ? 'Peer is offline' : 'No link yet'}</p>
            )}
          </div>
        </div>

        <Node device={peer} stats={peerStats} align="right" />
      </div>

      {migration && !active && migration.phase !== 'IDLE' && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-line bg-raised px-7 py-2.5 text-xs text-muted">
          <span>
            Last migration:{' '}
            <span className={migration.phase === 'COMPLETED' ? 'text-ok' : 'text-bad'}>
              {PHASE_LABEL[migration.phase] ?? migration.phase}
            </span>
          </span>
          <span>
            Authority epoch <span className="font-mono text-ink">{migration.authority.epoch}</span>
          </span>
          {migration.interruptionMs != null && (
            <span>
              Paused for <span className="font-mono text-ink">{migration.interruptionMs} ms</span>
            </span>
          )}
        </div>
      )}
    </section>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex flex-col items-center">
      <span className="font-mono text-[13px] text-ink">{value}</span>
      <span className="text-[10.5px] text-faint">{label}</span>
    </span>
  );
}
