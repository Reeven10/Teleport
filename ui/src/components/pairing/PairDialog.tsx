import { useState } from 'react';
import type { DeviceInfo } from '@contract';
import { apiPairDevice } from '../../api.ts';
import { useTeleport } from '../../store/useTeleport.ts';
import { formatArch, formatOs } from '../../utils/formatters.ts';

interface PairDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export function PairDialog({ isOpen, onClose }: PairDialogProps) {
  const { state, addPairedDevice, selectPeer } = useTeleport();
  const [address, setAddress] = useState('192.168.1.102:8765');
  const [pin, setPin] = useState('749218');
  const [localPin] = useState('381904'); // Local PIN for the peer to enter
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  async function handlePair(e: React.FormEvent) {
    e.preventDefault();
    if (!address.trim() || !pin.trim()) return;

    setIsSubmitting(true);
    setStatusMessage(null);

    try {
      if (state.mockFeederActive) {
        // Mock pairing behavior
        const mockNewDevice: DeviceInfo = {
          id: `dev-${Date.now().toString(36).slice(-4)}`,
          name: `Peer Node (${address.split(':')[0]})`,
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
        setStatusMessage({ type: 'success', text: `Successfully paired with ${mockNewDevice.name}!` });
        setIsSubmitting(false);
        return;
      }

      const res = await apiPairDevice(address, pin);
      if (res.ok && res.device) {
        addPairedDevice(res.device);
        selectPeer(res.device.id);
        setStatusMessage({ type: 'success', text: `Paired successfully with ${res.device.name}!` });
      } else {
        setStatusMessage({ type: 'error', text: res.error ?? 'Pairing failed. Verify PIN and address.' });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatusMessage({ type: 'error', text: `Connection error: ${msg}` });
    } finally {
      setIsSubmitting(false);
    }
  }

  const pairedList = Object.values(state.devices);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3 dark:border-slate-800">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">Pair New Device</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Establish an encrypted Ed25519 identity exchange with a peer agent
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Pairing Form */}
        <form onSubmit={handlePair} className="mt-4 space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Target Agent Address (IP:Port or Host)
            </label>
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="e.g. 192.168.1.102:8765 or http://127.0.0.1:8766"
              className="mt-1 w-full rounded-lg border border-slate-300 bg-slate-50 px-3.5 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Remote One-Time PIN
              </label>
              <input
                type="text"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                placeholder="e.g. 749218"
                className="mt-1 w-full rounded-lg border border-slate-300 bg-slate-50 px-3.5 py-2 font-mono text-sm tracking-widest text-slate-900 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                This Device PIN
              </label>
              <div className="mt-1 flex h-[38px] items-center justify-between rounded-lg border border-dashed border-indigo-300 bg-indigo-50/60 px-3 font-mono text-sm font-bold tracking-widest text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-300">
                <span>{localPin}</span>
                <span className="text-[10px] uppercase text-indigo-500 font-sans">Ready</span>
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
              className="rounded-lg border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Close
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-500 disabled:opacity-50"
            >
              {isSubmitting ? 'Pairing...' : 'Pair & Connect'}
            </button>
          </div>
        </form>

        {/* List of Already Paired Devices */}
        <div className="mt-6 border-t border-slate-100 pt-4 dark:border-slate-800">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
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
                      ? 'border-indigo-500/60 bg-indigo-50/50 dark:border-indigo-700/60 dark:bg-indigo-950/30'
                      : 'border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-800/40'
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-900 dark:text-white">{dev.name}</span>
                      {isSelf && (
                        <span className="rounded bg-indigo-100 px-1.5 text-[10px] font-bold text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300">
                          THIS DEVICE
                        </span>
                      )}
                      {isSelected && !isSelf && (
                        <span className="rounded bg-emerald-100 px-1.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">
                          ACTIVE PEER
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                      {formatOs(dev.os)} · {formatArch(dev.arch)} · {dev.cpuCores} cores
                    </p>
                  </div>

                  {!isSelf && (
                    <button
                      onClick={() => selectPeer(dev.id)}
                      className={`rounded px-2.5 py-1 text-xs font-semibold ${
                        isSelected
                          ? 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200'
                          : 'bg-indigo-600 text-white hover:bg-indigo-500'
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
