import type { FeasibilityResult, MigrationStatus, Phase } from '@contract';
import { useEffect, useRef, useState } from 'react';
import { useTeleport } from '../store/useTeleport.ts';
import { apiStartMigration, apiAbortMigration, apiCheckFeasibility, apiFetchMigrations } from '../api.ts';
import { CompatibilityCard } from '../components/migration/CompatibilityCard.tsx';
import { PhaseStepper } from '../components/migration/PhaseStepper.tsx';
import { FeasibilityPanel } from '../components/migration/FeasibilityPanel.tsx';
import { CheckpointGrid } from '../components/migration/CheckpointGrid.tsx';
import { AuthorityPanel } from '../components/migration/AuthorityPanel.tsx';
import { TransferStats } from '../components/migration/TransferStats.tsx';
import { RecommendationBanner } from '../components/migration/RecommendationBanner.tsx';
import { Bridge } from '../components/dashboard/Bridge.tsx';
import { Icon, PageHeader } from '../components/ui/Icon.tsx';

const TERMINAL: Phase[] = ['COMPLETED', 'ROLLED_BACK', 'FAILED', 'REMOTE_ACCESS', 'IDLE'];

/** When each phase of the current migration started, and the last phase that ran before it ended. */
function usePhaseTimeline(id: string | undefined, phase: Phase | undefined) {
  const ref = useRef<{ id?: string; times: Partial<Record<Phase, number>>; last: Phase | null }>({ times: {}, last: null });
  if (ref.current.id !== id) ref.current = { id, times: {}, last: null };
  if (phase && ref.current.times[phase] == null) ref.current.times[phase] = Date.now();
  if (phase && !TERMINAL.includes(phase) && phase !== 'ROLLING_BACK') ref.current.last = phase;
  const [now, setNow] = useState(Date.now());
  const active = Boolean(phase && !TERMINAL.includes(phase));
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(t);
  }, [active]);
  return { times: ref.current.times, failedAt: ref.current.last, now };
}

export function MigrationPage() {
  const { state, setSimulationScenario } = useTeleport();
  const [showStartModal, setShowStartModal] = useState(false);
  const [targetId, setTargetId] = useState<string>('');
  const [workloadId, setWorkloadId] = useState<string>('');
  const [feasibility, setFeasibility] = useState<FeasibilityResult | null>(null);
  const [checking, setChecking] = useState(false);
  // The compatibility card in the start dialog: re-evaluated whenever the workload or target changes.
  useEffect(() => {
    if (!showStartModal || !workloadId || !targetId || !state.agentReachable || state.mockFeederActive) return;
    let alive = true;
    setChecking(true);
    setFeasibility(null);
    apiCheckFeasibility(workloadId, targetId)
      .then((res) => alive && setFeasibility(res))
      .catch(() => alive && setFeasibility(null))
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, [showStartModal, workloadId, targetId, state.agentReachable, state.mockFeederActive]);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Every migration has its own status and its own lease: list them all and show the chosen one.
  const [all, setAll] = useState<MigrationStatus[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => {
    if (!state.agentReachable || state.mockFeederActive) return;
    let alive = true;
    const load = () =>
      apiFetchMigrations()
        .then((list) => alive && setAll(list.slice(-8).reverse()))
        .catch(() => {});
    load();
    const timer = window.setInterval(load, 1500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [state.agentReachable, state.mockFeederActive]);
  const mig = (selectedId ? all.find((m) => m.id === selectedId) : null) ?? state.migrationStatus;
  const timeline = usePhaseTimeline(mig?.id, mig?.phase);
  const isMigrating =
    mig &&
    !['COMPLETED', 'ROLLED_BACK', 'REMOTE_ACCESS'].includes(mig.phase);

  // Available candidate target devices (excluding this device)
  const candidateTargets = Object.values(state.devices).filter(
    (d) => d.id !== state.thisDeviceId
  );

  const defaultWorkload = state.workloads[0]?.manifest.id || 'workload-1';

  const handleOpenStart = () => {
    setWorkloadId(defaultWorkload);
    setTargetId(candidateTargets[0]?.id || state.peerDeviceId || 'device-b');
    setActionError(null);
    setShowStartModal(true);
  };

  const handleStartMigration = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      if (state.agentReachable) {
        await apiStartMigration(
          workloadId || defaultWorkload,
          targetId || 'device-b',
          'user_command',
        );
      } else {
        // Mock mode trigger in-flight migration
        setSimulationScenario('in_flight');
      }
      setShowStartModal(false);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Migration initiation failed');
    } finally {
      setActionLoading(false);
    }
  };

  const handleAbort = async () => {
    if (!mig) return;
    setActionLoading(true);
    setActionError(null);
    try {
      if (state.agentReachable) {
        await apiAbortMigration(mig.id);
      } else {
        setSimulationScenario('rollback');
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Abort request failed');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRollback = async () => {
    if (!mig) return;
    setActionLoading(true);
    setActionError(null);
    try {
      if (state.agentReachable) {
        await apiAbortMigration(mig.id);
      } else {
        setSimulationScenario('rollback');
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Rollback request failed');
    } finally {
      setActionLoading(false);
    }
  };

  const source = mig ? state.devices[mig.sourceId] : undefined;
  const target = mig ? state.devices[mig.targetId] : undefined;
  const workloadName = mig
    ? (state.workloads.find((w) => w.manifest.id === mig.workloadId)?.manifest.name ?? mig.workloadId)
    : null;
  const phaseTone =
    mig?.phase === 'COMPLETED'
      ? 'border-ok/40 text-ok'
      : mig?.phase === 'ROLLED_BACK' || mig?.phase === 'FAILED'
        ? 'border-bad/40 text-bad'
        : mig?.phase === 'REMOTE_ACCESS'
          ? 'border-steel/40 text-steel'
          : isMigrating
            ? 'border-accent/40 text-accent'
            : '';

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Migration"
        title={workloadName ?? 'Move a workload'}
        description={
          mig ? (
            <>
              {source?.name ?? mig.sourceId}{' '}
              <Icon name="arrow" className="inline h-3.5 w-3.5 align-[-2px]" /> {target?.name ?? mig.targetId}
              <span className="text-faint"> · trigger {mig.trigger}</span>
            </>
          ) : (
            'Checkpoints travel while the workload keeps running; it pauses only for the last small delta.'
          )
        }
        actions={
          <>
            <span data-testid="migration-phase-badge" className={`tp-chip font-mono ${phaseTone}`}>
              {mig?.phase || 'IDLE'}
            </span>
            <button
              type="button"
              data-testid="btn-abort-migration"
              disabled={actionLoading || !isMigrating}
              onClick={handleAbort}
              className="tp-btn"
            >
              Abort
            </button>
            <button
              type="button"
              data-testid="btn-rollback-migration"
              disabled={actionLoading || !mig || mig.phase === 'COMPLETED' || mig.phase === 'ROLLED_BACK'}
              onClick={handleRollback}
              className="tp-btn"
            >
              Roll back
            </button>
            <button
              type="button"
              data-testid="btn-start-migration"
              disabled={actionLoading || Boolean(isMigrating)}
              onClick={handleOpenStart}
              className="tp-btn-primary"
            >
              Start migration
              <Icon name="arrow" className="h-3.5 w-3.5" />
            </button>
          </>
        }
      />

      {actionError && (
        <div className="rounded-xl border border-bad/30 bg-bad-soft p-3 text-sm text-bad">{actionError}</div>
      )}

      {mig && mig.error && ['ROLLED_BACK', 'FAILED', 'ROLLING_BACK'].includes(mig.phase) && (
        <div data-testid="migration-error" className="flex gap-3 rounded-2xl border border-bad/30 bg-bad-soft p-4">
          <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
          <div>
            <p className="text-sm font-medium text-ink">
              {mig.phase === 'FAILED' ? 'Not migrated' : 'Rolled back: the workload kept running on the source'}
            </p>
            <p className="mt-1 text-sm text-ink/80">{mig.error}</p>
            <p className="mt-1 text-xs text-muted">Details are in the reasons below.</p>
          </div>
        </div>
      )}

      {/* Scenario Simulation Switcher */}
      {state.mockFeederActive && (
        <div
          data-testid="scenario-picker-bar"
          className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-warn/50 p-2.5 text-xs"
        >
          <span className="tp-label px-1">Demo scenarios</span>
          <button
            type="button"
            data-testid="scenario-inflight"
            onClick={() => setSimulationScenario('in_flight')}
            className="tp-btn"
          >
            5 of 10 In-Flight (Authority on A)
          </button>
          <button
            type="button"
            data-testid="scenario-completed"
            onClick={() => setSimulationScenario('completed')}
            className="tp-btn"
          >
            Completed Cutover (42ms Interruption)
          </button>
          <button
            type="button"
            data-testid="scenario-rollback"
            onClick={() => setSimulationScenario('rollback')}
            className="tp-btn"
          >
            Rollback (SHA mismatch checkpoint 4)
          </button>
          <button
            type="button"
            data-testid="scenario-remote"
            onClick={() => setSimulationScenario('remote_access')}
            className="tp-btn"
          >
            Remote Access Branch (Pinned GPU)
          </button>
        </div>
      )}


      {state.authorityConflict && (
        <div
          data-testid="migration-authority-conflict"
          className="flex gap-3 rounded-2xl border border-bad/30 bg-bad-soft p-4 text-sm"
        >
          <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
          <p className="text-ink">
            Two copies of {state.authorityConflict.workloadId} were running. Kept {state.authorityConflict.winner},
            stopped {state.authorityConflict.stopped} (epoch {state.authorityConflict.remoteEpoch} vs{' '}
            {state.authorityConflict.localEpoch}). <span className="text-muted">{state.authorityConflict.reason}</span>
          </p>
        </div>
      )}

      {all.length > 1 && (
        <div data-testid="migration-tabs" className="flex flex-wrap gap-2">
          {all.map((m) => {
            const active = m.id === mig?.id;
            const live = !['COMPLETED', 'ROLLED_BACK', 'FAILED', 'REMOTE_ACCESS'].includes(m.phase);
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => setSelectedId(m.id)}
                className={`rounded-xl border px-3 py-2 text-left text-xs transition-colors ${
                  active ? 'border-ink bg-surface' : 'border-line hover:bg-surface'
                }`}
              >
                <span className="flex items-center gap-1.5 text-ink">
                  {live && <span className="h-1.5 w-1.5 rounded-full bg-accent" />}
                  {state.workloads.find((w) => w.manifest.id === m.workloadId)?.manifest.name ?? m.workloadId}
                </span>
                <span className="font-mono text-[10.5px] text-faint">
                  {m.phase.toLowerCase()} · lease e{m.authority.epoch} · {m.id.slice(-6)}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <RecommendationBanner />

      <Bridge
        self={state.devices[state.thisDeviceId]}
        peer={state.peerDeviceId ? state.devices[state.peerDeviceId] : undefined}
        selfStats={state.stats[state.thisDeviceId]}
        peerStats={state.peerDeviceId ? state.stats[state.peerDeviceId] : undefined}
        link={state.link}
        migration={mig}
      />

      <PhaseStepper
        phase={mig?.phase || 'CONNECTING'}
        failedAt={timeline.failedAt}
        startedAt={timeline.times}
        now={timeline.now}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.35fr_1fr]">
        <CheckpointGrid
          checkpoints={mig?.checkpoints || []}
          authority={mig?.authority}
          phase={mig?.phase}
          metrics={mig?.metrics?.checkpoints}
        />
        <div className="space-y-5">
          <TransferStats
            bytesDone={mig?.bytesDone || 0}
            bytesTotal={mig?.bytesTotal || 0}
            linkType={mig?.link || state.link?.link || 'wifi'}
            interruptionMs={mig?.interruptionMs}
            speedMbps={state.link?.mbps || 120}
            metrics={mig?.metrics}
            migrationId={mig?.id}
          />
          <AuthorityPanel
            authority={mig?.authority}
            deviceA={state.devices[mig?.sourceId ?? state.thisDeviceId]}
            deviceB={state.devices[mig?.targetId ?? state.peerDeviceId ?? '']}
          />
        </div>
      </div>

      <FeasibilityPanel
        decision={mig?.decision || (mig?.phase === 'REMOTE_ACCESS' ? 'REMOTE_ACCESS' : 'MIGRATE')}
        reasons={mig?.reasons || []}
      />

      {/* Start Migration Modal */}
      {showStartModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4">
          <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-line bg-canvas p-6 shadow-2xl">
            <p className="tp-label">Migrate</p>
            <h3 className="mt-1 font-serif text-2xl text-ink">Start a migration</h3>
            <p className="mt-1 text-xs text-muted">
              Pick the workload and the laptop to move it to. Check the compatibility below, then start.
            </p>

            <div className="mt-5 space-y-4">
              <div>
                <label className="block text-xs font-bold text-ink/85">
                  Target Workload
                </label>
                <select
                  value={workloadId}
                  onChange={(e) => setWorkloadId(e.target.value)}
                  className="mt-1.5 block w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-xs font-semibold text-ink shadow-sm focus:border-ink/40 focus:outline-none"
                >
                  {state.workloads.length > 0 ? (
                    state.workloads.map((w) => (
                      <option key={w.manifest.id} value={w.manifest.id}>
                        {w.manifest.name} ({w.manifest.id}) - {w.manifest.runtime.name}
                      </option>
                    ))
                  ) : (
                    <option value="workload-1">Render-Pipeline-Primary (workload-1)</option>
                  )}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-ink/85">
                  Target Peer Device
                </label>
                <select
                  value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}
                  className="mt-1.5 block w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-xs font-semibold text-ink shadow-sm focus:border-ink/40 focus:outline-none"
                >
                  {candidateTargets.length > 0 ? (
                    candidateTargets.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} ({d.id}) - {d.os}
                      </option>
                    ))
                  ) : (
                    <option value="device-b">MacBook Pro M3 Max (device-b)</option>
                  )}
                </select>
              </div>
            </div>

            {state.agentReachable && !state.mockFeederActive && workloadId && targetId && (
              <div className="mt-5">
                {(() => {
                  const wl = state.workloads.find((w) => w.manifest.id === workloadId);
                  return wl ? (
                    <CompatibilityCard
                      manifest={wl.manifest}
                      source={state.devices[state.thisDeviceId]}
                      sourceStats={state.stats[state.thisDeviceId]}
                      target={state.devices[targetId]}
                      targetStats={state.stats[targetId]}
                      link={state.link}
                      feasibility={feasibility}
                      loading={checking}
                    />
                  ) : null;
                })()}
              </div>
            )}

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowStartModal(false)}
                className="rounded-xl px-4 py-2 text-xs font-semibold text-muted hover:bg-raised"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="modal-confirm-start"
                onClick={handleStartMigration}
                disabled={actionLoading}
                className="tp-btn-primary"
              >
                {actionLoading ? 'Connecting...' : 'Start Transfer Pipeline'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
