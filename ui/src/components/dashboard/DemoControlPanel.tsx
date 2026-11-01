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

  const slider = (label: string, value: number, unit: string, min: number, max: number, set: (n: number) => void) => (
    <label className="block">
      <span className="flex items-baseline justify-between text-xs text-muted">
        {label}
        <span className="font-mono text-ink">
          {value}
          {unit}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => set(Number(e.target.value))}
        className="mt-1.5 h-1 w-full cursor-pointer accent-[var(--tp-ink)]"
      />
    </label>
  );

  return (
    <div data-testid="demo-control-panel" className="rounded-2xl border border-dashed border-warn/50 bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="tp-chip border-warn/40 bg-warn-soft text-warn">SIMULATED</span>
          <span className="tp-label uppercase">DEMO FAULT INJECTOR & STATS OVERRIDE</span>
          {statusMsg && <span className="text-xs text-ok">{statusMsg}</span>}
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="target-device-select" className="text-xs text-muted">
            Device
          </label>
          <select
            id="target-device-select"
            value={targetDevice}
            onChange={(e) => setTargetDevice(e.target.value)}
            className="rounded-lg border border-line-strong bg-surface px-2 py-1 text-xs text-ink"
          >
            {Object.keys(state.devices).length > 0 ? (
              Object.values(state.devices).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))
            ) : (
              <>
                <option value="device-a">Device A (MacBook Pro)</option>
                <option value="device-b">Device B (Workstation)</option>
              </>
            )}
          </select>
          <button type="button" onClick={() => setCollapsed(!collapsed)} className="tp-btn">
            {collapsed ? 'Show controls' : 'Hide'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-[auto_1fr]">
          <div className="flex flex-wrap content-start gap-2 lg:w-56">
            <button type="button" data-testid="btn-drain-battery" onClick={handleDrainBattery} className="tp-btn">
              Drain battery
            </button>
            <button type="button" data-testid="btn-cpu-spike" onClick={handleCpuSpike} className="tp-btn">
              CPU spike
            </button>
            <button type="button" data-testid="btn-drop-wifi" onClick={handleDropWifi} className="tp-btn">
              Drop wifi
            </button>
            <button type="button" data-testid="btn-reset-telemetry" onClick={handleReset} className="tp-btn">
              Reset
            </button>
          </div>
          <div className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-3">
            <div className="space-y-2">
              {slider('Battery', batteryPct, '%', 0, 100, setBatteryPct)}
              <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
                <input type="checkbox" checked={charging} onChange={(e) => setCharging(e.target.checked)} />
                Charging
              </label>
            </div>
            <div className="space-y-3">
              {slider('CPU', cpuPct, '%', 0, 100, setCpuPct)}
              {slider('Memory', memPct, '%', 0, 100, setMemPct)}
            </div>
            <div className="space-y-3">
              {slider('Link round trip', latencyMs, ' ms', 1, 500, setLatencyMs)}
              {slider('Packet loss', lossPct, '%', 0, 50, setLossPct)}
            </div>
            <div className="sm:col-span-3 flex justify-end">
              <button type="button" onClick={handleApplyCustom} className="tp-btn-primary">
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
