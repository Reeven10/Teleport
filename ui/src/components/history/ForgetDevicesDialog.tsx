import { useState } from 'react';
import { useTeleport } from '../../store/useTeleport.ts';

interface ForgetDevicesDialogProps {
  onReset: () => Promise<{ devices: number; migrations: number }>;
}

/** "Start fresh": forget every paired device and clear the history. The history keeps recording. */
export function ForgetDevicesDialog({ onReset }: ForgetDevicesDialogProps) {
  const { state } = useTeleport();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onReset();
      window.location.reload(); // every page starts again from the agent's (now empty) view
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        data-testid="btn-forget-devices"
        disabled={!state.agentReachable || state.mockFeederActive}
        onClick={() => setOpen(true)}
        className="tp-btn"
      >
        Forget all devices
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div data-testid="forget-devices-dialog" className="w-full max-w-md rounded-2xl border border-line bg-canvas p-6 shadow-2xl">
            <p className="tp-label">Start fresh</p>
            <h2 className="mt-1 font-serif text-2xl text-ink">Forget all devices?</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
              <li>Every paired device, its trusted key and address are forgotten. To connect again it must pair with a PIN.</li>
              <li>The device, migration and decision history is cleared. New activity is recorded as before.</li>
              <li>Workloads running on this laptop keep running.</li>
            </ul>
            <p className="mt-3 text-xs text-faint">Do this on both laptops for a completely clean start.</p>
            {error && <p className="mt-3 text-sm text-bad">{error}</p>}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" className="tp-btn" onClick={() => setOpen(false)} disabled={busy}>
                Cancel
              </button>
              <button type="button" data-testid="confirm-forget-devices" className="tp-btn-primary" onClick={() => void confirm()} disabled={busy}>
                {busy ? 'Forgetting...' : 'Forget and start fresh'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
