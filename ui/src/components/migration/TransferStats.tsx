import type { LinkType } from '@contract';
import { formatBytes, formatDuration, formatLinkType } from '../../utils/formatters.ts';

interface TransferStatsProps {
  bytesDone: number;
  bytesTotal: number;
  linkType?: LinkType;
  interruptionMs?: number | null;
  estInterruptionMs?: number;
  speedMbps?: number;
}

export function TransferStats({
  bytesDone,
  bytesTotal,
  linkType = 'cable',
  interruptionMs,
  estInterruptionMs = 150,
  speedMbps = 85.0,
}: TransferStatsProps) {
  const pct = bytesTotal > 0 ? Math.min(100, Math.round((bytesDone / bytesTotal) * 100)) : 0;
  const remainingBytes = Math.max(0, bytesTotal - bytesDone);
  const remainingSec = speedMbps > 0 ? (remainingBytes * 8) / (speedMbps * 1024 * 1024) : 0;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
        Transfer Telemetry & Performance
      </span>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Bytes Done and Total */}
        <div className="rounded-lg bg-slate-50 p-3.5 dark:bg-slate-800/40">
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>Payload Transferred</span>
            <span className="font-bold text-slate-900 dark:text-white">{pct}%</span>
          </div>
          <p className="mt-1 font-mono text-lg font-bold text-slate-900 dark:text-white">
            {formatBytes(bytesDone)}
            <span className="text-xs text-slate-400 font-normal"> / {formatBytes(bytesTotal)}</span>
          </p>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div
              className="h-full bg-indigo-500 transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        {/* Transfer Speed & Link */}
        <div className="rounded-lg bg-slate-50 p-3.5 dark:bg-slate-800/40">
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>Transfer Throughput</span>
            <span className="rounded bg-indigo-100 px-1 text-[10px] font-bold text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300">
              {formatLinkType(linkType)}
            </span>
          </div>
          <p className="mt-1 font-mono text-lg font-bold text-indigo-600 dark:text-indigo-400">
            {speedMbps.toFixed(1)} MB/s
          </p>
          <span className="mt-1 block text-[11px] text-slate-400">
            Estimated remaining: {formatDuration(remainingSec)}
          </span>
        </div>

        {/* Cutover Interruption Time (High Visibility, Back-of-Room Readable) */}
        <div className="col-span-1 rounded-lg border-2 border-indigo-200 bg-indigo-50/60 p-3.5 dark:border-indigo-900 dark:bg-indigo-950/40 sm:col-span-2">
          <div className="flex items-center justify-between text-xs font-bold text-indigo-900 dark:text-indigo-200">
            <span className="uppercase tracking-wider">Workload Interruption Time</span>
            <span className="text-[11px] font-normal text-indigo-700 dark:text-indigo-300">
              Target Budget: &lt; 3000 ms
            </span>
          </div>

          <div className="mt-1.5 flex items-baseline gap-4">
            {interruptionMs != null ? (
              <span
                data-testid="interruption-time"
                className="font-mono text-4xl font-black text-indigo-600 dark:text-indigo-300 tracking-tight"
              >
                {interruptionMs} ms
              </span>
            ) : (
              <span className="font-mono text-2xl font-bold text-slate-400 italic">
                In Transit...
              </span>
            )}

            <div className="text-xs text-slate-600 dark:text-slate-400 font-mono">
              <span className="block text-[11px] uppercase tracking-wider text-slate-400">Baseline Estimate:</span>
              <span className="font-bold">{estInterruptionMs} ms</span>
            </div>
          </div>
          <span className="mt-1 block text-[10px] text-indigo-900/70 dark:text-indigo-300/70">
            {interruptionMs != null
              ? 'Elapsed blackout window during epoch fence and target resume.'
              : 'Stopwatch triggers during single-lease fencing handover.'}
          </span>
        </div>
      </div>
    </div>
  );
}

