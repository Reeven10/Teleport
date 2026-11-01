import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  apiFetchRemoteHosts,
  apiRequestRemoteView,
  apiStopRemoteView,
  remoteViewUrl,
  type RemoteHost,
} from '../api.ts';
import { useTeleport } from '../store/useTeleport.ts';

const WHOLE_SCREEN = 'desktop';

interface View {
  hostId: string;
  hostName: string;
  sessionId: string;
}

/** View and control another paired device's screen. The host's own dashboard asks its user to allow
 *  it (RemoteConsentPrompt); frames and input travel through this agent (/ws/remote-view). */
export function RemotePage() {
  const { state, setSimulationScenario } = useTeleport();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const ended = useRef<Set<string>>(new Set()); // sessions not to reopen by themselves

  const queryScenario =
    typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('scenario') : null;
  const simulated = Boolean(queryScenario) || !state.agentReachable || state.mockFeederActive;

  const [hosts, setHosts] = useState<RemoteHost[]>([]);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [requested, setRequested] = useState<Record<string, string>>({}); // sessionId -> hostId
  const [view, setView] = useState<View | null>(
    simulated && queryScenario === 'remote_access'
      ? { hostId: 'simulated', hostName: 'Simulated host', sessionId: 'session-demo-1' }
      : null,
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const [controlsCaptured, setControlsCaptured] = useState(false);
  const [fps, setFps] = useState(0);
  const [resolution, setResolution] = useState({ w: 1280, h: 720 });
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showDemoConsent, setShowDemoConsent] = useState(false);

  // Paired devices, what runs there, and the sessions they offer to this device.
  useEffect(() => {
    if (simulated) return;
    let alive = true;
    const load = () =>
      apiFetchRemoteHosts()
        .then((list) => alive && setHosts(list))
        .catch(() => {});
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [simulated]);

  // Open the stream by itself once the host allowed a session: one this page requested, or one the host
  // offered (Teleport chose remote access instead of migrating).
  useEffect(() => {
    if (simulated || view) return;
    for (const h of hosts) {
      const s = h.sessions?.find((x) => x.consent && !ended.current.has(x.id));
      if (s) {
        setView({ hostId: h.id, hostName: h.name, sessionId: s.id });
        return;
      }
    }
  }, [hosts, simulated, view]);

  // Real stream: JPEG frames (20-byte header: width, height, ..., timestamp) from the host via this agent.
  useEffect(() => {
    if (!view || simulated) return;
    let cancelled = false;
    let frames = 0;
    let lastFps = performance.now();
    const ws = new WebSocket(remoteViewUrl(view.hostId, view.sessionId));
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;
    const keepalive = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
    }, 10000); // the host ends a session after 60 s without any viewer message

    ws.onopen = () => {
      if (cancelled) return;
      setIsStreaming(true);
      setErrorMessage(null);
    };
    ws.onmessage = async (event) => {
      if (cancelled || !(event.data instanceof ArrayBuffer) || event.data.byteLength < 20) return;
      const buf = event.data;
      const head = new DataView(buf);
      const w = head.getUint32(0);
      const h = head.getUint32(4);
      setResolution({ w, h });
      frames++;
      const now = performance.now();
      if (now - lastFps >= 1000) {
        setFps(Number(((frames * 1000) / (now - lastFps)).toFixed(1)));
        frames = 0;
        lastFps = now;
      }
      const bitmap = await createImageBitmap(new Blob([buf.slice(20)], { type: 'image/jpeg' }));
      const canvas = canvasRef.current;
      if (canvas) {
        if (canvas.width !== w || canvas.height !== h) {
          canvas.width = w;
          canvas.height = h;
        }
        canvas.getContext('2d')?.drawImage(bitmap, 0, 0);
      }
      bitmap.close();
    };
    ws.onclose = (event) => {
      ended.current.add(view.sessionId);
      if (cancelled) return;
      setIsStreaming(false);
      setControlsCaptured(false);
      setErrorMessage(`Remote view ended: ${event.reason || 'the connection closed'}.`);
      setView(null);
    };

    return () => {
      cancelled = true;
      window.clearInterval(keepalive);
      ws.close();
      wsRef.current = null;
      setIsStreaming(false);
    };
  }, [view, simulated]);

  // Simulated stream for the offline demo and tests: clearly labelled, never shown for a real session.
  useEffect(() => {
    if (!view || !simulated) return;
    let animId = 0;
    let t = 0;
    let frames = 0;
    let lastFps = performance.now();
    setIsStreaming(true);
    const render = () => {
      t += 0.04;
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');
      if (canvas && ctx) {
        const { width: w, height: h } = canvas;
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, w, h);
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let x = 40; x < w - 40; x += 6) {
          const y = h / 2 + Math.sin(x * 0.02 + t) * 60 + Math.cos(x * 0.05 - t * 1.5) * 20;
          if (x === 40) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 18px monospace';
        ctx.fillText('SIMULATED: no real host connected', 56, 80);
      }
      frames++;
      const now = performance.now();
      if (now - lastFps >= 1000) {
        setFps(Number(((frames * 1000) / (now - lastFps)).toFixed(1)));
        frames = 0;
        lastFps = now;
      }
      animId = requestAnimationFrame(render);
    };
    render();
    return () => {
      cancelAnimationFrame(animId);
      setIsStreaming(false);
    };
  }, [view, simulated]);

  const sendInput = useCallback((payload: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(payload));
  }, []);

  const point = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
  };
  const buttonOf = (e: React.MouseEvent) => (e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left');

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (controlsCaptured) sendInput({ type: 'mouse_move', ...point(e) });
  };
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    setControlsCaptured(true);
    sendInput({ type: 'mouse_down', button: buttonOf(e), ...point(e) });
  };
  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    sendInput({ type: 'mouse_up', button: buttonOf(e), ...point(e) });
  };
  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    if (controlsCaptured) sendInput({ type: 'wheel', dx: e.deltaX, dy: e.deltaY });
  };

  // Keyboard goes to the host while controls are captured; Esc gives it back to this laptop.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setControlsCaptured(false);
        return;
      }
      if (controlsCaptured) {
        e.preventDefault();
        sendInput({ type: 'key_down', key: e.key, code: e.code });
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (controlsCaptured) {
        e.preventDefault();
        sendInput({ type: 'key_up', key: e.key, code: e.code });
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [controlsCaptured, sendInput]);

  const requestView = async (host: RemoteHost) => {
    setBusy(host.id);
    setErrorMessage(null);
    try {
      const s = await apiRequestRemoteView(host.id, choice[host.id] || WHOLE_SCREEN);
      setRequested((r) => ({ ...r, [s.id]: host.id }));
      setHosts(await apiFetchRemoteHosts().catch(() => hosts));
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : 'Could not ask the other device');
    } finally {
      setBusy(null);
    }
  };

  const handleDisconnect = async () => {
    const current = view;
    if (current) ended.current.add(current.sessionId);
    wsRef.current?.close();
    wsRef.current = null;
    setView(null);
    setIsStreaming(false);
    setControlsCaptured(false);
    if (current && !simulated) await apiStopRemoteView(current.hostId, current.sessionId).catch(() => {});
  };

  const linkBadgeColor =
    state.link?.link === 'cable'
      ? 'border border-ok/40 text-ok'
      : 'border border-line text-muted';
  const waiting = hosts.flatMap((h) =>
    (h.sessions ?? []).filter((s) => !s.consent).map((s) => ({ host: h, session: s })),
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 border-b border-line pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="tp-label mb-1.5">Remote access</p>
          <div className="flex items-center gap-2">
            <h1 className="tp-title">See the other screen</h1>
            {simulated && (
              <span className="tp-chip border-warn/40 bg-warn-soft text-warn">
                Simulated
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-muted">
            See and control another paired laptop's screen. The workload keeps running there; the other laptop
            is asked to allow it first.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {controlsCaptured ? (
            <button
              type="button"
              data-testid="btn-release-controls"
              onClick={() => setControlsCaptured(false)}
              className="rounded-xl bg-amber-500 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-amber-600"
            >
              Release Controls (Esc)
            </button>
          ) : (
            <button
              type="button"
              data-testid="btn-capture-controls"
              onClick={() => setControlsCaptured(true)}
              disabled={!view}
              className="tp-btn"
            >
              Capture Inputs
            </button>
          )}
          <button
            type="button"
            data-testid="btn-disconnect-remote"
            onClick={handleDisconnect}
            disabled={!view}
            className="tp-btn"
          >
            Disconnect
          </button>
        </div>
      </div>

      {simulated && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-raised p-2 text-xs">
          <span className="tp-label">Test Scenarios:</span>
          <button
            type="button"
            data-testid="btn-simulate-remote-scene"
            onClick={() => setSimulationScenario('remote_access')}
            className="rounded-lg border border-line-strong bg-surface px-2.5 py-1 font-semibold text-sky-600 shadow-sm dark:text-sky-400"
          >
            Simulate Remote Decision Stream
          </button>
          <button
            type="button"
            data-testid="btn-trigger-consent-modal"
            onClick={() => setShowDemoConsent(true)}
            className="rounded-lg border border-line-strong bg-surface px-2.5 py-1 font-semibold text-purple-600 shadow-sm dark:text-purple-400"
          >
            Simulate Host Consent Modal
          </button>
        </div>
      )}

      {!simulated && !view && (
        <div data-testid="remote-hosts" className="rounded-2xl border border-line bg-surface p-4 shadow-sm">
          <h2 className="text-sm font-bold text-ink">View another device</h2>
          {hosts.length === 0 && (
            <p className="mt-2 text-xs text-muted">No paired device yet: pair one with Pair Device first.</p>
          )}
          <div className="mt-3 space-y-2">
            {hosts.map((h) => (
              <div
                key={h.id}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2"
              >
                <span className="min-w-32 text-sm font-semibold">{h.name}</span>
                {h.reachable ? (
                  <>
                    <select
                      value={choice[h.id] ?? WHOLE_SCREEN}
                      onChange={(e) => setChoice((c) => ({ ...c, [h.id]: e.target.value }))}
                      className="rounded-lg border border-line-strong bg-surface px-2 py-1 text-xs"
                    >
                      <option value={WHOLE_SCREEN}>Whole screen</option>
                      {(h.workloads ?? []).map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.name}
                          {w.running ? ' (running)' : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      data-testid={`btn-request-view-${h.id}`}
                      disabled={busy === h.id}
                      onClick={() => requestView(h)}
                      className="tp-btn-primary"
                    >
                      {busy === h.id ? 'Asking...' : 'Request access'}
                    </button>
                  </>
                ) : (
                  <span className="text-xs text-rose-600">Not reachable right now</span>
                )}
              </div>
            ))}
          </div>
          {waiting.map(({ host, session }) => (
            <p key={session.id} className="mt-3 text-xs font-semibold text-amber-700 dark:text-amber-400">
              Waiting for {host.name} to click Allow on its screen
              {requested[session.id] ? '' : ' (offered by Teleport instead of migrating)'}...
            </p>
          ))}
        </div>
      )}

      {errorMessage && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
          {errorMessage}
        </div>
      )}

      <div
        data-testid="remote-status-bar"
        className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 py-2.5 text-xs shadow-sm"
      >
        <div className="flex flex-wrap items-center gap-5">
          <span>
            <span className="text-faint">Stream: </span>
            <span className={`font-semibold ${isStreaming ? 'text-emerald-600' : 'text-slate-400'}`}>
              {isStreaming ? `LIVE from ${view?.hostName ?? 'host'}` : 'STOPPED'}
            </span>
          </span>
          <span className="font-mono">
            <span className="text-faint">FPS: </span>
            <span data-testid="remote-fps" className="font-bold text-sky-600">
              {fps.toFixed(1)}
            </span>
          </span>
          <span className="font-mono">
            <span className="text-faint">Link RTT: </span>
            <span data-testid="remote-latency" className="font-bold text-emerald-600">
              {state.link ? `${Math.round(state.link.rttMs)} ms` : 'n/a'}
            </span>
          </span>
          <span className="font-mono">
            <span className="text-faint">Resolution: </span>
            {resolution.w} × {resolution.h}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span data-testid="remote-link-type" className={`rounded-md px-2 py-0.5 text-[11px] font-bold uppercase ${linkBadgeColor}`}>
            {state.link ? `${state.link.link} (${Math.round(state.link.mbps)} Mbps)` : 'link n/a'}
          </span>
          {controlsCaptured && (
            <span
              data-testid="controls-captured-indicator"
              className="rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-bold text-amber-800 dark:bg-amber-950/70 dark:text-amber-300"
            >
              Input goes to the other laptop (Esc to release)
            </span>
          )}
        </div>
      </div>

      <div className="relative flex items-center justify-center overflow-hidden rounded-2xl border border-line-strong bg-slate-950 p-2 shadow-xl">
        <canvas
          ref={canvasRef}
          data-testid="remote-viewport-canvas"
          width={1280}
          height={720}
          onMouseMove={handleMouseMove}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onWheel={handleWheel}
          onContextMenu={(e) => e.preventDefault()}
          tabIndex={0}
          className={`max-h-[70vh] w-full rounded-xl object-contain focus:outline-none ${
            controlsCaptured ? 'cursor-crosshair ring-2 ring-amber-400/80' : 'cursor-pointer'
          }`}
        />
        {!isStreaming && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950/80 text-center">
            <h3 className="text-base font-bold text-slate-100">
              {view ? `Connecting to ${view.hostName}...` : 'No remote session'}
            </h3>
            <p className="mt-1 max-w-md text-xs text-faint">
              Pick a device above and click Request access. It opens here as soon as that laptop allows it.
            </p>
          </div>
        )}
      </div>

      {showDemoConsent && (
        <div data-testid="consent-modal" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4">
          <div className="w-full max-w-md rounded-2xl bg-surface p-6 shadow-2xl">
            <h3 className="text-lg font-bold">Remote Control Permission Request</h3>
            <p className="mt-2 text-xs text-muted">Simulated: this is what the host sees.</p>
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" data-testid="btn-consent-deny" onClick={() => setShowDemoConsent(false)} className="rounded-xl border px-4 py-2 text-xs font-bold">
                Deny
              </button>
              <button type="button" data-testid="btn-consent-allow" onClick={() => setShowDemoConsent(false)} className="tp-btn-primary">
                Allow
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
