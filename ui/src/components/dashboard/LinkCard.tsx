import { memo } from 'react';
import type { LinkQuality } from '@contract';
import { formatMbps, formatMs, formatPercent } from '../../utils/formatters.ts';

interface LinkCardProps {
  link: LinkQuality | null;
  peerOnline: boolean;
}

export const LinkCard = memo(function LinkCard({ link, peerOnline }: LinkCardProps) {
  if (!peerOnline || !link) {
    return (
      <div className="flex h-full min-h-[300px] w-full flex-col items-center justify-center rounded-xl border border-dashed border-rose-200 bg-rose-50/40 p-6 text-center dark:border-rose-950/60 dark:bg-rose-950/10 lg:w-48">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-rose-100 text-rose-500 dark:bg-rose-900/40">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-2.83m-1.414 5.658a9 9 0 01-2.167-9.238m7.824 2.166a1 1 0 111.414 1.414" />
          </svg>
        </div>
        <p className="mt-2 text-xs font-bold uppercase tracking-wider text-rose-600 dark:text-rose-400">Link Inactive</p>
        <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">Peer node is currently offline</p>
      </div>
    );
  }

  const isCable = link.link === 'cable';
  const rttColor = link.rttMs < 15 ? 'text-emerald-500 dark:text-emerald-400' : link.rttMs < 50 ? 'text-amber-500 dark:text-amber-400' : 'text-rose-500 dark:text-rose-400';
  const lossColor = link.lossPct === 0 ? 'text-emerald-500 dark:text-emerald-400' : link.lossPct < 1.0 ? 'text-amber-500 dark:text-amber-400' : 'text-rose-500 dark:text-rose-400';

  return (
    <div className="flex flex-col items-center justify-between rounded-xl border border-slate-200 bg-white/95 p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900/90 lg:w-48">
      {/* Top Badge: Link Type */}
      <div className="flex flex-col items-center text-center">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          Peer Transport
        </span>
        <div className="mt-1.5 flex items-center gap-1.5">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${
              isCable
                ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'
                : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
            }`}
          >
            {isCable ? (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            ) : (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0" />
              </svg>
            )}
            {link.link.toUpperCase()}
          </span>
        </div>
      </div>

      {/* Visual Connection Wave / Arrow */}
      <div className="my-4 flex w-full flex-col items-center justify-center">
        <div className="flex items-center gap-1 text-slate-300 dark:text-slate-600">
          <div className="h-1.5 w-1.5 rounded-full bg-indigo-500 animate-ping" />
          <div className="h-0.5 w-8 bg-gradient-to-r from-indigo-500 to-emerald-500" />
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-ping" />
        </div>
        <span className="mt-1 text-[10px] font-mono text-slate-400 dark:text-slate-500">
          Peer Transport Link
        </span>
      </div>

      {/* Vitals: RTT, Bandwidth, Loss */}
      <div className="w-full space-y-3 divide-y divide-slate-100 text-center dark:divide-slate-800">
        <div className="pt-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500">Latency (RTT)</span>
          <p className={`font-mono text-base font-bold ${rttColor}`}>
            {formatMs(link.rttMs)}
          </p>
        </div>

        <div className="pt-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500">Throughput</span>
          <p className="font-mono text-base font-bold text-slate-800 dark:text-slate-100">
            {formatMbps(link.mbps)}
          </p>
        </div>

        <div className="pt-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500">Packet Loss</span>
          <p className={`font-mono text-base font-bold ${lossColor}`}>
            {formatPercent(link.lossPct, 1)}
          </p>
        </div>
      </div>

      <div className="mt-3 text-[10px] text-slate-400 dark:text-slate-500">
        Preferred: Cable
      </div>
    </div>
  );
});

