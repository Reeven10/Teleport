import { useEffect, useState } from 'react';
import { apiGetSettings, apiPutSettings, type SettingsPrefs } from '../api.ts';
import { useTeleport } from '../store/useTeleport.ts';

export function SettingsPage() {
  const { state, toggleTheme, toggleMockFeeder } = useTeleport();

  // Settings form state
  const [mode, setMode] = useState<'recommend' | 'auto'>('recommend');
  const [batteryLowPct, setBatteryLowPct] = useState<number>(20);
  const [cpuHighPct, setCpuHighPct] = useState<number>(90);
  const [memHighPct, setMemHighPct] = useState<number>(90);
  const [predictionWindowSec, setPredictionWindowSec] = useState<number>(60);
  const [preferredLink, setPreferredLink] = useState<'auto' | 'cable' | 'wifi'>('auto');
  const [checkpointChunkKb, setCheckpointChunkKb] = useState<number>(1024);
  const [remoteConsent, setRemoteConsent] = useState<'prompt' | 'auto_allow' | 'deny_all'>('prompt');

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Fetch settings from agent on mount
  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      if (state.agentReachable) {
        setLoading(true);
        try {
          const s = await apiGetSettings();
          if (!cancelled && s) {
            if (s.mode) setMode(s.mode);
            if (s.batteryLowPct !== undefined) setBatteryLowPct(s.batteryLowPct);
            if (s.cpuHighPct !== undefined) setCpuHighPct(s.cpuHighPct);
            if (s.memHighPct !== undefined) setMemHighPct(s.memHighPct);
            if (s.predictionWindowSec !== undefined) setPredictionWindowSec(s.predictionWindowSec);
            if (s.preferredLink) setPreferredLink(s.preferredLink);
            if (s.checkpointChunkKb !== undefined) setCheckpointChunkKb(s.checkpointChunkKb);
            if (s.remoteConsent) setRemoteConsent(s.remoteConsent);
          }
        } catch {
          // Keep defaults
        } finally {
          if (!cancelled) setLoading(false);
        }
      }
    }

    loadSettings();

    return () => {
      cancelled = true;
    };
  }, [state.agentReachable]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSaveSuccess(false);

    // Client-side validation
    if (isNaN(batteryLowPct) || batteryLowPct < 5 || batteryLowPct > 50) {
      setErrorMessage('Battery Low threshold must be a number between 5% and 50%.');
      return;
    }

    if (isNaN(cpuHighPct) || cpuHighPct < 50 || cpuHighPct > 99) {
      setErrorMessage('CPU High pressure threshold must be between 50% and 99%.');
      return;
    }

    if (isNaN(memHighPct) || memHighPct < 50 || memHighPct > 99) {
      setErrorMessage('Memory High pressure threshold must be between 50% and 99%.');
      return;
    }

    if (isNaN(predictionWindowSec) || predictionWindowSec < 10 || predictionWindowSec > 300) {
      setErrorMessage('Prediction window must be between 10 and 300 seconds.');
      return;
    }

    if (isNaN(checkpointChunkKb) || checkpointChunkKb < 64 || checkpointChunkKb > 16384) {
      setErrorMessage('Checkpoint chunk size must be between 64 KB and 16,384 KB.');
      return;
    }

    const payload: Partial<SettingsPrefs> = {
      mode,
      batteryLowPct: Number(batteryLowPct),
      cpuHighPct: Number(cpuHighPct),
      memHighPct: Number(memHighPct),
      predictionWindowSec: Number(predictionWindowSec),
      preferredLink,
      checkpointChunkKb: Number(checkpointChunkKb),
      remoteConsent,
    };

    setSaving(true);
    try {
      if (state.agentReachable) {
        await apiPutSettings(payload);
      }
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 5000);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to save settings to agent');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
          Teleport Agent Settings & Policies
        </h1>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Orchestration decision modes, pressure triggers, transport link policies, and remote access consent
        </p>
      </div>

      {/* Notifications */}
      {saveSuccess && (
        <div
          data-testid="settings-save-success"
          className="flex items-center gap-2 rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-xs font-bold text-emerald-800 shadow-xs dark:border-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-200 text-emerald-800 dark:bg-emerald-800 dark:text-emerald-100">
            ✓
          </span>
          <span>Settings saved successfully to agent operational store.</span>
        </div>
      )}

      {errorMessage && (
        <div
          data-testid="settings-error-banner"
          className="flex items-center gap-2 rounded-xl border border-rose-300 bg-rose-50 px-4 py-3 text-xs font-semibold text-rose-800 shadow-xs dark:border-rose-900/60 dark:bg-rose-950/60 dark:text-rose-300"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-200 text-rose-800 dark:bg-rose-900 dark:text-rose-100">
            !
          </span>
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Main Settings Form */}
      <form onSubmit={handleSave} className="space-y-5">
        {/* Card 1: Orchestration Mode */}
        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            1. Orchestration Execution Mode
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Choose whether migrations require manual human approval or execute autonomously upon rule breaches
          </p>

          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all ${
                mode === 'recommend'
                  ? 'border-indigo-500 bg-indigo-50/40 ring-2 ring-indigo-500/20 dark:border-indigo-500 dark:bg-indigo-950/30'
                  : 'border-slate-200 bg-slate-50/30 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/30'
              }`}
            >
              <input
                type="radio"
                name="mode"
                value="recommend"
                checked={mode === 'recommend'}
                onChange={() => setMode('recommend')}
                className="mt-0.5 text-indigo-600 focus:ring-indigo-500"
              />
              <div>
                <span className="text-xs font-bold text-slate-900 dark:text-white">
                  Recommend Mode (Human in the Loop)
                </span>
                <p className="mt-1 text-[11px] text-slate-500">
                  Orchestrator generates proactive decision recommendations on the dashboard with full rule evidence.
                  Authority moves only when the operator accepts.
                </p>
              </div>
            </label>

            <label
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all ${
                mode === 'auto'
                  ? 'border-indigo-500 bg-indigo-50/40 ring-2 ring-indigo-500/20 dark:border-indigo-500 dark:bg-indigo-950/30'
                  : 'border-slate-200 bg-slate-50/30 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/30'
              }`}
            >
              <input
                type="radio"
                name="mode"
                value="auto"
                data-testid="radio-mode-auto"
                checked={mode === 'auto'}
                onChange={() => setMode('auto')}
                className="mt-0.5 text-indigo-600 focus:ring-indigo-500"
              />
              <div>
                <span className="text-xs font-bold text-slate-900 dark:text-white">
                  Autonomous Cutover (Auto Mode)
                </span>
                <p className="mt-1 text-[11px] text-slate-500">
                  Orchestrator automatically initiates migration pipeline when pressure thresholds or battery limits
                  are breached. Reverts on checksum failure without downtime.
                </p>
              </div>
            </label>
          </div>
        </div>

        {/* Card 2: Pressure Triggers & Prediction Window */}
        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            2. Telemetry Triggers & Pressure Thresholds
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Define boundary thresholds that trigger feasibility checks and proactive cutover recommendations
          </p>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                Low Battery Limit (%)
              </label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="number"
                  data-testid="input-battery-threshold"
                  value={batteryLowPct}
                  onChange={(e) => setBatteryLowPct(parseFloat(e.target.value))}
                  min={5}
                  max={50}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-mono text-xs font-bold text-slate-900 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
                <span className="text-xs font-bold text-slate-400">%</span>
              </div>
              <p className="mt-1 text-[10px] text-slate-400">Default: 20% (Valid: 5 - 50%)</p>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                CPU Pressure Limit (%)
              </label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="number"
                  data-testid="input-cpu-threshold"
                  value={cpuHighPct}
                  onChange={(e) => setCpuHighPct(parseFloat(e.target.value))}
                  min={50}
                  max={99}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-mono text-xs font-bold text-slate-900 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
                <span className="text-xs font-bold text-slate-400">%</span>
              </div>
              <p className="mt-1 text-[10px] text-slate-400">Default: 90% (Valid: 50 - 99%)</p>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                Memory Pressure Limit (%)
              </label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="number"
                  data-testid="input-mem-threshold"
                  value={memHighPct}
                  onChange={(e) => setMemHighPct(parseFloat(e.target.value))}
                  min={50}
                  max={99}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-mono text-xs font-bold text-slate-900 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
                <span className="text-xs font-bold text-slate-400">%</span>
              </div>
              <p className="mt-1 text-[10px] text-slate-400">Default: 90% (Valid: 50 - 99%)</p>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                Prediction Window (Seconds)
              </label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="number"
                  data-testid="input-prediction-window"
                  value={predictionWindowSec}
                  onChange={(e) => setPredictionWindowSec(parseInt(e.target.value, 10))}
                  min={10}
                  max={300}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-mono text-xs font-bold text-slate-900 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
                <span className="text-xs font-bold text-slate-400">sec</span>
              </div>
              <p className="mt-1 text-[10px] text-slate-400">Linear trend extrapolation (10 - 300s)</p>
            </div>
          </div>
        </div>

        {/* Card 3: Transport Link & Checkpoint Chunking */}
        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            3. Peer Transport & State Serialization
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Network physical link preference and chunk fragmentation parameters
          </p>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                Preferred Peer Transport Link
              </label>
              <select
                data-testid="select-preferred-link"
                value={preferredLink}
                onChange={(e) => setPreferredLink(e.target.value as 'auto' | 'cable' | 'wifi')}
                className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-900 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              >
                <option value="auto">Automatic (Highest Throughput / Lowest RTT)</option>
                <option value="cable">Wired Cable Only (Ethernet/Thunderbolt direct)</option>
                <option value="wifi">Wireless Wi-Fi (802.11ax/ac link)</option>
              </select>
              <p className="mt-1 text-[10px] text-slate-400">
                Auto dynamically transitions state transfer if cable is unplugged.
              </p>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                Checkpoint Chunk Size (KB)
              </label>
              <input
                type="number"
                data-testid="input-chunk-size"
                value={checkpointChunkKb}
                onChange={(e) => setCheckpointChunkKb(parseInt(e.target.value, 10))}
                min={64}
                max={16384}
                step={64}
                className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 font-mono text-xs font-bold text-slate-900 shadow-2xs focus:border-blue-500 focus:outline-hidden dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
              <p className="mt-1 text-[10px] text-slate-400">
                Chunk buffer size for streaming SHA-256 validation (64 KB - 16 MB).
              </p>
            </div>
          </div>
        </div>

        {/* Card 4: Remote Access Consent Behavior */}
        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            4. Remote Access Consent Policy
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Authorization behavior when peer devices request screen viewing and input injection fallback
          </p>

          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label
              className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3.5 transition ${
                remoteConsent === 'prompt'
                  ? 'border-sky-500 bg-sky-50/40 ring-1 ring-sky-500/20 dark:border-sky-500 dark:bg-sky-950/30'
                  : 'border-slate-200 bg-slate-50/30 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/30'
              }`}
            >
              <input
                type="radio"
                name="remoteConsent"
                value="prompt"
                checked={remoteConsent === 'prompt'}
                onChange={() => setRemoteConsent('prompt')}
                className="mt-0.5 text-sky-600 focus:ring-sky-500"
              />
              <div>
                <span className="text-xs font-bold text-slate-900 dark:text-white">Prompt Every Time</span>
                <p className="mt-0.5 text-[10px] text-slate-500">Always show modal requiring explicit approval.</p>
              </div>
            </label>

            <label
              className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3.5 transition ${
                remoteConsent === 'auto_allow'
                  ? 'border-sky-500 bg-sky-50/40 ring-1 ring-sky-500/20 dark:border-sky-500 dark:bg-sky-950/30'
                  : 'border-slate-200 bg-slate-50/30 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/30'
              }`}
            >
              <input
                type="radio"
                name="remoteConsent"
                value="auto_allow"
                checked={remoteConsent === 'auto_allow'}
                onChange={() => setRemoteConsent('auto_allow')}
                className="mt-0.5 text-sky-600 focus:ring-sky-500"
              />
              <div>
                <span className="text-xs font-bold text-slate-900 dark:text-white">Auto-Allow Paired</span>
                <p className="mt-0.5 text-[10px] text-slate-500">Grant viewing immediately if peer was previously paired.</p>
              </div>
            </label>

            <label
              className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3.5 transition ${
                remoteConsent === 'deny_all'
                  ? 'border-sky-500 bg-sky-50/40 ring-1 ring-sky-500/20 dark:border-sky-500 dark:bg-sky-950/30'
                  : 'border-slate-200 bg-slate-50/30 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/30'
              }`}
            >
              <input
                type="radio"
                name="remoteConsent"
                value="deny_all"
                checked={remoteConsent === 'deny_all'}
                onChange={() => setRemoteConsent('deny_all')}
                className="mt-0.5 text-sky-600 focus:ring-sky-500"
              />
              <div>
                <span className="text-xs font-bold text-slate-900 dark:text-white">Deny All Requests</span>
                <p className="mt-0.5 text-[10px] text-slate-500">Reject all remote viewport and input injection requests.</p>
              </div>
            </label>
          </div>
        </div>

        {/* Save Bar */}
        <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/60">
          <span className="text-xs text-slate-500">
            {loading ? 'Fetching current agent configuration...' : 'Changes apply immediately to running agent daemon.'}
          </span>
          <button
            type="submit"
            data-testid="btn-save-settings"
            disabled={saving}
            className="flex items-center gap-2 rounded-xl bg-blue-600 px-6 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </form>

      {/* Developer & Simulation Feeder Controls */}
      <div className="space-y-4 pt-4 border-t border-slate-200 dark:border-slate-800">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Developer & Display Environment</h3>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Mock Feeder Toggle */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
            <h4 className="text-xs font-bold text-slate-900 dark:text-white">Mock BusEvent Feeder</h4>
            <p className="mt-1 text-[11px] text-slate-500">
              Generates realistic live stats, simulated battery drain, link quality oscillations, and migration scenarios.
            </p>
            <div className="mt-3 flex items-center justify-between">
              <span className="font-mono text-xs font-semibold text-slate-600 dark:text-slate-300">
                {state.mockFeederActive ? 'Status: ACTIVE' : 'Status: STOPPED'}
              </span>
              <button
                type="button"
                data-testid="btn-toggle-feeder"
                onClick={() => toggleMockFeeder()}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold text-white transition ${
                  state.mockFeederActive ? 'bg-amber-500 hover:bg-amber-600' : 'bg-slate-600 hover:bg-slate-700'
                }`}
              >
                {state.mockFeederActive ? 'Disable Feeder' : 'Enable Feeder'}
              </button>
            </div>
          </div>

          {/* Theme Selector */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
            <h4 className="text-xs font-bold text-slate-900 dark:text-white">Theme & Display Contrast</h4>
            <p className="mt-1 text-[11px] text-slate-500">
              Switch between Light and Dark control-room palettes with high-contrast color badges.
            </p>
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                Current: <strong className="uppercase">{state.theme}</strong>
              </span>
              <button
                type="button"
                data-testid="btn-toggle-theme"
                onClick={() => toggleTheme()}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              >
                Switch to {state.theme === 'dark' ? 'Light' : 'Dark'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
