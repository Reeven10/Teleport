import { useState } from 'react';
import { apiStatsOverride } from '../../api.ts';
import { useTeleport } from '../../store/useTeleport.ts';

export function DemoControlPanel() {
  const { state, dispatch } = useTeleport();

  // If not simulated or mock feeder not active and no ?demo parameter, don't show
  const isDemo =
    state.isSimulated ||
    state.mockFeederActive ||
    (typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('demo'));

  const [collapsed, setCollapsed] = useState(false);
  const [targetDevice, setTargetDevice] = useState<string>(
    state.thisDeviceId || Object.keys(state.devices)[0] || 'device-a',
  );

  const [batteryPct, setBatteryPct] = useState<number>(12);
  const [charging, setCharging] = useState<boolean>(false);
  const [cpuPct, setCpuPct] = useState<number>(95);
  const [memPct, setMemPct] = useState<number>(85);
  const [latencyMs, setLatencyMs] = useState<number>(180);
  const [lossPct, setLossPct] = useState<number>(15);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  if (!isDemo) return null;

  const showStatus = (msg: string) => {
    setStatusMsg(msg);
    setTimeout(() => setStatusMsg(null), 3000);
  };

  const applyStats = async (
    devId: string,
    stats: {
      battery?: { pct: number; charging: boolean } | null;
      cpuPct?: number;
      memPct?: number;
      online?: boolean;
    } | null,
  ) => {
    // 1. Try agent API if reachable
    if (state.agentReachable) {
      try {
        await apiStatsOverride(devId, stats);
      } catch {
        // Fallback gracefully
      }
    }

    // 2. Also dispatch store event so UI reflects changes immediately
    const existing = state.stats[devId];
    if (stats === null) {
      // Reset
      dispatch({
        type: 'BUS_EVENT',
        payload: {
          t: 'stats.update',
          stats: {
            deviceId: devId,
            ts: Date.now(),
            cpuPct: 24,
            memPct: 42,
            memFreeMb: 8192,
            diskFreeMb: 120000,
            battery: { pct: 85, charging: true },
            online: true,
            simulated: true,
          },
        },
      });
      // Reset link quality
      dispatch({
        type: 'BUS_EVENT',
        payload: {
          t: 'link.update',
          link: {
            peerId: state.peerDeviceId || 'device-b',
            link: 'cable',
            rttMs: 1.2,
            mbps: 1000,
            lossPct: 0.0,
            ts: Date.now(),
          },
        },
      });
      showStatus(`Reset telemetry overrides for ${devId}`);
      return;
    }

    const updatedBattery =
      stats.battery !== undefined
        ? stats.battery
        : existing?.battery ?? { pct: batteryPct, charging };

    dispatch({
      type: 'BUS_EVENT',
      payload: {
        t: 'stats.update',
        stats: {
          deviceId: devId,
          ts: Date.now(),
          cpuPct: stats.cpuPct ?? existing?.cpuPct ?? cpuPct,
          memPct: stats.memPct ?? existing?.memPct ?? memPct,
          memFreeMb: existing?.memFreeMb ?? 4096,
          diskFreeMb: existing?.diskFreeMb ?? 100000,
          battery: updatedBattery,
          online: stats.online ?? existing?.online ?? true,
          simulated: true,
        },
      },
    });
  };

  // Quick Action Handlers
  const handleDrainBattery = async () => {
    setBatteryPct(12);
    setCharging(false);
    await applyStats(targetDevice, {
      battery: { pct: 12, charging: false },
    });
    showStatus(`Drained battery to 12% (Discharging) on ${targetDevice}`);
  };

  const handleCpuSpike = async () => {
    setCpuPct(96);
    await applyStats(targetDevice, {
      cpuPct: 96,
    });
    showStatus(`Injected 96% CPU spike on ${targetDevice}`);
  };

  const handleDropWifi = async () => {
    setLatencyMs(180);
    setLossPct(15);
    // Fault inject link
    dispatch({
      type: 'BUS_EVENT',
      payload: {
        t: 'link.update',
        link: {
          peerId: state.peerDeviceId || 'device-b',
          link: 'wifi',
          rttMs: 180,
          mbps: 12,
          lossPct: 15.0,
          ts: Date.now(),
        },
      },
    });
    showStatus(`Dropped link to high-latency / lossy WiFi on ${targetDevice}`);
  };

  const handleReset = async () => {
    setBatteryPct(85);
    setCharging(true);
    setCpuPct(24);
    setMemPct(42);
    setLatencyMs(2);
    setLossPct(0);
    await applyStats(targetDevice, null);
  };

  const handleApplyCustom = async () => {
    await applyStats(targetDevice, {
      battery: { pct: batteryPct, charging },
      cpuPct,
      memPct,
    });
    dispatch({
      type: 'BUS_EVENT',
      payload: {
        t: 'link.update',
        link: {
          peerId: state.peerDeviceId || 'device-b',
          link: latencyMs > 50 ? 'wifi' : 'cable',
          rttMs: latencyMs,
          mbps: latencyMs > 50 ? 54 : 1000,
          lossPct,
          ts: Date.now(),
        },
      },
    });
    showStatus(`Applied custom overrides to ${targetDevice}`);
  };

  return (
    <div
      data-testid="demo-control-panel"
      className="overflow-hidden rounded-2xl border-2 border-dashed border-amber-500/80 bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-purple-500/10 p-5 shadow-md backdrop-blur-xs dark:border-amber-400/80 dark:bg-amber-950/20"
    >
      {/* Panel Top Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500 px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-slate-950 shadow-xs">
            <span className="h-2 w-2 animate-ping rounded-full bg-white opacity-80" />
            SIMULATED
          </span>
          <span className="text-sm font-black tracking-wide text-amber-900 dark:text-amber-200">
            DEMO FAULT INJECTOR & STATS OVERRIDE
          </span>
          {statusMsg && (
            <span className="rounded-md bg-emerald-500/20 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
              {statusMsg}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Target device picker */}
          <div className="flex items-center gap-1.5 text-xs">
            <label htmlFor="target-device-select" className="font-semibold text-slate-700 dark:text-slate-300">
              Target:
            </label>
            <select
              id="target-device-select"
              value={targetDevice}
              onChange={(e) => setTargetDevice(e.target.value)}
              className="rounded-lg border border-amber-300 bg-white px-2 py-1 font-mono text-xs font-semibold text-slate-900 dark:border-amber-700 dark:bg-slate-900 dark:text-amber-200"
            >
              {Object.keys(state.devices).length > 0 ? (
                Object.values(state.devices).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} ({d.id})
                  </option>
                ))
              ) : (
                <>
                  <option value="device-a">Device A (MacBook Pro)</option>
                  <option value="device-b">Device B (Workstation)</option>
                </>
              )}
            </select>
          </div>

          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="rounded-lg border border-amber-300/80 bg-white/80 px-2.5 py-1 text-xs font-bold text-amber-900 transition hover:bg-white dark:border-amber-800 dark:bg-slate-900/80 dark:text-amber-200"
          >
            {collapsed ? 'Expand Controls ▼' : 'Collapse ▲'}
          </button>
        </div>
      </div>

      {/* Collapsible Content */}
      {!collapsed && (
        <div className="mt-4 space-y-4">
          {/* Action Buttons Row */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <button
              type="button"
              data-testid="btn-drain-battery"
              onClick={handleDrainBattery}
              className="flex items-center justify-center gap-2 rounded-xl border border-amber-400 bg-amber-500 px-3 py-2 text-xs font-bold text-slate-950 shadow-xs transition hover:bg-amber-400 active:scale-95"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
              Drain battery
            </button>

            <button
              type="button"
              data-testid="btn-cpu-spike"
              onClick={handleCpuSpike}
              className="flex items-center justify-center gap-2 rounded-xl border border-orange-400 bg-orange-500 px-3 py-2 text-xs font-bold text-slate-950 shadow-xs transition hover:bg-orange-400 active:scale-95"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              CPU spike
            </button>

            <button
              type="button"
              data-testid="btn-drop-wifi"
              onClick={handleDropWifi}
              className="flex items-center justify-center gap-2 rounded-xl border border-rose-400 bg-rose-500 px-3 py-2 text-xs font-bold text-white shadow-xs transition hover:bg-rose-400 active:scale-95"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-2.83m-1.414 5.658a9 9 0 01-2.121-4.243m16.97-4.243a8.955 8.955 0 00-2.828-2.828" />
              </svg>
              Drop wifi
            </button>

            <button
              type="button"
              data-testid="btn-reset-telemetry"
              onClick={handleReset}
              className="flex items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800 shadow-xs transition hover:bg-slate-100 active:scale-95 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Reset
            </button>
          </div>

          {/* Sliders Grid for Custom Manual Tuning */}
          <div className="grid grid-cols-1 gap-4 rounded-xl border border-amber-300/40 bg-white/70 p-4 sm:grid-cols-3 dark:border-slate-800 dark:bg-slate-900/60">
            {/* Battery Slider + Charging toggle */}
            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
                <span>Battery Level</span>
                <span className="font-mono font-bold text-amber-700 dark:text-amber-300">{batteryPct}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={batteryPct}
                onChange={(e) => setBatteryPct(Number(e.target.value))}
                className="mt-1 h-2 w-full accent-amber-500"
              />
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
                <input
                  type="checkbox"
                  checked={charging}
                  onChange={(e) => setCharging(e.target.checked)}
                  className="rounded text-amber-600 focus:ring-amber-500"
                />
                <span>AC Charging Connected</span>
              </label>
            </div>

            {/* CPU & Memory Sliders */}
            <div className="space-y-2">
              <div>
                <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
                  <span>CPU Usage</span>
                  <span className="font-mono font-bold text-orange-600 dark:text-orange-400">{cpuPct}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={cpuPct}
                  onChange={(e) => setCpuPct(Number(e.target.value))}
                  className="mt-1 h-2 w-full accent-orange-500"
                />
              </div>

              <div>
                <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
                  <span>Memory Usage</span>
                  <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400">{memPct}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={memPct}
                  onChange={(e) => setMemPct(Number(e.target.value))}
                  className="mt-1 h-2 w-full accent-indigo-500"
                />
              </div>
            </div>

            {/* Link Fault Injection (Latency & Loss) */}
            <div className="space-y-2">
              <div>
                <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
                  <span>Link RTT Latency</span>
                  <span className="font-mono font-bold text-rose-600 dark:text-rose-400">{latencyMs} ms</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={500}
                  value={latencyMs}
                  onChange={(e) => setLatencyMs(Number(e.target.value))}
                  className="mt-1 h-2 w-full accent-rose-500"
                />
              </div>

              <div>
                <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
                  <span>Packet Loss</span>
                  <span className="font-mono font-bold text-rose-600 dark:text-rose-400">{lossPct}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={50}
                  value={lossPct}
                  onChange={(e) => setLossPct(Number(e.target.value))}
                  className="mt-1 h-2 w-full accent-rose-500"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              onClick={handleApplyCustom}
              className="rounded-xl bg-slate-900 px-4 py-1.5 text-xs font-bold text-white shadow-xs transition hover:bg-slate-800 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
            >
              Apply Custom Overrides
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
