import { useEffect, useState } from 'react';
import type { DeviceInfo } from '@contract';
import { apiFetchDiscovery, apiFetchPairInfo, apiPairDevice, type NearbyDevice } from '../../api.ts';
import { useTeleport } from '../../store/useTeleport.ts';
import { formatArch, formatOs } from '../../utils/formatters.ts';

interface PairDialogProps {
  isOpen: boolean;
  onClose: () => void;
  initialAddress?: string;
}

export function PairDialog({ isOpen, onClose, initialAddress }: PairDialogProps) {
  const { state, addPairedDevice, selectPeer } = useTeleport();
  const [address, setAddress] = useState(initialAddress || '');
  const [pin, setPin] = useState('');
  const [localPin, setLocalPin] = useState<string>('');
  const [nearby, setNearby] = useState<NearbyDevice[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Live mode: this device's real PIN (the agent shows it only to its own dashboard) and the
  // Teleport devices heard on the local network, refreshed every 2 s while the dialog is open.
  useEffect(() => {
    if (!isOpen) return;
    if (!state.agentReachable) {
      setLocalPin('381904'); // simulation only
      return;
    }
    let stop = false;
    apiFetchPairInfo()
      .then((info) => !stop && setLocalPin(info.pin ?? ''))
      .catch(() => !stop && setLocalPin(''));
    const refresh = () =>
      apiFetchDiscovery()
        .then((list) => !stop && setNearby(list))
        .catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [isOpen, state.agentReachable]);

  if (!isOpen) return null;

  async function handlePair(e: React.FormEvent) {
    e.preventDefault();
    if (!address.trim() || !pin.trim()) return;

    setIsSubmitting(true);
    setStatusMessage(null);

    try {
      // If agent is reachable, always use real backend API
      if (state.agentReachable) {
        const res = await apiPairDevice(address, pin);
        if (res.ok && res.device) {
          addPairedDevice(res.device);
          selectPeer(res.device.id);
          setStatusMessage({ type: 'success', text: `Paired successfully with ${res.device.name}!` });
        } else {
          setStatusMessage({ type: 'error', text: res.error ?? 'Pairing failed: peer agent rejected PIN/address.' });
        }
        setIsSubmitting(false);
        return;
      }

      // Offline / standalone mock feeder mode: require exact PIN validation
      if (state.mockFeederActive) {
        if (pin.trim() !== '749218') {
          setStatusMessage({ type: 'error', text: 'Pairing rejected: Invalid PIN for peer device (expected 749218 in simulation).' });
          setIsSubmitting(false);
          return;
        }

        const mockNewDevice: DeviceInfo = {
          id: `dev-${Date.now().toString(36).slice(-4)}`,
          name: `Peer Node [SIMULATED] (${address.split(':')[0]})`,
          os: 'linux',
          arch: 'x86_64',
          cpuCores: 8,
          ramMb: 16384,
          gpu: null,
          diskFreeMb: 256000,
          runtimes: { python: '3.11.9' },
          libs: ['torch', 'fastapi'],
          addrs: [{ addr: address, link: 'cable' }],
          agentVersion: '0.1.0',
          simulated: true,
        };
        addPairedDevice(mockNewDevice);
        selectPeer(mockNewDevice.id);
        setStatusMessage({ type: 'success', text: `Simulated pairing validated with ${mockNewDevice.name}.` });
        setIsSubmitting(false);
        return;
      }

      // If neither agent reachable nor mock feeder:
      setStatusMessage({ type: 'error', text: 'Agent is unreachable. Check connection on :8765.' });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatusMessage({ type: 'error', text: `Connection error: ${msg}` });
    } finally {
      setIsSubmitting(false);
    }
  }

  const pairedList = Object.values(state.devices);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
      <div className="w-full max-w-xl rounded-2xl border border-line bg-surface p-6 shadow-2xl">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <div>
            <h2 className="text-lg font-bold text-ink">Pair New Device</h2>
            <p className="text-xs text-muted">
              Establish an encrypted Ed25519 identity exchange with a peer agent
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-faint hover:bg-raised hover:text-slate-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Nearby Teleport devices on this network (LAN discovery) */}
        {state.agentReachable && (
          <div className="mt-4" data-testid="nearby-devices">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted">
              Nearby devices
            </p>
            {nearby.length === 0 ? (
              <p className="mt-1 text-xs text-muted">
                Looking for Teleport on this network... Start Teleport on the other laptop (same wifi or cable),
                or type its address below.
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {nearby.map((d) => (
                  <li
                    key={d.deviceId}
                    className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm ${
                      address === d.addr
                        ? 'border-ink/40 bg-raised'
                        : 'border-line'
                    }`}
                  >
                    <span>
                      <span className="font-semibold text-ink">{d.name}</span>
                      <span className="ml-2 font-mono text-xs text-muted">{d.addr}</span>
                    </span>
                    {d.paired ? (
                      <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">Paired</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setAddress(d.addr)}
                        className="tp-btn-primary"
                      >
                        Select
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Pairing Form */}
        <form onSubmit={handlePair} className="mt-4 space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-muted">
              Target Agent Address (IP:Port or Host)
            </label>
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="e.g. 192.168.1.102:8765 or http://127.0.0.1:8766"
              className="mt-1 w-full rounded-lg border border-line-strong bg-raised px-3.5 py-2 text-sm text-ink outline-none focus:border-ink/40 focus:ring-1 focus:ring-ink/20"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-muted">
                Remote One-Time PIN
              </label>
              <input
                type="text"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                placeholder="PIN shown on the other device"
                className="mt-1 w-full rounded-lg border border-line-strong bg-raised px-3.5 py-2 font-mono text-sm tracking-widest text-ink outline-none focus:border-ink/40 focus:ring-1 focus:ring-ink/20"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-muted">
                This Device PIN
              </label>
              <div className="mt-1 flex h-[38px] items-center justify-between rounded-lg border border-dashed border-line-strong bg-raised px-3 font-mono text-sm font-medium tracking-[0.25em] text-ink">
                <span data-testid="local-pin">{localPin || '------'}</span>
                <span className="font-sans text-[10.5px] tracking-normal text-faint">tell the other laptop</span>
              </div>
            </div>
          </div>

          {statusMessage && (
            <div
              className={`rounded-lg p-3 text-xs font-medium ${
                statusMessage.type === 'success'
                  ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300'
                  : 'bg-rose-50 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300'
              }`}
            >
              {statusMessage.text}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="tp-btn"
            >
              Close
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="tp-btn-primary"
            >
              {isSubmitting ? 'Pairing...' : 'Pair & Connect'}
            </button>
          </div>
        </form>

        {/* List of Already Paired Devices */}
        <div className="mt-6 border-t border-line pt-4">
          <h3 className="tp-label">
            Paired Devices ({pairedList.length})
          </h3>

          <div className="mt-2.5 max-h-48 space-y-2 overflow-y-auto">
            {pairedList.map((dev) => {
              const isSelected = state.peerDeviceId === dev.id;
              const isSelf = state.thisDeviceId === dev.id;

              return (
                <div
                  key={dev.id}
                  className={`flex items-center justify-between rounded-lg border p-2.5 text-xs ${
                    isSelected
                      ? 'border-ink/30 bg-raised'
                      : 'border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-800/40'
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-ink">{dev.name}</span>
                      {isSelf && (
                        <span className="tp-chip py-0 text-[10px]">
                          THIS DEVICE
                        </span>
                      )}
                      {isSelected && !isSelf && (
                        <span className="rounded bg-emerald-100 px-1.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">
                          ACTIVE PEER
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11px] text-muted">
                      {formatOs(dev.os)} · {formatArch(dev.arch)} · {dev.cpuCores} cores
                    </p>
                  </div>

                  {!isSelf && (
                    <button
                      onClick={() => selectPeer(dev.id)}
                      className={`rounded px-2.5 py-1 text-xs font-semibold ${
                        isSelected
                          ? 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200'
                          : 'bg-ink text-canvas hover:opacity-85'
                      }`}
                    >
                      {isSelected ? 'Active' : 'Select'}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
