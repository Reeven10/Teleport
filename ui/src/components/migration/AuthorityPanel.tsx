import type { Authority, DeviceInfo } from '@contract';

interface AuthorityPanelProps {
  authority?: Authority | null;
  deviceA?: DeviceInfo;
  deviceB?: DeviceInfo;
}

/** Exactly one lease: it sits with the device allowed to run the workload and slides across at cutover. */
export function AuthorityPanel({ authority, deviceA, deviceB }: AuthorityPanelProps) {
  const state = authority?.state ?? 'SOURCE';
  const epoch = authority?.epoch ?? 1;
  const isSource = state === 'SOURCE';
  const isFenced = state === 'FENCED';
  const isTarget = state === 'TARGET';
  const position = isTarget ? 'calc(100% - 2.75rem)' : isFenced ? 'calc(50% - 1.375rem)' : '0rem';

  return (
    <div className="tp-card p-6">
      <div className="flex items-baseline justify-between">
        <p className="tp-label">Authority</p>
        <span data-testid="authority-epoch" className="font-mono text-xs text-muted">
          Epoch {epoch}
        </span>
      </div>

      <div className="relative mt-5 h-11">
        <div className="absolute top-1/2 right-5 left-5 h-px -translate-y-1/2 bg-line" />
        <div
          className={`absolute top-0 flex h-11 w-11 items-center justify-center rounded-full border font-mono text-[11px] transition-[left] duration-700 ease-in-out ${
            isFenced ? 'border-warn bg-warn-soft text-warn' : 'border-ink bg-ink text-canvas'
          }`}
          style={{ left: position }}
          title="The lease: only its holder may run the workload"
        >
          e{epoch}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
        <div data-testid="authority-node-a">
          <p className="text-ink">{deviceA?.name ?? 'Device A (Host)'}</p>
          <p className="mt-0.5 text-xs text-muted">
            <span
              data-testid="authority-state-source"
              className={`font-mono ${isSource ? 'text-ink' : isFenced ? 'text-warn' : 'text-faint'}`}
            >
              {isFenced ? 'FENCED' : isSource ? 'SOURCE' : 'RELEASED'}
            </span>
            {' · '}
            {isSource ? 'running here' : isFenced ? 'paused for cutover' : 'stopped, never runs again'}
          </p>
        </div>
        <div data-testid="authority-node-b" className="text-right">
          <p className="text-ink">{deviceB?.name ?? 'Device B (Target)'}</p>
          <p className="mt-0.5 text-xs text-muted">
            {isTarget ? 'running here' : 'waiting for the lease'}
            {' · '}
            <span data-testid="authority-state-target" className={`font-mono ${isTarget ? 'text-ok' : 'text-faint'}`}>
              {isTarget ? 'TARGET' : 'STANDBY'}
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}
