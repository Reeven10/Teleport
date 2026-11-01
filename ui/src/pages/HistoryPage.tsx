import { PageHeader } from '../components/ui/Icon.tsx';
import { useEffect, useState } from 'react';
import type { DecisionLog, DeviceInfo, MigrationStatus } from '@contract';
import {
  apiResetDevices,
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
import { ForgetDevicesDialog } from '../components/history/ForgetDevicesDialog.tsx';
import { useTeleport } from '../store/useTeleport.ts';

export function HistoryPage() {
  const { state } = useTeleport();
  // Sample history only without a live agent (or with ?mock=1): a real agent's history is shown as it
  // is, even when empty, so forgotten devices never come back as sample ones.
  const sample =
    !state.agentReachable ||
    state.mockFeederActive ||
    (typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('mock'));
  const [deviceItems, setDeviceItems] = useState<DeviceHistoryItem[]>(sample ? MOCK_HISTORY_DEVICES : []);
  const [migrations, setMigrations] = useState<MigrationStatus[]>(sample ? MOCK_HISTORY_MIGRATIONS : []);
  const [decisions, setDecisions] = useState<DecisionLog[]>(sample ? MOCK_HISTORY_DECISIONS : []);

  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [inspectingMigration, setInspectingMigration] = useState<MigrationStatus | null>(null);

  // Reconnect dialog state
  const [pairModalOpen, setPairModalOpen] = useState(false);
  const [pairInitialAddr, setPairInitialAddr] = useState('');

  // Load history from API or fallback to mock
  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      if (sample) {
        setDeviceItems(MOCK_HISTORY_DEVICES);
        setMigrations(MOCK_HISTORY_MIGRATIONS);
        setDecisions(MOCK_HISTORY_DECISIONS);
        return;
      }
      if (state.agentReachable) {
        try {
          const [apiDevs, apiMigs, apiDecs] = await Promise.all([
            apiGetHistoryDevices().catch(() => []),
            apiGetHistoryMigrations().catch(() => []),
            apiGetHistoryDecisions().catch(() => []),
          ]);

          if (cancelled) return;

          setMigrations(apiMigs);
          setDecisions(apiDecs);
          setDeviceItems(
            apiDevs.map((s) => ({
              device: s.device,
              firstSeen: s.firstSeen,
              lastSeen: s.lastSeen,
              migrationCount: s.migrationCount,
            })),
          );
        } catch {
          // Keep mock history on failure
        }
      }
    }

    loadData();

    return () => {
      cancelled = true;
    };
  }, [state.agentReachable, sample]);

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
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex-1">
          <PageHeader eyebrow="History" title="Every move, with its reasons" description="Past devices, each migration step by step, and the evidence behind every decision." />
        </div>

        <div className="flex items-center gap-2">
          <span className="rounded-full bg-raised px-3 py-1 font-mono text-[11px] font-semibold text-muted">
            {migrations.length} Migrations Logged
          </span>
          <span className="rounded-full bg-raised px-3 py-1 font-mono text-[11px] font-semibold text-muted">
            {decisions.length} Decisions Logged
          </span>
          <ForgetDevicesDialog onReset={apiResetDevices} />
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
