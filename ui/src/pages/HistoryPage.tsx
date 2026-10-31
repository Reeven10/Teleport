import { useEffect, useState } from 'react';
import type { DecisionLog, DeviceInfo, MigrationStatus } from '@contract';
import {
  apiGetHistoryDecisions,
  apiGetHistoryDevices,
  apiGetHistoryMigrations,
  apiGetHistoryMigration,
} from '../api.ts';
import {
  MOCK_HISTORY_DECISIONS,
  MOCK_HISTORY_DEVICES,
  MOCK_HISTORY_MIGRATIONS,
  type DeviceHistoryItem,
} from '../mock/mockHistory.ts';
import { DeviceHistoryList } from '../components/history/DeviceHistoryList.tsx';
import { MigrationTable } from '../components/history/MigrationTable.tsx';
import { MigrationDetailModal } from '../components/history/MigrationDetailModal.tsx';
import { DecisionLogPanel } from '../components/history/DecisionLogPanel.tsx';
import { PairDialog } from '../components/pairing/PairDialog.tsx';
import { useTeleport } from '../store/useTeleport.ts';

export function HistoryPage() {
  const { state } = useTeleport();
  const [deviceItems, setDeviceItems] = useState<DeviceHistoryItem[]>(MOCK_HISTORY_DEVICES);
  const [migrations, setMigrations] = useState<MigrationStatus[]>(MOCK_HISTORY_MIGRATIONS);
  const [decisions, setDecisions] = useState<DecisionLog[]>(MOCK_HISTORY_DECISIONS);

  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [inspectingMigration, setInspectingMigration] = useState<MigrationStatus | null>(null);

  // Reconnect dialog state
  const [pairModalOpen, setPairModalOpen] = useState(false);
  const [pairInitialAddr, setPairInitialAddr] = useState('');

  // Load history from API or fallback to mock
  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      if (state.agentReachable) {
        try {
          const [apiDevs, apiMigs, apiDecs] = await Promise.all([
            apiGetHistoryDevices().catch(() => []),
            apiGetHistoryMigrations().catch(() => []),
            apiGetHistoryDecisions().catch(() => []),
          ]);

          if (cancelled) return;

          if (apiMigs.length > 0) {
            setMigrations(apiMigs);
          }

          if (apiDecs.length > 0) {
            setDecisions(apiDecs);
          }

          if (apiDevs.length > 0) {
            const devItems: DeviceHistoryItem[] = apiDevs.map((s) => ({
              device: s.device,
              firstSeen: s.firstSeen,
              lastSeen: s.lastSeen,
              migrationCount: s.migrationCount,
            }));
            setDeviceItems(devItems);
          }
        } catch {
          // Keep mock history on failure
        }
      }
    }

    loadData();

    return () => {
      cancelled = true;
    };
  }, [state.agentReachable]);

  const handleSelectMigration = async (mig: MigrationStatus) => {
    try {
      if (state.agentReachable) {
        const full = await apiGetHistoryMigration(mig.id);
        if (full) {
          setInspectingMigration(full);
          return;
        }
      }
    } catch {
      // Fallback to table status
    }
    setInspectingMigration(mig);
  };

  const handleReconnect = (device: DeviceInfo) => {
    const addr = device.addrs[0]?.addr || `${device.id}:8765`;
    setPairInitialAddr(addr);
    setPairModalOpen(true);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
            Migration & Audit History
          </h1>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Historical registry of past devices, step-by-step migration post-mortems, and decision evidence
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="rounded-full bg-slate-100 px-3 py-1 font-mono text-[11px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {migrations.length} Migrations Logged
          </span>
          <span className="rounded-full bg-indigo-50 px-3 py-1 font-mono text-[11px] font-semibold text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
            {decisions.length} Decisions Logged
          </span>
        </div>
      </div>

      {/* 1. Device List with Last Known Specs & Reconnect */}
      <DeviceHistoryList
        devices={deviceItems}
        selectedDeviceId={selectedDeviceId}
        onSelectDevice={setSelectedDeviceId}
        onReconnect={handleReconnect}
      />

      {/* 2. Migration Table with Filters & Click to Detail */}
      <MigrationTable
        migrations={migrations}
        onSelectMigration={handleSelectMigration}
        selectedDeviceId={selectedDeviceId}
        onClearDeviceFilter={() => setSelectedDeviceId(null)}
      />

      {/* 3. Decision Log Panel (including Remote Access & STAY decisions) */}
      <DecisionLogPanel decisions={decisions} />

      {/* Detail Modal Replay View */}
      <MigrationDetailModal
        migration={inspectingMigration}
        onClose={() => setInspectingMigration(null)}
      />

      {/* Reconnect Pairing Modal */}
      {pairModalOpen && (
        <PairDialog
          isOpen={pairModalOpen}
          initialAddress={pairInitialAddr}
          onClose={() => setPairModalOpen(false)}
        />
      )}
    </div>
  );
}
