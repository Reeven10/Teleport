import type { BusEvent, DeviceInfo, MigrationStatus, RemoteSession, Stats } from '@contract';
import type { MetricHistoryPoint, StoreAction, TeleportState, WorkloadItem } from './types.ts';

export function createInitialState(): TeleportState {
  const savedTheme = typeof window !== 'undefined' ? (localStorage.getItem('teleport_theme') as 'dark' | 'light' | null) : null;
  return {
    thisDeviceId: '',
    peerDeviceId: null,
    devices: {},
    stats: {},
    history60s: {},
    link: null,
    workloads: [],
    recommendation: null,
    migrationStatus: null,
    authority: null,
    remoteSession: null,
    authorityConflict: null,
    wsConnected: false,
    agentReachable: false,
    mockFeederActive: true,
    theme: savedTheme ?? 'dark',
    isSimulated: true,
  };
}

function checkSimulated(state: TeleportState): boolean {
  if (state.mockFeederActive) return true;
  for (const s of Object.values(state.stats)) {
    if (s.simulated) return true;
  }
  for (const d of Object.values(state.devices)) {
    if (d.simulated) return true;
  }
  return false;
}

function appendHistory(
  existingHistory: Record<string, MetricHistoryPoint[]>,
  deviceId: string,
  stats: Stats,
): Record<string, MetricHistoryPoint[]> {
  const current = existingHistory[deviceId] ?? [];
  const nextPoint: MetricHistoryPoint = {
    ts: stats.ts,
    cpuPct: Math.round(stats.cpuPct),
    memPct: Math.round(stats.memPct),
    diskFreeMb: Math.round(stats.diskFreeMb),
  };
  const updated = [...current, nextPoint].slice(-60);
  return {
    ...existingHistory,
    [deviceId]: updated,
  };
}

export function storeReducer(state: TeleportState, action: StoreAction): TeleportState {
  switch (action.type) {
    case 'INIT_REST': {
      const { thisDeviceId, devices, stats, workloads, migrations, workloadRuns, remoteSessions } = action.payload;
      const deviceMap: Record<string, DeviceInfo> = {};
      let thisDev = thisDeviceId || state.thisDeviceId;

      devices.forEach((d) => {
        deviceMap[d.id] = d;
      });

      const firstDev = devices[0];
      if (!thisDev && firstDev) {
        thisDev = firstDev.id;
      }

      // First peer device that is not thisDeviceId
      let peerDev = state.peerDeviceId;
      if (!peerDev || peerDev === thisDev || !deviceMap[peerDev]) {
        const peer = devices.find((d) => d.id !== thisDev);
        peerDev = peer ? peer.id : null;
      }

      const statsMap: Record<string, Stats> = {};
      let historyMap = { ...state.history60s };
      stats.forEach((s) => {
        statsMap[s.deviceId] = s;
        historyMap = appendHistory(historyMap, s.deviceId, s);
      });

      // Map workload runs
      let nextWorkloads: WorkloadItem[] = workloads ?? state.workloads;
      if (workloadRuns && workloadRuns.length > 0) {
        const runMap = new Map(workloadRuns.map((r) => [r.workloadId, r]));
        nextWorkloads = nextWorkloads.map((w) => {
          const run = runMap.get(w.manifest.id);
          if (run) {
            return {
              ...w,
              status: run.state === 'running' ? 'RUNNING' : 'STOPPED',
            };
          }
          return w;
        });
      }

      // Check latest migration and authority (P4-6)
      let nextMig: MigrationStatus | null = state.migrationStatus;
      let nextAuth = state.authority;
      if (migrations && migrations.length > 0) {
        const sorted = [...migrations].sort((a, b) => b.startedAt - a.startedAt);
        const latest = sorted[0];
        if (latest) {
          nextMig = latest;
          if (latest.authority) {
            nextAuth = latest.authority;
          }
        }
      }

      // Check remote sessions
      let nextRemote: RemoteSession | null = state.remoteSession;
      if (remoteSessions && remoteSessions.length > 0) {
        nextRemote = remoteSessions[remoteSessions.length - 1] ?? null;
      }

      const nextState: TeleportState = {
        ...state,
        thisDeviceId: thisDev,
        peerDeviceId: peerDev,
        devices: deviceMap,
        stats: statsMap,
        history60s: historyMap,
        workloads: nextWorkloads,
        migrationStatus: nextMig,
        authority: nextAuth,
        remoteSession: nextRemote,
        agentReachable: true,
        mockFeederActive: action.payload.thisDeviceId ? false : state.mockFeederActive,
      };
      nextState.isSimulated = checkSimulated(nextState);
      return nextState;
    }

    case 'BUS_EVENT': {
      return handleBusEvent(state, action.payload);
    }

    case 'SET_WS_CONNECTED': {
      const next: TeleportState = { ...state, wsConnected: action.payload };
      if (action.payload) {
        next.agentReachable = true;
      }
      next.isSimulated = checkSimulated(next);
      return next;
    }

    case 'SET_AGENT_REACHABLE': {
      const next: TeleportState = { ...state, agentReachable: action.payload };
      next.isSimulated = checkSimulated(next);
      return next;
    }

    case 'TOGGLE_MOCK_FEEDER': {
      if (!action.payload) {
        // Filter out simulated devices, stats, and history when feeder is toggled off
        const realDevices = Object.fromEntries(
          Object.entries(state.devices).filter(([, d]) => !d.simulated)
        );
        const realStats = Object.fromEntries(
          Object.entries(state.stats).filter(([, s]) => !s.simulated)
        );
        const realDevIds = Object.keys(realDevices);
        const thisDev = realDevIds[0] ?? '';
        const peerDev = realDevIds[1] ?? null;

        const next: TeleportState = {
          ...state,
          mockFeederActive: false,
          devices: realDevices,
          stats: realStats,
          thisDeviceId: thisDev,
          peerDeviceId: peerDev,
          migrationStatus: state.migrationStatus?.sourceId.startsWith('device-') ? null : state.migrationStatus,
          recommendation: state.recommendation?.targetId?.startsWith('device-') ? null : state.recommendation,
        };
        next.isSimulated = checkSimulated(next);
        return next;
      }
      const next: TeleportState = { ...state, mockFeederActive: true };
      next.isSimulated = checkSimulated(next);
      return next;
    }

    case 'SET_THEME': {
      if (typeof window !== 'undefined') {
        localStorage.setItem('teleport_theme', action.payload);
      }
      return { ...state, theme: action.payload };
    }

    case 'SELECT_PEER': {
      return { ...state, peerDeviceId: action.payload };
    }

    case 'ADD_PAIRED_DEVICE': {
      const d = action.payload;
      const deviceMap = { ...state.devices, [d.id]: d };
      const next: TeleportState = {
        ...state,
        devices: deviceMap,
        peerDeviceId: state.peerDeviceId ?? d.id,
      };
      next.isSimulated = checkSimulated(next);
      return next;
    }

    case 'ADD_WORKLOAD': {
      return {
        ...state,
        workloads: [...state.workloads.filter((w) => w.manifest.id !== action.payload.manifest.id), action.payload],
      };
    }

    case 'CLEAR_RECOMMENDATION': {
      return { ...state, recommendation: null };
    }

    default:
      return state;
  }
}

function handleBusEvent(state: TeleportState, event: BusEvent): TeleportState {
  switch (event.t) {
    case 'stats.update': {
      const stats = event.stats;
      const nextStats = { ...state.stats, [stats.deviceId]: stats };
      const nextHistory = appendHistory(state.history60s, stats.deviceId, stats);
      const nextState: TeleportState = {
        ...state,
        stats: nextStats,
        history60s: nextHistory,
      };
      nextState.isSimulated = checkSimulated(nextState);
      return nextState;
    }

    case 'link.update': {
      return { ...state, link: event.link };
    }

    case 'device.paired': {
      const d = event.device;
      const deviceMap = { ...state.devices, [d.id]: d };
      const nextState: TeleportState = {
        ...state,
        devices: deviceMap,
        peerDeviceId: state.peerDeviceId ?? d.id,
      };
      nextState.isSimulated = checkSimulated(nextState);
      return nextState;
    }

    case 'device.lost': {
      const devId = event.deviceId;
      const existing = state.stats[devId];
      if (existing) {
        const updatedStats = {
          ...state.stats,
          [devId]: { ...existing, online: false },
        };
        return { ...state, stats: updatedStats };
      }
      return state;
    }

    case 'recommendation': {
      return { ...state, recommendation: event.rec };
    }

    case 'migration.status': {
      return { ...state, migrationStatus: event.status };
    }

    case 'authority.change': {
      return { ...state, authority: event.authority };
    }

    case 'remote.session': {
      return { ...state, remoteSession: event.session };
    }

    case 'authority.conflict': {
      return { ...state, authorityConflict: event.conflict };
    }

    case 'decision.logged':
      return state;

    default:
      return state;
  }
}

