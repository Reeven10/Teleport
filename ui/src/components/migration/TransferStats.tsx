import { useEffect, useRef, useState } from 'react';
import type { LinkType, MigrationMetrics } from '@contract';
import { formatBytes, formatLinkType } from '../../utils/formatters.ts';

interface TransferStatsProps {
  bytesDone: number;
  bytesTotal: number;
  linkType?: LinkType;
  interruptionMs?: number | null;
  estInterruptionMs?: number;
  speedMbps?: number;
  metrics?: MigrationMetrics;
  migrationId?: string;
}

/** Throughput samples taken in the browser from bytesDone, for a live trace while bytes move. */
function useThroughput(bytesDone: number, key: string | undefined) {
  const [samples, setSamples] = useState<number[]>([]);
  const last = useRef<{ t: number; b: number } | null>(null);

  useEffect(() => {
    setSamples([]);
    last.current = null;
  }, [key]);

  useEffect(() => {
    const now = performance.now();
    const prev = last.current;
    last.current = { t: now, b: bytesDone };
    if (!prev || now - prev.t < 150 || bytesDone < prev.b) return;
    const mbps = ((bytesDone - prev.b) * 8) / 1e6 / ((now - prev.t) / 1000);
    setSamples((s) => [...s.slice(-59), mbps]);
  }, [bytesDone]);

  return samples;
}

function Trace({ samples }: { samples: number[] }) {
  if (samples.length < 2) {
    return <div className="h-10 border-b border-dashed border-line" />;
  }
  const max = Math.max(...samples, 1);
  const pts = samples.map((v, i) => `${(i / (samples.length - 1)) * 100},${38 - (v / max) * 34}`).join(' ');
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-10 w-full border-b border-line" aria-hidden="true">
      <polyline points={`0,40 ${pts} 100,40`} className="fill-accent/10" stroke="none" />
      <polyline points={pts} fill="none" className="stroke-accent" strokeWidth="1.25" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function TransferStats({
  bytesDone,
  bytesTotal,
  linkType = 'cable',
  interruptionMs,
  speedMbps = 85.0,
  metrics,
  migrationId,
}: TransferStatsProps) {
  const samples = useThroughput(bytesDone, migrationId);
  const live = samples.length > 0 ? samples[samples.length - 1] : undefined;
  const throughput = metrics?.throughputMbps ?? live ?? speedMbps;
  const pct = bytesTotal > 0 ? Math.min(100, Math.round((bytesDone / bytesTotal) * 100)) : 0;
  const cut = metrics?.cutover;

  return (
    <div className="tp-card flex flex-col p-6">
      <div className="flex items-baseline justify-between">
        <p className="tp-label">Transfer</p>
        <span className="tp-chip">{formatLinkType(linkType)}</span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-5">
        <div>
          <p className="font-mono text-[1.75rem] leading-tight font-light text-ink">{pct}%</p>
          <p className="text-xs text-muted">
            {formatBytes(bytesDone)} of {formatBytes(bytesTotal)}
          </p>
          <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-line">
            <div className="h-full rounded-full bg-ink transition-all duration-300" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div>
          <p className="font-mono text-[1.75rem] leading-tight font-light text-ink">
            {throughput >= 1 ? throughput.toFixed(1) : ((throughput * 1000) / 8).toFixed(0)}
          </p>
          <p className="text-xs text-muted">
            {throughput >= 1 ? 'Mbps' : 'KB/s'}
            {metrics ? ' average' : live != null ? ' now' : ' link estimate'}
          </p>
          <div className="mt-1">
            <Trace samples={samples} />
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-xl bg-raised p-4">
        <div className="flex items-baseline justify-between">
          <p className="tp-label">Workload paused for</p>
          <p className="text-[10.5px] text-faint">fence → target running</p>
        </div>
        {interruptionMs != null ? (
          <p data-testid="interruption-time" className="mt-1 font-serif text-5xl leading-none text-ink">
            {interruptionMs} ms
          </p>
        ) : (
          <p className="mt-1 font-serif text-3xl leading-tight text-faint italic">still running</p>
        )}
        <p className="mt-2 text-xs text-muted">
          {cut
            ? `${cut.catchupRounds} live catch-up round${cut.catchupRounds === 1 ? '' : 's'}, then only ${formatBytes(cut.deltaBytes)} sent while paused.`
            : 'The workload keeps running while checkpoints copy; it only pauses for the final small delta.'}
          {metrics && metrics.bytesSkipped > 0 ? ` ${formatBytes(metrics.bytesSkipped)} skipped (already on the target).` : ''}
        </p>
      </div>
    </div>
  );
}
