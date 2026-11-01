import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  apiFetchApps,
  apiOpenVSCodeProject,
  apiStartMigration,
  apiStartWorkload,
  apiStopWorkload,
  type AppTemplate,
} from '../api.ts';
import { useTeleport } from '../store/useTeleport.ts';
import type { WorkloadItem } from '../store/types.ts';
import { formatMb } from '../utils/formatters.ts';

export function WorkloadsPage() {
  const { state, addWorkload } = useTeleport();
  const navigate = useNavigate();
  const [isStartOpen, setIsStartOpen] = useState(false);
  const [manifestPath, setManifestPath] = useState('tests/fixtures/counter_job');
  const [apps, setApps] = useState<AppTemplate[]>([]);
  const [projectPath, setProjectPath] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!state.agentReachable) return;
    apiFetchApps().then(setApps).catch(() => setApps([]));
  }, [state.agentReachable]);

  async function startApp(app: AppTemplate) {
    setBusy(app.id);
    setActionMessage(null);
    const res =
      app.id === 'vscode'
        ? await apiOpenVSCodeProject(projectPath)
        : await apiStartWorkload(app.manifestPath ?? '').then((r) => ({ ...r, manifest: undefined }));
    setBusy(null);
    if (!res.ok) {
      setActionMessage(`Could not start ${app.title}: ${res.error ?? 'unknown error'}`);
      return;
    }
    if ('manifest' in res && res.manifest) addWorkload({ manifest: res.manifest, status: 'RUNNING' });
    setActionMessage(`${app.title} is running on this device. Use "Migrate" to move it.`);
  }

  async function migrateTo(wl: WorkloadItem, targetId: string, targetName: string) {
    setIsTargetPickerOpen(false);
    setActionMessage(`Starting the migration of ${wl.manifest.name} to ${targetName}...`);
    try {
      await apiStartMigration(wl.manifest.id, targetId, 'user_command');
      navigate('/migration'); // the steps update live there
    } catch (err: unknown) {
      setActionMessage(`Migration not started: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  const [selectedWorkload, setSelectedWorkload] = useState<WorkloadItem | null>(null);
  const [isTargetPickerOpen, setIsTargetPickerOpen] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  async function handleStartWorkload(e: React.FormEvent) {
    e.preventDefault();
    if (!manifestPath.trim()) return;

    try {
      if (state.mockFeederActive) {
        setActionMessage(`Workload started from "${manifestPath}" in simulated runtime.`);
        setIsStartOpen(false);
        return;
      }

      const res = await apiStartWorkload(manifestPath);
      if (res.ok) {
        setActionMessage(`Workload started successfully (ID: ${res.workloadId ?? 'new'}).`);
        setIsStartOpen(false);
      } else {
        setActionMessage(`Error starting workload: ${res.error ?? 'Unknown error'}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setActionMessage(`Failed to contact agent: ${msg}`);
    }
  }

  function handleOpenMigrate(wl: WorkloadItem) {
    setSelectedWorkload(wl);
    setIsTargetPickerOpen(true);
  }

  const peers = Object.values(state.devices).filter((d) => d.id !== state.thisDeviceId);

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
            Workload Registry & Feasibility
          </h1>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Registered stateful workloads with declarative checkpoints and remote fallback capabilities
          </p>
        </div>

        <button
          onClick={() => setIsStartOpen(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-indigo-500 transition-all active:scale-95"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>Start Workload</span>
        </button>
      </div>

      {actionMessage && (
        <div className="flex items-center justify-between rounded-lg bg-indigo-50 px-4 py-3 text-xs font-medium text-indigo-900 dark:bg-indigo-950/60 dark:text-indigo-200">
          <span>{actionMessage}</span>
          <button onClick={() => setActionMessage(null)} className="text-indigo-500 hover:text-indigo-700">
            Dismiss
          </button>
        </div>
      )}

      {/* Ready-made apps: one click, no manifest path */}
      {state.agentReachable && apps.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2" data-testid="app-gallery">
          {apps.map((app) => (
            <div
              key={app.id}
              data-testid={`app-${app.id}`}
              className="rounded-xl border border-slate-200 bg-white/90 p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900/80"
            >
              <h2 className="text-base font-bold text-slate-900 dark:text-white">{app.title}</h2>
              <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">{app.description}</p>
              {app.needs === 'projectPath' && (
                <input
                  type="text"
                  value={projectPath}
                  onChange={(e) => setProjectPath(e.target.value)}
                  placeholder="Project folder on this device, e.g. C:\Users\me\projects\demo"
                  className="mt-3 w-full rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-900 outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
              )}
              {!app.available && app.detail && <p className="mt-2 text-xs text-rose-600">{app.detail}</p>}
              <button
                type="button"
                disabled={!app.available || busy !== null || (app.needs === 'projectPath' && !projectPath.trim())}
                onClick={() => void startApp(app)}
                className="mt-3 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === app.id ? 'Starting...' : app.id === 'vscode' ? 'Open in VS Code' : 'Start'}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Workload Cards List */}
      <div className="space-y-4">
        {state.workloads.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center dark:border-slate-800">
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">No active workloads registered</p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Click &quot;Start Workload&quot; to launch a workload from a manifest path.
            </p>
          </div>
        ) : (
          state.workloads.map((wl) => {
            const m = wl.manifest;
            const authority = wl.authority ?? state.authority;

            return (
              <div
                key={m.id}
                data-testid={`workload-card-${m.id}`}
                className="rounded-xl border border-slate-200 bg-white/90 p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900/80 backdrop-blur-sm"
              >
                {/* Header */}
                <div className="flex flex-col justify-between gap-2 border-b border-slate-100 pb-4 dark:border-slate-800 sm:flex-row sm:items-center">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-slate-900 dark:text-white">{m.name}</h2>
                      <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300">
                        {wl.status}
                      </span>
                      {authority && (
                        <span className="rounded bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300">
                          AUTHORITY: {authority.state} (Epoch {authority.epoch})
                        </span>
                      )}
                    </div>
                    <p className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">
                      ID: {m.id} · Command: <code className="text-slate-800 dark:text-slate-200">{m.command}</code>
                    </p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    {wl.status === 'RUNNING' && (
                      <button
                        onClick={() =>
                          void apiStopWorkload(m.id)
                            .then(() => setActionMessage(`${m.name} stopped.`))
                            .catch((err: unknown) => setActionMessage(`Could not stop: ${err instanceof Error ? err.message : String(err)}`))
                        }
                        className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                      >
                        Stop
                      </button>
                    )}
                    <button
                      onClick={() => handleOpenMigrate(wl)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-indigo-500 transition-all"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                      </svg>
                      <span>Migrate</span>
                    </button>
                  </div>
                </div>

                {/* Manifest Specs Grid */}
                <div className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                  <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
                    <span className="text-slate-400 dark:text-slate-500">Runtime Requirement</span>
                    <p className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
                      {m.runtime.name} &gt;= {m.runtime.minVersion}
                    </p>
                  </div>

                  <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
                    <span className="text-slate-400 dark:text-slate-500">Target Architecture</span>
                    <p className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
                      {m.arch.join(', ')}
                    </p>
                  </div>

                  <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
                    <span className="text-slate-400 dark:text-slate-500">Min Resources</span>
                    <p className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
                      {formatMb(m.minRamMb)} RAM · {m.minCpuCores} Cores
                    </p>
                  </div>

                  <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
                    <span className="text-slate-400 dark:text-slate-500">Remote Fallback</span>
                    <p className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
                      {m.remoteCapable ? 'Supported (Zero-install)' : 'Unsupported'}
                    </p>
                  </div>
                </div>

                {/* Checkpoint Definitions Strip */}
                <div className="mt-4">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    Checkpoints Defined ({m.checkpoints.length} stages)
                  </span>
                  <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                    {m.checkpoints.map((chk, idx) => (
                      <div
                        key={chk.id}
                        className="rounded-lg border border-slate-200 bg-slate-50/60 p-2 text-center text-xs dark:border-slate-800 dark:bg-slate-800/30"
                      >
                        <span className="font-mono text-[10px] text-indigo-600 dark:text-indigo-400">
                          #{idx + 1}
                        </span>
                        <p className="mt-0.5 font-semibold text-slate-800 dark:text-slate-200 truncate" title={chk.name}>
                          {chk.name}
                        </p>
                        <p className="mt-0.5 font-mono text-[10px] text-slate-400 dark:text-slate-500 truncate" title={chk.paths.join(', ')}>
                          {chk.paths[0]}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Start Workload Modal */}
      {isStartOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">Start Workload by Manifest</h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Provide the relative or absolute path to the JSON manifest.
            </p>

            <form onSubmit={handleStartWorkload} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Manifest Path
                </label>
                <input
                  type="text"
                  value={manifestPath}
                  onChange={(e) => setManifestPath(e.target.value)}
                  placeholder="examples/migratable_ml_trainer/manifest.json"
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-slate-50 px-3.5 py-2 font-mono text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsStartOpen(false)}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-500"
                >
                  Launch Process
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Migrate Target Picker Modal */}
      {isTargetPickerOpen && selectedWorkload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">
              Select Target for &quot;{selectedWorkload.manifest.name}&quot;
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              The Feasibility Engine will evaluate CPU architecture, dependencies and link quality before handover.
            </p>

            <div className="mt-4 space-y-2">
              {peers.length === 0 ? (
                <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
                  No peer devices paired. Pair a device in the top bar first.
                </div>
              ) : (
                peers.map((peer) => (
                  <div
                    key={peer.id}
                    className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-800 dark:bg-slate-800/50"
                  >
                    <div>
                      <span className="font-semibold text-slate-900 dark:text-white">{peer.name}</span>
                      <p className="text-[11px] text-slate-500 dark:text-slate-400">
                        {peer.os} · {peer.arch} · {formatMb(peer.ramMb)} RAM
                      </p>
                    </div>
                    <button
                      onClick={() => void migrateTo(selectedWorkload, peer.id, peer.name)}
                      className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
                    >
                      Evaluate & Migrate
                    </button>
                  </div>
                ))
              )}
            </div>

            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setIsTargetPickerOpen(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

