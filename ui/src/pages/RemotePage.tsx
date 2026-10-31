import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useTeleport } from '../store/useTeleport.ts';
import {
  apiConsentRemote,
  apiStopRemote,
  apiGetRemoteToken,
} from '../api.ts';

export function RemotePage() {
  const { state, setSimulationScenario } = useTeleport();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Session & Connection state
  const [activeSessionId, setActiveSessionId] = useState<string>('session-demo-1');
  const [isStreaming, setIsStreaming] = useState<boolean>(true);
  const [controlsCaptured, setControlsCaptured] = useState<boolean>(false);
  const [fps, setFps] = useState<number>(18.4);
  const [latencyMs, setLatencyMs] = useState<number>(14);
  const [resolution, setResolution] = useState<{ w: number; h: number }>({ w: 1280, h: 720 });
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Host consent modal state
  const [showConsentModal, setShowConsentModal] = useState<boolean>(false);
  const [pendingConsentSession, setPendingConsentSession] = useState<{
    id: string;
    workloadId: string;
    viewerId: string;
  } | null>(null);

  // Check if this device is host with an active viewer session
  const isHostBeingViewed =
    Boolean(state.remoteSession &&
      state.remoteSession.consent &&
      state.remoteSession.hostId === state.thisDeviceId);

  // Real WebSocket ref
  const wsRef = useRef<WebSocket | null>(null);

  // If state has an active remote session, keep sessionId aligned
  useEffect(() => {
    if (state.remoteSession) {
      setActiveSessionId(state.remoteSession.id);
      if (!state.remoteSession.consent && state.remoteSession.hostId === state.thisDeviceId) {
        setPendingConsentSession({
          id: state.remoteSession.id,
          workloadId: state.remoteSession.workloadId,
          viewerId: state.remoteSession.viewerId,
        });
        setShowConsentModal(true);
      }
    }
  }, [state.remoteSession, state.thisDeviceId]);

  // Connect real WebSocket or start mock canvas render loop
  useEffect(() => {
    let animId: number;
    let cancelled = false;

    if (state.agentReachable && activeSessionId) {
      // Connect to real backend
      (async () => {
        try {
          const { token } = await apiGetRemoteToken(activeSessionId);
          if (cancelled) return;

          const loc = window.location;
          const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
          const wsUrl = `${wsProto}//${loc.host}/ws/remote/${activeSessionId}?token=${encodeURIComponent(token)}`;

          const ws = new WebSocket(wsUrl);
          ws.binaryType = 'arraybuffer';
          wsRef.current = ws;

          let frameCount = 0;
          let lastFpsTime = performance.now();

          ws.onopen = () => {
            if (cancelled) return;
            setIsStreaming(true);
            setErrorMessage(null);
          };

          ws.onmessage = async (event) => {
            if (cancelled || !(event.data instanceof ArrayBuffer)) return;
            const buf = event.data;
            if (buf.byteLength < 20) return;

            const view = new DataView(buf);
            const w = view.getUint32(0);
            const h = view.getUint32(4);
            const ts = view.getFloat64(12);

            const nowSec = Date.now() / 1000;
            const lat = Math.max(1, Math.round((nowSec - ts) * 1000));
            setLatencyMs(lat);
            setResolution({ w, h });

            frameCount++;
            const now = performance.now();
            if (now - lastFpsTime >= 1000) {
              setFps(parseFloat(((frameCount * 1000) / (now - lastFpsTime)).toFixed(1)));
              frameCount = 0;
              lastFpsTime = now;
            }

            const jpegBytes = buf.slice(20);
            const blob = new Blob([jpegBytes], { type: 'image/jpeg' });
            const imgBitmap = await createImageBitmap(blob);

            const canvas = canvasRef.current;
            if (canvas) {
              if (canvas.width !== w || canvas.height !== h) {
                canvas.width = w;
                canvas.height = h;
              }
              const ctx = canvas.getContext('2d');
              ctx?.drawImage(imgBitmap, 0, 0);
            }
            imgBitmap.close();
          };

          ws.onerror = () => {
            setErrorMessage('WebSocket remote stream error');
          };

          ws.onclose = () => {
            setIsStreaming(false);
          };
        } catch {
          // If real stream fails, fallback to animated canvas
          startMockLoop();
        }
      })();
    } else {
      // Offline / Mock Feeder mode: canvas animation
      startMockLoop();
    }

    function startMockLoop() {
      let t = 0;
      let frameCount = 0;
      let lastFpsCheck = performance.now();

      const render = () => {
        if (cancelled) return;
        t += 0.04;
        const canvas = canvasRef.current;
        if (canvas) {
          const ctx = canvas.getContext('2d');
          if (ctx) {
            const w = canvas.width;
            const h = canvas.height;

            // Background
            ctx.fillStyle = '#0f172a';
            ctx.fillRect(0, 0, w, h);

            // Desktop Window Frame
            ctx.fillStyle = '#1e293b';
            ctx.fillRect(20, 20, w - 40, h - 40);

            // Window Header Bar
            ctx.fillStyle = '#334155';
            ctx.fillRect(20, 20, w - 40, 36);

            // Window controls
            ctx.fillStyle = '#ef4444';
            ctx.beginPath();
            ctx.arc(40, 38, 6, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#f59e0b';
            ctx.beginPath();
            ctx.arc(58, 38, 6, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#10b981';
            ctx.beginPath();
            ctx.arc(76, 38, 6, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#94a3b8';
            ctx.font = '12px monospace';
            ctx.fillText('teleport-workload-runner (PID 8412) · remote host: device-b', 100, 42);

            // Workload Simulation Content
            ctx.fillStyle = '#090d16';
            ctx.fillRect(40, 76, w - 80, h - 116);

            // Animated waveform / processing graphs
            ctx.strokeStyle = '#38bdf8';
            ctx.lineWidth = 2;
            ctx.beginPath();
            for (let x = 40; x < w - 40; x += 6) {
              const y = h / 2 + Math.sin((x * 0.02) + t) * 60 + Math.cos((x * 0.05) - t * 1.5) * 20;
              if (x === 40) ctx.moveTo(x, y);
              else ctx.lineTo(x, y);
            }
            ctx.stroke();

            // Terminal Logs on host screen
            ctx.fillStyle = '#22c55e';
            ctx.font = '13px monospace';
            ctx.fillText('> [TELEPORT] Workload running pinned on host (device-b: macOS Darwin aarch64)', 56, 110);
            ctx.fillText('> [TELEPORT] Zero-install fallback: low-latency screen capture active', 56, 134);
            ctx.fillText(`> [WORKLOAD] Chunk processing cycle #${Math.floor(t * 10)} OK`, 56, 158);
            ctx.fillText(`> [GPU] Metal Pipeline 0: 64ComputeTasks / frame @ ${(60 + Math.sin(t)*5).toFixed(1)} FPS`, 56, 182);

            // Animated Simulated Remote Cursor
            const cursorX = w / 2 + Math.sin(t * 0.8) * (w * 0.25);
            const cursorY = h / 2 + Math.cos(t * 0.6) * (h * 0.25);

            ctx.fillStyle = '#ffffff';
            ctx.strokeStyle = '#000000';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(cursorX, cursorY);
            ctx.lineTo(cursorX, cursorY + 16);
            ctx.lineTo(cursorX + 5, cursorY + 12);
            ctx.lineTo(cursorX + 11, cursorY + 15);
            ctx.lineTo(cursorX + 13, cursorY + 12);
            ctx.lineTo(cursorX + 7, cursorY + 9);
            ctx.lineTo(cursorX + 12, cursorY + 9);
            ctx.closePath();
            ctx.fill();
            ctx.stroke();
          }
        }

        frameCount++;
        const now = performance.now();
        if (now - lastFpsCheck >= 1000) {
          setFps(parseFloat(((frameCount * 1000) / (now - lastFpsCheck)).toFixed(1)));
          setLatencyMs(Math.floor(12 + Math.random() * 5));
          frameCount = 0;
          lastFpsCheck = now;
        }

        animId = requestAnimationFrame(render);
      };

      render();
    }

    return () => {
      cancelled = true;
      if (animId) cancelAnimationFrame(animId);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [state.agentReachable, activeSessionId]);

  // Input coordinate normalization & WebSocket dispatcher
  const sendInput = useCallback((payload: Record<string, unknown>) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!controlsCaptured) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    sendInput({ type: 'mouse_move', x, y });
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    setControlsCaptured(true);
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const button = e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left';
    sendInput({ type: 'mouse_down', button, x, y });
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const button = e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left';
    sendInput({ type: 'mouse_up', button, x, y });
  };

  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    if (!controlsCaptured) return;
    e.preventDefault();
    sendInput({ type: 'wheel', dx: e.deltaX, dy: e.deltaY });
  };

  // Keyboard capture with Esc to release
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

  // Actions
  const handleDisconnect = async () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsStreaming(false);
    setControlsCaptured(false);
    try {
      if (state.agentReachable && activeSessionId) {
        await apiStopRemote(activeSessionId);
      }
    } catch {
      // Ignore cleanup error
    }
  };

  const handleHostStopRemote = async () => {
    const sid = state.remoteSession?.id || activeSessionId;
    if (state.agentReachable && sid) {
      await apiStopRemote(sid).catch(() => {});
    }
    handleDisconnect();
  };

  const handleConsent = async (allow: boolean) => {
    const sid = pendingConsentSession?.id || activeSessionId;
    setShowConsentModal(false);
    try {
      if (state.agentReachable && sid) {
        await apiConsentRemote(sid, allow);
      }
      if (allow) {
        setIsStreaming(true);
      }
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : 'Consent response failed');
    }
  };

  const linkBadgeColor =
    state.link?.link === 'cable'
      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300'
      : 'bg-blue-100 text-blue-800 dark:bg-blue-950/70 dark:text-blue-300';

  return (
    <div className="space-y-4">
      {/* (1) Host Persistent Warning Banner (when peer is viewing host) */}
      {isHostBeingViewed && (
        <div
          data-testid="host-viewing-banner"
          className="flex items-center justify-between rounded-xl border border-rose-400 bg-rose-50 px-4 py-3 text-rose-900 shadow-sm dark:border-rose-800 dark:bg-rose-950/60 dark:text-rose-200"
        >
          <div className="flex items-center gap-3">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-rose-500" />
            </span>
            <span className="text-xs font-bold uppercase tracking-wide">
              Active Remote View: Peer is viewing and controlling this host desktop
            </span>
            <span className="font-mono text-xs opacity-75">
              (Session: {state.remoteSession?.id})
            </span>
          </div>

          <button
            type="button"
            data-testid="btn-host-stop-remote"
            onClick={handleHostStopRemote}
            className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-bold text-white shadow hover:bg-rose-700 dark:bg-rose-500 dark:hover:bg-rose-600"
          >
            Stop Remote Access
          </button>
        </div>
      )}

      {/* Header & Controls Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
              Remote Access Viewport
            </h1>
            <span className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider text-sky-700 dark:bg-sky-950/60 dark:text-sky-400">
              Low-Latency Screen & Input Forwarding
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Zero-install adaptive frame streaming (mss + Pillow) with remote input capture (pynput)
          </p>
        </div>

        {/* Top actions */}
        <div className="flex flex-wrap items-center gap-2">
          {controlsCaptured ? (
            <button
              type="button"
              data-testid="btn-release-controls"
              onClick={() => setControlsCaptured(false)}
              className="flex items-center gap-1.5 rounded-xl bg-amber-500 px-3.5 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-amber-600"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Release Controls (Esc)</span>
            </button>
          ) : (
            <button
              type="button"
              data-testid="btn-capture-controls"
              onClick={() => setControlsCaptured(true)}
              className="flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122" />
              </svg>
              <span>Capture Inputs</span>
            </button>
          )}

          <button
            type="button"
            data-testid="btn-disconnect-remote"
            onClick={handleDisconnect}
            className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-rose-700 dark:bg-rose-500 dark:hover:bg-rose-600"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            <span>Disconnect</span>
          </button>
        </div>
      </div>

      {/* Scenario helpers for demonstration & review */}
      {state.mockFeederActive && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-2 text-xs dark:border-slate-800 dark:bg-slate-900/40">
          <span className="text-[11px] font-bold uppercase text-slate-500">Test Scenarios:</span>
          <button
            type="button"
            data-testid="btn-simulate-remote-scene"
            onClick={() => setSimulationScenario('remote_access')}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 font-semibold text-sky-600 shadow-sm hover:bg-sky-50 dark:border-slate-700 dark:bg-slate-800 dark:text-sky-400"
          >
            Simulate Remote Decision Stream
          </button>
          <button
            type="button"
            data-testid="btn-trigger-consent-modal"
            onClick={() => {
              setPendingConsentSession({
                id: 'sess-peer-984',
                workloadId: 'workload-1',
                viewerId: state.peerDeviceId || 'device-b',
              });
              setShowConsentModal(true);
            }}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 font-semibold text-purple-600 shadow-sm hover:bg-purple-50 dark:border-slate-700 dark:bg-slate-800 dark:text-purple-400"
          >
            Simulate Host Consent Modal
          </button>
        </div>
      )}

      {errorMessage && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
          {errorMessage}
        </div>
      )}

      {/* Status Bar */}
      <div
        data-testid="remote-status-bar"
        className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs shadow-sm dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex flex-wrap items-center gap-5">
          <div className="flex items-center gap-1.5 font-medium">
            <span className="text-slate-400">Stream Status:</span>
            <span
              className={`font-semibold ${
                isStreaming ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'
              }`}
            >
              {isStreaming ? 'STREAMING ACTIVE' : 'STOPPED'}
            </span>
          </div>

          <div className="flex items-center gap-1.5 font-mono">
            <span className="text-slate-400">FPS:</span>
            <span data-testid="remote-fps" className="font-bold text-sky-600 dark:text-sky-400">
              {fps.toFixed(1)}
            </span>
          </div>

          <div className="flex items-center gap-1.5 font-mono">
            <span className="text-slate-400">Latency:</span>
            <span data-testid="remote-latency" className="font-bold text-emerald-600 dark:text-emerald-400">
              {latencyMs} ms
            </span>
          </div>

          <div className="flex items-center gap-1.5 font-mono">
            <span className="text-slate-400">Resolution:</span>
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              {resolution.w} × {resolution.h}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">Transport:</span>
            <span
              data-testid="remote-link-type"
              className={`rounded-md px-2 py-0.5 text-[11px] font-bold uppercase ${linkBadgeColor}`}
            >
              {state.link?.link || 'wifi'} ({state.link?.mbps || 120} Mbps)
            </span>
          </div>

          {controlsCaptured && (
            <span
              data-testid="controls-captured-indicator"
              className="rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-bold text-amber-800 dark:bg-amber-950/70 dark:text-amber-300"
            >
              ⌨️ Input Active (Esc to release)
            </span>
          )}
        </div>
      </div>

      {/* Main Screen Viewport Canvas */}
      <div className="relative flex flex-col items-center justify-center overflow-hidden rounded-2xl border border-slate-300 bg-slate-950 p-2 shadow-xl dark:border-slate-800">
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
          className={`max-h-[70vh] w-full rounded-xl object-contain transition focus:outline-none ${
            controlsCaptured
              ? 'cursor-crosshair ring-2 ring-amber-400/80'
              : 'cursor-pointer hover:ring-1 hover:ring-blue-500/50'
          }`}
        />

        {!controlsCaptured && isStreaming && (
          <div
            onClick={() => setControlsCaptured(true)}
            className="absolute bottom-6 cursor-pointer rounded-full bg-slate-900/80 px-4 py-1.5 text-xs font-semibold text-slate-200 shadow-lg backdrop-blur-md transition hover:bg-slate-900"
          >
            Click viewport to capture mouse & keyboard controls
          </div>
        )}

        {!isStreaming && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950/80 backdrop-blur-sm">
            <h3 className="text-base font-bold text-slate-100">Remote Stream Disconnected</h3>
            <p className="mt-1 text-xs text-slate-400">
              The remote session was closed or waiting for host authorization.
            </p>
            <button
              type="button"
              onClick={() => setIsStreaming(true)}
              className="mt-4 rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow hover:bg-blue-700"
            >
              Reconnect Viewport
            </button>
          </div>
        )}
      </div>

      {/* (2) Host Consent Modal (when viewer requests access) */}
      {showConsentModal && (
        <div
          data-testid="consent-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-100 text-amber-600 dark:bg-amber-950/60 dark:text-amber-400">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>

            <h3 className="mt-4 text-lg font-bold text-slate-900 dark:text-white">
              Remote Control Permission Request
            </h3>
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">
              Remote device <span className="font-mono font-bold text-slate-900 dark:text-white">{pendingConsentSession?.viewerId || 'peer-device'}</span> is requesting interactive remote desktop access to control workload <span className="font-mono font-bold text-slate-900 dark:text-white">{pendingConsentSession?.workloadId || 'workload-1'}</span>.
            </p>

            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-[11px] text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
              Granting access allows the peer device to view your display and inject mouse and keyboard inputs via low-latency screen streaming.
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                data-testid="btn-consent-deny"
                onClick={() => handleConsent(false)}
                className="rounded-xl border border-slate-300 px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Deny Access
              </button>
              <button
                type="button"
                data-testid="btn-consent-allow"
                onClick={() => handleConsent(true)}
                className="rounded-xl bg-blue-600 px-5 py-2 text-xs font-bold text-white shadow hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600"
              >
                Allow Remote Control
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
