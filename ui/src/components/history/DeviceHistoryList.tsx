import type { DeviceInfo } from '@contract';
import type { DeviceHistoryItem } from '../../mock/mockHistory.ts';
import { formatBytes } from '../../utils/formatters.ts';

interface DeviceHistoryListProps {
  devices: DeviceHistoryItem[];
  selectedDeviceId: string | null;
  onSelectDevice: (deviceId: string | null) => void;
  onReconnect: (device: DeviceInfo) => void;
}

export function DeviceHistoryList({
  devices,
  selectedDeviceId,
  onSelectDevice,
  onReconnect,
}: DeviceHistoryListProps) {
  const formatTime = (ts: number) => {
    return new Date(ts).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-3 dark:border-slate-800">
        <div>
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            Known Peer Devices ({devices.length})
          </h2>
          <p className="text-xs text-slate-500">
            Historical registry of paired compute devices, hardware specs and migration counts
          </p>
        </div>
        {selectedDeviceId && (
          <button
            type="button"
            data-testid="btn-clear-device-filter"
            onClick={() => onSelectDevice(null)}
            className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            Show All Devices
          </button>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {devices.map((item) => {
          const isSelected = selectedDeviceId === item.device.id;
          const dev = item.device;

          return (
            <div
              key={dev.id}
              data-testid={`history-device-${dev.id}`}
              onClick={() => onSelectDevice(isSelected ? null : dev.id)}
              className={`flex cursor-pointer flex-col justify-between rounded-xl border p-4 transition-all duration-200 ${
                isSelected
                  ? 'border-blue-500 bg-blue-50/50 shadow-md ring-2 ring-blue-500/20 dark:border-blue-500 dark:bg-blue-950/30'
                  : 'border-slate-200 bg-slate-50/40 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/30 dark:hover:border-slate-700'
              }`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] uppercase font-bold text-slate-400">
                    {dev.os} · {dev.arch}
                  </span>
                  <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                    {item.migrationCount} {item.migrationCount === 1 ? 'migration' : 'migrations'}
                  </span>
                </div>

                <h3 className="mt-2 text-sm font-bold text-slate-900 dark:text-white line-clamp-1">
                  {dev.name}
                </h3>
                <p className="font-mono text-[11px] text-slate-400">
                  {dev.id}
                </p>

                <div className="mt-3 space-y-1 text-[11px] text-slate-600 dark:text-slate-300">
                  <div>
                    <span className="text-slate-400">Compute: </span>
                    <span className="font-semibold">{dev.cpuCores} cores</span> ·{' '}
                    <span className="font-semibold">{formatBytes(dev.ramMb * 1024 * 1024)} RAM</span>
                  </div>
                  {dev.gpu && (
                    <div className="line-clamp-1">
                      <span className="text-slate-400">GPU: </span>
                      <span className="font-medium">{dev.gpu}</span>
                    </div>
                  )}
                  <div className="flex items-center justify-between text-[10px] text-slate-500 dark:text-slate-400 pt-0.5">
                    <span>First: {formatTime(item.firstSeen)}</span>
                    <span>Last: {formatTime(item.lastSeen)}</span>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
                <span className="text-[10px] text-slate-400">
                  {isSelected ? 'Filtering migrations' : 'Click to filter'}
                </span>
                <button
                  type="button"
                  data-testid={`btn-reconnect-${dev.id}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onReconnect(dev);
                  }}
                  className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-bold text-white shadow-xs hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600"
                >
                  Reconnect
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
