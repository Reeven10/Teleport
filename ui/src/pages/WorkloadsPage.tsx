import { useEffect, useState } from 'react';
import type { Authority, FeasibilityResult, WorkloadRun } from '@contract';
import { useNavigate } from 'react-router-dom';
import {
  apiCheckFeasibility,
  apiFetchApps,
  apiFetchAuthority,
  apiFetchWorkloadRuns,
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
import { FolderField } from '../components/ui/FolderField.tsx';
import { ServerAppCard } from '../components/workloads/ServerAppCard.tsx';
import { CompatibilityCard } from '../components/migration/CompatibilityCard.tsx';

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

  // Each workload's own lease and its latest log line (installing, ready on http://localhost:...).
  const [leases, setLeases] = useState<Record<string, Authority>>({});
  const [runs, setRuns] = useState<Record<string, WorkloadRun>>({});
  useEffect(() => {
    if (!state.agentReachable || state.mockFeederActive) return;
    let alive = true;
    const load = () => {
      apiFetchAuthority()
        .then((list) => alive && setLeases(Object.fromEntries(list.map((a) => [a.workloadId, a]))))
        .catch(() => {});
      apiFetchWorkloadRuns()
        .then((list) => alive && setRuns(Object.fromEntries(list.map((r) => [r.workloadId, r]))))
        .catch(() => {});
    };
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [state.agentReachable, state.mockFeederActive]);

  const [targetId, setTargetId] = useState<string | null>(null);
  const [feasibility, setFeasibility] = useState<FeasibilityResult | null>(null);
  const [checking, setChecking] = useState(false);

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
    const others = Object.values(state.devices).filter((d) => d.id !== state.thisDeviceId);
    void chooseTarget(wl, others.length === 1 ? (others[0]?.id ?? null) : null);
  }

  async function chooseTarget(wl: WorkloadItem, id: string | null) {
    setTargetId(id);
    setFeasibility(null);
    if (!id || !state.agentReachable) return;
    setChecking(true);
    try {
      setFeasibility(await apiCheckFeasibility(wl.manifest.id, id));
    } catch {
      setFeasibility(null);
    } finally {
      setChecking(false);
    }
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
          {apps.map((app) =>
            app.id === 'server' ? (
              <ServerAppCard
                key={app.id}
                app={app}
                onStarted={(manifest, message) => {
                  addWorkload({ manifest, status: 'RUNNING' });
                  setActionMessage(message);
                }}
                onError={setActionMessage}
              />
            ) : (
            <div key={app.id} data-testid={`app-${app.id}`} className="tp-card flex flex-col p-5">
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-raised text-muted">
                  <Icon name={app.id === 'vscode' ? 'folder' : app.id === 'pinned-notes' ? 'remote' : 'play'} className="h-4 w-4" />
                </span>
                <div>
                  <h2 className="text-[15px] font-medium text-ink">{app.title}</h2>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted">{app.description}</p>
                </div>
              </div>
              {app.needs === 'projectPath' && (
                <div className="mt-4">
                  <FolderField
                    value={projectPath}
                    onChange={setProjectPath}
                    title="Choose the project to open in VS Code"
                    testId="vscode-project-path"
                  />
                </div>
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
            ),
          )}
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
            const authority = leases[m.id] ?? wl.authority;
            const run = runs[m.id];
            const lastLine = run?.logTail.filter((l) => l.trim()).at(-1);
            const readyUrl = run?.logTail.map((l) => /ready on (http:\/\/localhost:\d+)/.exec(l)?.[1]).filter(Boolean).at(-1);
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
                        <span
                          className="tp-chip font-mono"
                          title={authority.migrationId ? `set by migration ${authority.migrationId}` : 'never migrated'}
                        >
                          {authority.state} · epoch {authority.epoch}
                          {authority.migrationId ? ` · ${authority.migrationId.slice(-6)}` : ''}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 truncate font-mono text-[11px] text-faint">
                      {m.id} · {m.command}
                    </p>
                    {running && lastLine && (
                      <p data-testid={`workload-status-${m.id}`} className="mt-1.5 truncate text-xs text-muted" title={lastLine}>
                        {lastLine.replace(/^\[(server|vscode)\]\s*/, '')}
                      </p>
                    )}
                    {running && readyUrl && (
                      <a href={readyUrl} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-accent hover:underline">
                        Open {readyUrl} <Icon name="arrow" className="h-3 w-3" />
                      </a>
                    )}
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
            <h2 className="font-serif text-2xl text-ink">Start a workload</h2>
            <p className="mt-1 text-xs text-muted">
              Choose a folder that contains a teleport.yaml. For a VS Code project or a server, use the cards
              above instead.
            </p>

            <form onSubmit={handleStartWorkload} className="mt-4 space-y-4">
              <div>
                <label className="tp-label">Workload folder</label>
                <div className="mt-1">
                  <FolderField
                    value={manifestPath}
                    onChange={setManifestPath}
                    placeholder="Folder with a teleport.yaml"
                    title="Choose the workload folder (it contains teleport.yaml)"
                    testId="manifest-path"
                  />
                </div>
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

      {/* Migrate: pick the target, see the compatibility card, then confirm */}
      {isTargetPickerOpen && selectedWorkload && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/60 p-4 sm:items-center">
          <div className="w-full max-w-2xl rounded-2xl border border-line bg-canvas p-6 shadow-2xl">
            <p className="tp-label">Migrate</p>
            <h2 className="mt-1 font-serif text-2xl text-ink">{selectedWorkload.manifest.name}</h2>

            {peers.length === 0 ? (
              <p className="mt-4 rounded-xl border border-warn/40 bg-warn-soft p-3 text-sm text-ink">
                No paired device yet: click Pair Device in the top bar first.
              </p>
            ) : (
              <div className="mt-4 flex flex-wrap gap-2">
                {peers.map((peer) => (
                  <button
                    key={peer.id}
                    type="button"
                    data-testid={`target-${peer.id}`}
                    onClick={() => void chooseTarget(selectedWorkload, peer.id)}
                    className={`rounded-xl border px-3 py-2 text-left text-xs transition-colors ${
                      targetId === peer.id ? 'border-ink bg-surface' : 'border-line hover:bg-surface'
                    }`}
                  >
                    <span className="block text-sm text-ink">{peer.name}</span>
                    <span className="text-faint">
                      {peer.os} · {peer.arch} · {formatMb(peer.ramMb)}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {targetId && (
              <div className="mt-4">
                <CompatibilityCard
                  manifest={selectedWorkload.manifest}
                  source={state.devices[state.thisDeviceId]}
                  sourceStats={state.stats[state.thisDeviceId]}
                  target={state.devices[targetId]}
                  targetStats={state.stats[targetId]}
                  link={state.link}
                  feasibility={feasibility}
                  loading={checking}
                />
              </div>
            )}

            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setIsTargetPickerOpen(false)} className="tp-btn">
                Cancel
              </button>
              <button
                type="button"
                data-testid="confirm-migrate"
                disabled={!targetId || checking}
                onClick={() =>
                  targetId && void migrateTo(selectedWorkload, targetId, state.devices[targetId]?.name ?? targetId)
                }
                className="tp-btn-primary"
              >
                {feasibility?.decision === 'REMOTE_ACCESS' ? 'Continue with remote access' : 'Migrate now'}
                <Icon name="arrow" className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

