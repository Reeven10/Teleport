import { useState } from 'react';
import { useTeleport } from '../store/useTeleport.ts';
import { apiStartMigration, apiAbortMigration } from '../api.ts';
import { PhaseStepper } from '../components/migration/PhaseStepper.tsx';
import { FeasibilityPanel } from '../components/migration/FeasibilityPanel.tsx';
import { CheckpointGrid } from '../components/migration/CheckpointGrid.tsx';
import { AuthorityPanel } from '../components/migration/AuthorityPanel.tsx';
import { TransferStats } from '../components/migration/TransferStats.tsx';
import { ResourceComparison } from '../components/migration/ResourceComparison.tsx';
import { RecommendationBanner } from '../components/migration/RecommendationBanner.tsx';

export function MigrationPage() {
  const { state, setSimulationScenario } = useTeleport();
  const [showStartModal, setShowStartModal] = useState(false);
  const [targetId, setTargetId] = useState<string>('');
  const [workloadId, setWorkloadId] = useState<string>('');
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const mig = state.migrationStatus;
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

  return (
    <div className="space-y-6">
      {/* Top Header & Page Controls */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
              Migration Engine & Authority Cutover
            </h1>
            <span
              data-testid="migration-phase-badge"
              className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider ${
                mig?.phase === 'COMPLETED'
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400'
                  : mig?.phase === 'ROLLED_BACK'
                  ? 'bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-400'
                  : mig?.phase === 'REMOTE_ACCESS'
                  ? 'bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-400'
                  : 'bg-blue-100 text-blue-700 dark:bg-blue-950/60 dark:text-blue-400'
              }`}
            >
              {mig?.phase || 'IDLE'}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Atomic state transfer pipeline, SHA-256 chunk validation, and zero double-spend epoch fencing
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="btn-start-migration"
            disabled={actionLoading || Boolean(isMigrating)}
            onClick={handleOpenStart}
            className="flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
            <span>Start Migration</span>
          </button>

          <button
            type="button"
            data-testid="btn-abort-migration"
            disabled={actionLoading || !isMigrating}
            onClick={handleAbort}
            className="flex items-center gap-1.5 rounded-xl border border-rose-300 bg-white px-3.5 py-2 text-xs font-bold text-rose-700 shadow-sm transition hover:bg-rose-50 disabled:opacity-40 dark:border-rose-900/60 dark:bg-slate-900 dark:text-rose-400 dark:hover:bg-rose-950/30"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            <span>Abort</span>
          </button>

          <button
            type="button"
            data-testid="btn-rollback-migration"
            disabled={actionLoading || !mig || mig.phase === 'COMPLETED' || mig.phase === 'ROLLED_BACK'}
            onClick={handleRollback}
            className="flex items-center gap-1.5 rounded-xl border border-amber-300 bg-white px-3.5 py-2 text-xs font-bold text-amber-700 shadow-sm transition hover:bg-amber-50 disabled:opacity-40 dark:border-amber-900/60 dark:bg-slate-900 dark:text-amber-400 dark:hover:bg-amber-950/30"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
            </svg>
            <span>Roll Back</span>
          </button>
        </div>
      </div>

      {actionError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
          {actionError}
        </div>
      )}

      {/* Scenario Simulation Switcher */}
      {state.mockFeederActive && (
        <div
          data-testid="scenario-picker-bar"
          className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/70 p-2.5 text-xs dark:border-slate-800 dark:bg-slate-900/40"
        >
          <span className="text-[11px] font-bold uppercase text-slate-500">Live Demo Scenarios:</span>
          <button
            type="button"
            data-testid="scenario-inflight"
            onClick={() => setSimulationScenario('in_flight')}
            className="rounded-lg bg-white px-2.5 py-1 font-semibold text-blue-600 shadow-sm border border-slate-200 hover:bg-blue-50 dark:border-slate-700 dark:bg-slate-800 dark:text-blue-400"
          >
            5 of 10 In-Flight (Authority on A)
          </button>
          <button
            type="button"
            data-testid="scenario-completed"
            onClick={() => setSimulationScenario('completed')}
            className="rounded-lg bg-white px-2.5 py-1 font-semibold text-emerald-600 shadow-sm border border-slate-200 hover:bg-emerald-50 dark:border-slate-700 dark:bg-slate-800 dark:text-emerald-400"
          >
            Completed Cutover (42ms Interruption)
          </button>
          <button
            type="button"
            data-testid="scenario-rollback"
            onClick={() => setSimulationScenario('rollback')}
            className="rounded-lg bg-white px-2.5 py-1 font-semibold text-rose-600 shadow-sm border border-slate-200 hover:bg-rose-50 dark:border-slate-700 dark:bg-slate-800 dark:text-rose-400"
          >
            Rollback (SHA mismatch checkpoint 4)
          </button>
          <button
            type="button"
            data-testid="scenario-remote"
            onClick={() => setSimulationScenario('remote_access')}
            className="rounded-lg bg-white px-2.5 py-1 font-semibold text-sky-600 shadow-sm border border-slate-200 hover:bg-sky-50 dark:border-slate-700 dark:bg-slate-800 dark:text-sky-400"
          >
            Remote Access Branch (Pinned GPU)
          </button>
        </div>
      )}

      {/* (h) Orchestrator Proactive Recommendation Banner */}
      <RecommendationBanner />

      {/* (a) Phase Stepper */}
      <PhaseStepper phase={mig?.phase || 'CONNECTING'} />

      {/* Grid: (b) Feasibility Decision & Reasons + (e) Transfer Progress & Interruption Time */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <FeasibilityPanel
          decision={mig?.decision || (mig?.phase === 'REMOTE_ACCESS' ? 'REMOTE_ACCESS' : 'MIGRATE')}
          reasons={mig?.reasons || []}
        />
        <TransferStats
          bytesDone={mig?.bytesDone || 0}
          bytesTotal={mig?.bytesTotal || 0}
          linkType={mig?.link || state.link?.link || 'wifi'}
          interruptionMs={mig?.interruptionMs}
          speedMbps={state.link?.mbps || 120}
        />
      </div>

      {/* (d) Authority Cutover Panel */}
      <AuthorityPanel
        authority={mig?.authority}
        deviceA={state.devices[state.thisDeviceId]}
        deviceB={state.peerDeviceId ? state.devices[state.peerDeviceId] : undefined}
      />

      {/* (c) Checkpoint Grid */}
      <CheckpointGrid checkpoints={mig?.checkpoints || []} authority={mig?.authority} />

      {/* (f) Node Telemetry Resource Comparison */}
      <ResourceComparison />

      {/* Start Migration Modal */}
      {showStartModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            <h3 className="text-lg font-bold text-slate-900 dark:text-white">
              Initiate Workload Migration
            </h3>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Select workload and designated peer node to begin zero-downtime checkpoint synchronization.
            </p>

            <div className="mt-5 space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                  Target Workload
                </label>
                <select
                  value={workloadId}
                  onChange={(e) => setWorkloadId(e.target.value)}
                  className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-white"
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
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">
                  Target Peer Device
                </label>
                <select
                  value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}
                  className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-white"
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

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowStartModal(false)}
                className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="modal-confirm-start"
                onClick={handleStartMigration}
                disabled={actionLoading}
                className="rounded-xl bg-blue-600 px-5 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
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
