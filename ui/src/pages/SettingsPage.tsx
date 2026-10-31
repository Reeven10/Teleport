import { useTeleport } from '../store/useTeleport.ts';

export function SettingsPage() {
  const { state, toggleTheme, toggleMockFeeder } = useTeleport();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
          Teleport Agent Settings
        </h1>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Agent operational policies, orchestration thresholds and simulation controls
        </p>
      </div>

      <div className="space-y-4">
        {/* Simulation Controls Card */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-base font-bold text-slate-900 dark:text-white">Developer & Simulation Feeder</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Control the live event playback feeder for testing UI components and control room displays without live peer hardware.
          </p>

          <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4 dark:border-slate-800">
            <div>
              <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">Mock BusEvent Feeder</span>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                Simulates battery drain, CPU oscillations, link transitions (cable to wifi), and 6-checkpoint cutover sequence.
              </p>
            </div>
            <button
              onClick={() => toggleMockFeeder()}
              className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all ${
                state.mockFeederActive
                  ? 'bg-amber-500 text-white shadow-xs hover:bg-amber-600'
                  : 'bg-slate-200 text-slate-700 hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-300'
              }`}
            >
              {state.mockFeederActive ? 'Feeder Enabled' : 'Feeder Disabled'}
            </button>
          </div>
        </div>

        {/* Display & Visual Theme Card */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-base font-bold text-slate-900 dark:text-white">Theme & Appearance</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Control room high-contrast themes optimized for readability across both desktop screens and projection displays.
          </p>

          <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4 dark:border-slate-800">
            <div>
              <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">Theme Mode</span>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                Current mode: <span className="font-semibold capitalize">{state.theme}</span>
              </p>
            </div>
            <button
              onClick={toggleTheme}
              className="rounded-lg border border-slate-300 px-3.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Switch to {state.theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
