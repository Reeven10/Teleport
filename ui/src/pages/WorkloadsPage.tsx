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
import { Icon, LiveDot, PageHeader } from '../components/ui/Icon.tsx';

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
      <PageHeader
        eyebrow="Workloads"
        title="What runs here"
        description="Start something on this laptop, then move it to the other one with its state."
        actions={
          <button type="button" onClick={() => setIsStartOpen(true)} className="tp-btn">
            <Icon name="plus" className="h-3.5 w-3.5" />
            <span>Start Workload</span>
          </button>
        }
      />

      {actionMessage && (
        <div className="flex items-center justify-between rounded-xl border border-line bg-raised px-4 py-2.5 text-sm text-ink">
          <span>{actionMessage}</span>
          <button type="button" onClick={() => setActionMessage(null)} className="text-xs text-muted hover:text-ink">
            Dismiss
          </button>
        </div>
      )}

      {state.agentReachable && apps.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2" data-testid="app-gallery">
          {apps.map((app) => (
            <div key={app.id} data-testid={`app-${app.id}`} className="tp-card flex flex-col p-5">
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-raised text-muted">
                  <Icon name={app.id === 'vscode' ? 'folder' : 'play'} className="h-4 w-4" />
                </span>
                <div>
                  <h2 className="text-[15px] font-medium text-ink">{app.title}</h2>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted">{app.description}</p>
                </div>
              </div>
              {app.needs === 'projectPath' && (
                <input
                  type="text"
                  value={projectPath}
                  onChange={(e) => setProjectPath(e.target.value)}
                  placeholder="C:\Users\me\projects\demo"
                  className="mt-4 w-full rounded-lg border border-line-strong bg-canvas px-3 py-2 font-mono text-xs text-ink outline-none placeholder:text-faint focus:border-ink/40"
                />
              )}
              {!app.available && app.detail && <p className="mt-2 text-xs text-bad">{app.detail}</p>}
              <div className="mt-4 flex justify-end">
                <button
                  type="button"
                  disabled={!app.available || busy !== null || (app.needs === 'projectPath' && !projectPath.trim())}
                  onClick={() => void startApp(app)}
                  className="tp-btn-primary"
                >
                  {busy === app.id ? 'Starting...' : app.id === 'vscode' ? 'Open in VS Code' : 'Start'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-4">
        {state.workloads.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-line-strong p-12 text-center">
            <p className="font-serif text-2xl text-ink">Nothing running yet</p>
            <p className="mt-1 text-sm text-muted">Open a VS Code project or start the counter demo above.</p>
          </div>
        ) : (
          state.workloads.map((wl) => {
            const m = wl.manifest;
            const authority = wl.authority ?? state.authority;
            const running = wl.status === 'RUNNING';
            return (
              <div key={m.id} data-testid={`workload-card-${m.id}`} className="tp-card p-6">
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <LiveDot tone={running ? 'ok' : wl.status === 'PAUSED' ? 'warn' : 'idle'} live={running} />
                      <h2 className="font-serif text-2xl leading-tight text-ink">{m.name}</h2>
                      <span className="tp-chip font-mono">{wl.status}</span>
                      {authority && (
                        <span className="tp-chip font-mono">
                          {authority.state} · epoch {authority.epoch}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 truncate font-mono text-[11px] text-faint">
                      {m.id} · {m.command}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {running && (
                      <button
                        type="button"
                        onClick={() =>
                          void apiStopWorkload(m.id)
                            .then(() => setActionMessage(`${m.name} stopped.`))
                            .catch((err: unknown) =>
                              setActionMessage(`Could not stop: ${err instanceof Error ? err.message : String(err)}`),
                            )
                        }
                        className="tp-btn"
                      >
                        Stop
                      </button>
                    )}
                    <button type="button" onClick={() => handleOpenMigrate(wl)} className="tp-btn-primary">
                      <span>Migrate</span>
                      <Icon name="arrow" className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                <dl className="mt-5 grid grid-cols-2 gap-4 border-y border-line py-3.5 text-xs sm:grid-cols-4">
                  <div>
                    <dt className="text-[10.5px] text-faint">Runtime</dt>
                    <dd className="mt-0.5 text-ink">
                      {m.runtime.name} {m.runtime.minVersion}+
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] text-faint">Architecture</dt>
                    <dd className="mt-0.5 text-ink">{m.arch.join(', ')}</dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] text-faint">Needs at least</dt>
                    <dd className="mt-0.5 text-ink">
                      {formatMb(m.minRamMb)} · {m.minCpuCores} cores
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] text-faint">If it cannot move</dt>
                    <dd className="mt-0.5 text-ink">{m.remoteCapable ? 'remote access' : 'stays here'}</dd>
                  </div>
                </dl>

                <div className="mt-4">
                  <p className="tp-label">
                    {m.checkpoints.length} checkpoint{m.checkpoints.length === 1 ? '' : 's'}
                  </p>
                  <ol className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-2 text-xs">
                    {m.checkpoints.map((chk, idx) => (
                      <li key={chk.id} className="flex items-center gap-2">
                        {idx > 0 && <span className="h-px w-4 bg-line-strong" aria-hidden="true" />}
                        <span
                          className="rounded-full border border-line px-2.5 py-1 text-ink"
                          title={chk.paths.join(', ') || 'state saved by the program'}
                        >
                          <span className="mr-1.5 font-mono text-faint">{idx + 1}</span>
                          {chk.name}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Start Workload Modal */}
      {isStartOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-line bg-surface p-6 shadow-2xl">
            <h2 className="text-lg font-bold text-ink">Start Workload by Manifest</h2>
            <p className="mt-1 text-xs text-muted">
              Provide the relative or absolute path to the JSON manifest.
            </p>

            <form onSubmit={handleStartWorkload} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-muted">
                  Manifest Path
                </label>
                <input
                  type="text"
                  value={manifestPath}
                  onChange={(e) => setManifestPath(e.target.value)}
                  placeholder="examples/migratable_ml_trainer/manifest.json"
                  className="mt-1 w-full rounded-lg border border-line-strong bg-raised px-3.5 py-2 font-mono text-xs text-ink outline-none focus:border-ink/40 focus:ring-1 focus:ring-ink/20"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsStartOpen(false)}
                  className="tp-btn"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="tp-btn-primary"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-line bg-surface p-6 shadow-2xl">
            <h2 className="text-lg font-bold text-ink">
              Select Target for &quot;{selectedWorkload.manifest.name}&quot;
            </h2>
            <p className="mt-1 text-xs text-muted">
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
                    className="flex items-center justify-between rounded-lg border border-line bg-raised p-3 text-xs"
                  >
                    <div>
                      <span className="font-semibold text-ink">{peer.name}</span>
                      <p className="text-[11px] text-muted">
                        {peer.os} · {peer.arch} · {formatMb(peer.ramMb)} RAM
                      </p>
                    </div>
                    <button
                      onClick={() => void migrateTo(selectedWorkload, peer.id, peer.name)}
                      className="tp-btn-primary"
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
                className="tp-btn"
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

