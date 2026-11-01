import { useEffect, useRef, useState } from 'react';
import { apiConsentRemote, apiFetchRemoteSessions, apiStopRemote } from '../../api.ts';
import type { RemoteSession } from '@contract';
import { useTeleport } from '../../store/useTeleport.ts';

/** On the host: asks before another device may view and control this screen, on whatever page is open.
 *  Also shows a bar with Stop while a peer is viewing. */
export function RemoteConsentPrompt() {
  const { state } = useTeleport();
  const [sessions, setSessions] = useState<RemoteSession[]>([]);
  const answered = useRef<Set<string>>(new Set());
  const [, rerender] = useState(0);

  useEffect(() => {
    if (!state.agentReachable || state.mockFeederActive) return;
    let alive = true;
    const load = () =>
      apiFetchRemoteSessions()
        .then((list) => alive && setSessions(list))
        .catch(() => {});
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [state.agentReachable, state.mockFeederActive, state.remoteSession]);

  const me = state.thisDeviceId;
  const pending = sessions.find((s) => s.hostId === me && !s.consent && !answered.current.has(s.id));
  const viewing = sessions.filter((s) => s.hostId === me && s.consent);
  const nameOf = (id: string) => state.devices[id]?.name ?? id;

  const answer = async (s: RemoteSession, allow: boolean) => {
    answered.current.add(s.id);
    rerender((n) => n + 1);
    await apiConsentRemote(s.id, allow).catch(() => {});
    if (!allow) await apiStopRemote(s.id).catch(() => {});
    setSessions(await apiFetchRemoteSessions().catch(() => sessions));
  };

  const stopAll = async () => {
    await Promise.all(viewing.map((s) => apiStopRemote(s.id).catch(() => {})));
    setSessions(await apiFetchRemoteSessions().catch(() => []));
  };

  return (
    <>
      {viewing.length > 0 && (
        <div
          data-testid="host-viewing-banner"
          className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-rose-400 bg-rose-50 px-4 py-2 text-rose-900 shadow-lg dark:border-rose-800 dark:bg-rose-950/90 dark:text-rose-200"
        >
          <span className="relative flex h-3 w-3">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-rose-500" />
          </span>
          <span className="text-xs font-bold">
            {viewing.map((s) => nameOf(s.viewerId)).join(', ')} can see and control this screen
          </span>
          <button
            type="button"
            data-testid="btn-host-stop-remote"
            onClick={stopAll}
            className="rounded-lg bg-rose-600 px-3 py-1 text-xs font-bold text-white hover:bg-rose-700"
          >
            Stop sharing
          </button>
        </div>
      )}

      {pending && (
        <div
          data-testid="consent-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4"
        >
          <div className="w-full max-w-md rounded-2xl border border-line bg-surface p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-ink">Remote Control Permission Request</h3>
            <p className="mt-2 text-sm text-muted">
              <span className="font-bold text-ink">{nameOf(pending.viewerId)}</span> wants to
              see this screen and use its mouse and keyboard, to work with{' '}
              <span className="font-mono font-bold">{pending.workloadId}</span>.
            </p>
            <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
              Allow only if you started this. You can stop it at any time with Stop sharing.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                data-testid="btn-consent-deny"
                onClick={() => answer(pending, false)}
                className="tp-btn"
              >
                Deny
              </button>
              <button
                type="button"
                data-testid="btn-consent-allow"
                onClick={() => answer(pending, true)}
                className="tp-btn-primary"
              >
                Allow
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
