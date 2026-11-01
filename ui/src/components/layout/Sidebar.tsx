import { NavLink } from 'react-router-dom';
import { useTeleport } from '../../store/useTeleport.ts';
import { Icon, LiveDot, type IconName } from '../ui/Icon.tsx';

const NAV_ITEMS: { name: string; path: string; icon: IconName }[] = [
  { name: 'Dashboard', path: '/', icon: 'overview' },
  { name: 'Workloads', path: '/workloads', icon: 'workloads' },
  { name: 'Migration', path: '/migration', icon: 'migrate' },
  { name: 'Remote', path: '/remote', icon: 'remote' },
  { name: 'History', path: '/history', icon: 'history' },
  { name: 'Settings', path: '/settings', icon: 'settings' },
];

/** The Teleport mark: two points and the arc between them. */
export function TeleportMark({ className = 'h-6 w-6' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 17C7 8.5 17 8.5 19 17" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeDasharray="1.5 2.5" />
      <circle cx="5" cy="17" r="2.25" fill="currentColor" />
      <circle cx="19" cy="17" r="2.25" className="fill-accent" />
    </svg>
  );
}

export function Sidebar() {
  const { state, toggleTheme, toggleMockFeeder } = useTeleport();
  const me = state.devices[state.thisDeviceId];
  const live = state.wsConnected;
  const migrating = Boolean(
    state.migrationStatus && !['IDLE', 'COMPLETED', 'ROLLED_BACK', 'FAILED'].includes(state.migrationStatus.phase),
  );

  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface md:flex">
      <div className="flex items-center gap-2.5 px-5 pt-6 pb-7">
        <TeleportMark className="h-7 w-7 text-ink" />
        <span className="font-serif text-[1.6rem] leading-none tracking-tight text-ink">Teleport</span>
      </div>

      <nav className="flex-1 space-y-0.5 px-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors ${
                isActive ? 'bg-raised font-medium text-ink' : 'text-muted hover:bg-raised/60 hover:text-ink'
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && <span className="absolute top-2 bottom-2 left-0 w-0.5 rounded-full bg-accent" />}
                <Icon name={item.icon} className={`h-[18px] w-[18px] ${isActive ? 'text-ink' : 'text-faint group-hover:text-muted'}`} />
                <span>{item.name}</span>
                {item.path === '/migration' && migrating && (
                  <span className="ml-auto">
                    <LiveDot tone="accent" />
                  </span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="space-y-3 border-t border-line p-4">
        <div className="rounded-xl bg-raised px-3 py-2.5">
          <div className="flex items-center gap-2">
            <LiveDot tone={live ? 'ok' : state.mockFeederActive ? 'warn' : 'bad'} live={live} />
            <span className="truncate text-xs font-medium text-ink">{me?.name ?? 'This device'}</span>
          </div>
          <p className="mt-1 pl-4 font-mono text-[10.5px] text-faint">
            {live ? 'agent connected' : state.mockFeederActive ? 'demo data' : 'agent offline'}
          </p>
        </div>
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => toggleMockFeeder()}
            title="Show recorded demo data instead of the live agent"
            className={`rounded-md px-2 py-1 text-[11px] transition-colors ${
              state.mockFeederActive ? 'bg-warn-soft text-warn' : 'text-faint hover:text-muted'
            }`}
          >
            {state.mockFeederActive ? 'Demo data on' : 'Demo data'}
          </button>
          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle Theme"
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-raised hover:text-ink"
          >
            <Icon name={state.theme === 'dark' ? 'sun' : 'moon'} />
          </button>
        </div>
      </div>
    </aside>
  );
}
