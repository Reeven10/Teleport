import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTeleport } from '../../store/useTeleport.ts';
import { apiStartMigration } from '../../api.ts';
import { Icon } from '../ui/Icon.tsx';

export function RecommendationBanner() {
  const { state, clearRecommendation } = useTeleport();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const rec = state.recommendation;
  if (!rec) return null;

  const isMigrate = rec.decision === 'MIGRATE';
  const isRemote = rec.decision === 'REMOTE_ACCESS';

  const badgeColor = 'font-mono';

  const handleAccept = async () => {
    setErrorMsg(null);
    if (isRemote) {
      clearRecommendation();
      navigate('/remote');
      return;
    }

    if (isMigrate) {
      setSubmitting(true);
      try {
        const target = rec.targetId || state.peerDeviceId || 'device-b';
        if (state.agentReachable) {
          await apiStartMigration(rec.workloadId, target, 'user_command');
        }
        clearRecommendation();
      } catch (err: unknown) {
        setErrorMsg(err instanceof Error ? err.message : 'Failed to start migration');
      } finally {
        setSubmitting(false);
      }
    } else {
      clearRecommendation();
    }
  };

  const handleDismiss = () => {
    clearRecommendation();
  };

  return (
    <div
      data-testid="recommendation-banner"
      className="flex flex-col gap-3 rounded-2xl border border-accent/30 bg-accent-soft p-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-3">
        <Icon name="bolt" className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
        <div>
          <p className="text-sm text-ink">
            <span className="font-medium">
              Teleport suggests {isMigrate ? 'migrating' : isRemote ? 'remote access for' : 'keeping'}
            </span>{' '}
            <span className="font-mono text-xs">{rec.workloadId}</span>
            {rec.targetId ? <span className="text-muted"> to {state.devices[rec.targetId]?.name ?? rec.targetId}</span> : null}
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {rec.reasons[0]?.text || 'Automatic policy'} · trigger {rec.trigger} ·{' '}
            <span className={badgeColor}>{rec.decision}</span>
          </p>
          {errorMsg && <p className="mt-1 text-xs text-bad">{errorMsg}</p>}
        </div>
      </div>
      <div className="flex items-center gap-2 self-end sm:self-center">
        <button type="button" data-testid="recommendation-dismiss" onClick={handleDismiss} className="tp-btn border-transparent bg-transparent">
          Dismiss
        </button>
        <button type="button" data-testid="recommendation-accept" disabled={submitting} onClick={handleAccept} className="tp-btn-primary">
          {submitting ? 'Starting...' : isRemote ? 'Open remote access' : 'Accept'}
        </button>
      </div>
    </div>
  );
}
