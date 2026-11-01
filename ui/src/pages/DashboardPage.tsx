import { Link } from 'react-router-dom';
import { Bridge } from '../components/dashboard/Bridge.tsx';
import { DemoControlPanel } from '../components/dashboard/DemoControlPanel.tsx';
import { DeviceCard } from '../components/dashboard/DeviceCard.tsx';
import { Icon, LiveDot, PageHeader } from '../components/ui/Icon.tsx';
import { useTeleport } from '../store/useTeleport.ts';

export function DashboardPage() {
  const { state } = useTeleport();

  const thisDevice = state.devices[state.thisDeviceId];
  const peerDevice = state.peerDeviceId ? state.devices[state.peerDeviceId] : undefined;
  const statsA = state.stats[state.thisDeviceId];
  const statsB = state.peerDeviceId ? state.stats[state.peerDeviceId] : undefined;
  const historyA = state.history60s[state.thisDeviceId] ?? [];
  const historyB = state.peerDeviceId ? (state.history60s[state.peerDeviceId] ?? []) : [];
  const rec = state.recommendation;
  const conflict = state.authorityConflict;
  const running = state.workloads.filter((w) => w.status === 'RUNNING' || w.status === 'PAUSED');

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Overview"
        title="Devices"
        description="Both laptops, their live stats, and the encrypted link between them."
        actions={
          <>
            <span className="tp-chip">{Object.keys(state.devices).length} devices</span>
            <span className="tp-chip" title="Each workload has its own authority lease">
              {running.length} running here
            </span>
          </>
        }
      />

      <DemoControlPanel />

      {conflict && (
        <div data-testid="authority-conflict-banner" className="flex gap-3 rounded-2xl border border-bad/30 bg-bad-soft p-4 text-sm">
          <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
          <div>
            <p className="font-medium text-ink">Two copies were running: Teleport stopped one</p>
            <p className="mt-1 text-xs text-muted">
              {conflict.workloadId}: epoch {conflict.localEpoch} here, {conflict.remoteEpoch} there. Kept{' '}
              <span className="text-ink">{conflict.winner}</span>, stopped <span className="text-ink">{conflict.stopped}</span>.{' '}
              {conflict.reason}
            </p>
          </div>
        </div>
      )}

      {rec && (
        <div className="flex flex-col gap-3 rounded-2xl border border-warn/30 bg-warn-soft p-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex gap-3">
            <Icon name="bolt" className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
            <div>
              <p className="text-sm font-medium text-ink">
                Teleport suggests: {rec.decision === 'MIGRATE' ? 'migrate' : rec.decision === 'REMOTE_ACCESS' ? 'remote access' : 'stay'}{' '}
                <span className="font-mono text-xs text-muted">{rec.workloadId}</span>
              </p>
              <ul className="mt-1.5 space-y-0.5 text-xs text-muted">
                {rec.reasons.map((r, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <Icon name={r.severity === 'pass' ? 'check' : 'alert'} className={`mt-px h-3.5 w-3.5 shrink-0 ${r.severity === 'pass' ? 'text-ok' : 'text-warn'}`} />
                    {r.text}
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <span className="tp-chip shrink-0">trigger: {rec.trigger}</span>
        </div>
      )}

      <Bridge
        self={thisDevice}
        peer={peerDevice}
        selfStats={statsA}
        peerStats={statsB}
        link={state.link}
        migration={state.migrationStatus}
      />

      {running.length > 0 && (
        <div className="tp-card flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
          <span className="tp-label">Running here</span>
          {running.map((w) => (
            <span key={w.manifest.id} className="flex items-center gap-2 text-sm text-ink">
              <LiveDot tone={w.status === 'PAUSED' ? 'warn' : 'ok'} />
              {w.manifest.name}
            </span>
          ))}
          <Link to="/workloads" className="ml-auto flex items-center gap-1 text-xs text-muted hover:text-ink">
            Manage <Icon name="arrow" className="h-3.5 w-3.5" />
          </Link>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <DeviceCard device={thisDevice} stats={statsA} history={historyA} roleTitle="Device A · this laptop" isSelf />
        <DeviceCard device={peerDevice} stats={statsB} history={historyB} roleTitle="Device B · peer" />
      </div>
    </div>
  );
}
