import { useEffect, useState } from 'react';
import { apiFetchPairInfo } from '../../api.ts';
import { useTeleport } from '../../store/useTeleport.ts';
import { PairDialog } from '../pairing/PairDialog.tsx';
import { Icon, LiveDot } from '../ui/Icon.tsx';

export function TopBar() {
  const { state } = useTeleport();
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
  const link = state.link;
  const peerOnline = state.peerDeviceId ? (state.stats[state.peerDeviceId]?.online ?? false) : false;

  return (
    <>
      <header className="sticky top-0 z-40 flex h-14 w-full items-center justify-between gap-4 border-b border-line bg-canvas/85 px-6 backdrop-blur-md md:px-10">
        <div className="flex min-w-0 items-center gap-3 text-[13px]">
          <span className="flex items-center gap-2 truncate font-medium text-ink">
            <Icon name="laptop" className="h-4 w-4 text-faint" />
            {thisDevice?.name ?? 'This device'}
          </span>

          <span className="hidden items-center gap-2 sm:flex" title={link ? `${link.link}, ${link.rttMs} ms round trip` : 'not linked'}>
            <svg width="72" height="8" viewBox="0 0 72 8" aria-hidden="true" className={peerDevice ? 'text-line-strong' : 'text-line'}>
              <line
                x1="2"
                y1="4"
                x2="70"
                y2="4"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeDasharray="2 4"
                style={peerOnline ? { animation: 'tp-dash 1.2s linear infinite' } : undefined}
              />
              <circle cx="2" cy="4" r="2" className="fill-ink" />
              <circle cx="70" cy="4" r="2" className={peerOnline ? 'fill-accent' : 'fill-line-strong'} />
            </svg>
            {link && peerDevice && (
              <span className="font-mono text-[11px] text-faint">
                {link.link === 'cable' ? 'cable' : 'wifi'} · {Math.round(link.rttMs)} ms
              </span>
            )}
          </span>

          <span className={`truncate ${peerDevice ? 'font-medium text-ink' : 'text-faint'}`}>
            {peerDevice ? peerDevice.name : 'no peer yet'}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          {state.isSimulated && (
            <span data-testid="badge-simulated" className="tp-chip border-warn/40 bg-warn-soft text-warn">
              <LiveDot tone="warn" live={false} />
              SIMULATED
            </span>
          )}

          {pin && (
            <span
              data-testid="topbar-pin"
              title="Enter this PIN on the other device to pair with this one"
              className="hidden items-center gap-2 rounded-lg border border-line px-2.5 py-1 text-[11px] text-muted lg:flex"
            >
              Pairing PIN
              <span className="font-mono text-[13px] font-medium tracking-[0.2em] text-ink">{pin}</span>
            </span>
          )}

          <button type="button" onClick={() => setIsPairOpen(true)} className="tp-btn-primary">
            <Icon name="plus" className="h-3.5 w-3.5" />
            <span>Pair Device</span>
          </button>
        </div>
      </header>

      <PairDialog isOpen={isPairOpen} onClose={() => setIsPairOpen(false)} />
    </>
  );
}
