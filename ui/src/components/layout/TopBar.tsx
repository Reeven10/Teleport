import { useEffect, useState } from 'react';
import { apiFetchPairInfo } from '../../api.ts';
import { useTeleport } from '../../store/useTeleport.ts';
import { PairDialog } from '../pairing/PairDialog.tsx';

export function TopBar() {
  const { state, toggleTheme, toggleMockFeeder } = useTeleport();
  const [isPairOpen, setIsPairOpen] = useState(false);
  const [pin, setPin] = useState<string>('');

  // This device's pairing PIN, always visible so the other laptop's user can read it off this screen.
  useEffect(() => {
    if (!state.agentReachable) return;
    let stop = false;
    const load = () =>
      apiFetchPairInfo()
        .then((info) => !stop && setPin(info.pin ?? ''))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 10000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [state.agentReachable]);

  const thisDevice = state.devices[state.thisDeviceId];
  const peerDevice = state.peerDeviceId ? state.devices[state.peerDeviceId] : null;

  const linkType = state.link?.link;
  const isCable = linkType === 'cable';

  return (
    <>
      <header className="sticky top-0 z-40 flex h-16 w-full items-center justify-between border-b border-slate-200 bg-white/95 px-6 shadow-xs backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/90">
        {/* Left: Brand + Device & Peer Identities */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-400 text-white shadow-sm">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 3v18" strokeDasharray="2 2" />
                <path d="M3 12h18" />
              </svg>
            </div>
            <div>
              <span className="text-base font-extrabold tracking-tight text-slate-900 dark:text-white">
                Teleport
              </span>
              <span className="ml-1.5 rounded bg-indigo-50 px-1.5 py-0.2 text-[10px] font-bold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                v0.1.0
              </span>
            </div>
          </div>

          <div className="hidden h-5 w-px bg-slate-200 dark:bg-slate-800 md:block" />

          {/* This Device & Peer Badges */}
          <div className="hidden items-center gap-3 sm:flex">
            <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs dark:border-slate-800 dark:bg-slate-800/60">
              <span className="font-semibold text-slate-500 dark:text-slate-400">Host:</span>
              <span className="font-bold text-slate-900 dark:text-white">
                {thisDevice?.name ?? 'Device A'}
              </span>
            </div>

            <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>

            <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs dark:border-slate-800 dark:bg-slate-800/60">
              <span className="font-semibold text-slate-500 dark:text-slate-400">Peer:</span>
              <span className="font-bold text-slate-900 dark:text-white">
                {peerDevice ? peerDevice.name : 'No Peer Selected'}
              </span>
            </div>
          </div>
        </div>

        {/* Right: Badges, Controls, Theme, Simulation */}
        <div className="flex items-center gap-3">
          {/* Link Type Badge */}
          {linkType ? (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${
                isCable
                  ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'
                  : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  isCable ? 'bg-indigo-500' : 'bg-emerald-500'
                } animate-pulse`}
              />
              {isCable ? 'CABLE' : 'WIFI'}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              NO LINK
            </span>
          )}

          {/* SIMULATED Badge */}
          {state.isSimulated && (
            <span
              data-testid="badge-simulated"
              className="inline-flex items-center gap-1.5 rounded-md bg-amber-400/20 px-2.5 py-1 text-xs font-extrabold text-amber-700 ring-1 ring-amber-400/40 dark:bg-amber-950/60 dark:text-amber-300 dark:ring-amber-500/50"
            >
              <span className="h-2 w-2 rounded-full bg-amber-500 animate-ping" />
              SIMULATED
            </span>
          )}

          {/* Mock Feeder Toggle Switch */}
          <button
            onClick={() => toggleMockFeeder()}
            title={state.mockFeederActive ? 'Mock Feeder is Active (click to disable)' : 'Mock Feeder is Inactive (click to enable)'}
            className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold transition-all ${
              state.mockFeederActive
                ? 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300'
                : 'border-slate-200 bg-slate-100 text-slate-600 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-400'
            }`}
          >
            <span>Feeder:</span>
            <span className="font-bold">{state.mockFeederActive ? 'MOCK' : 'LIVE'}</span>
          </button>

          {pin && (
            <div
              data-testid="topbar-pin"
              title="Enter this PIN on the other device to pair with this one"
              className="flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs text-indigo-800 dark:border-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-200"
            >
              <span>Pairing PIN</span>
              <span className="font-mono font-bold tracking-widest">{pin}</span>
            </div>
          )}

          {/* Pair Device Button */}
          <button
            onClick={() => setIsPairOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-indigo-500 transition-all active:scale-95"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            <span>Pair Device</span>
          </button>

          {/* Theme Switcher */}
          <button
            onClick={toggleTheme}
            aria-label="Toggle Theme"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            {state.theme === 'dark' ? (
              <svg className="h-4 w-4 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg className="h-4 w-4 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>
        </div>
      </header>

      {/* Pairing Dialog Modal */}
      <PairDialog isOpen={isPairOpen} onClose={() => setIsPairOpen(false)} />
    </>
  );
}
