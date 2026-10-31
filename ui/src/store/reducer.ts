import type { BusEvent, DeviceInfo, Stats } from '@contract';
import type { MetricHistoryPoint, StoreAction, TeleportState, WorkloadItem } from './types.ts';

export function createInitialState(): TeleportState {
  const savedTheme = typeof window !== 'undefined' ? (localStorage.getItem('teleport_theme') as 'dark' | 'light' | null) : null;
  return {
    thisDeviceId: 'device-a',
    peerDeviceId: 'device-b',
    devices: {},
    stats: {},
    history60s: {},
    link: null,
    workloads: [],
    recommendation: null,
    migrationStatus: null,
    authority: null,
    remoteSession: null,
    wsConnected: false,
    agentReachable: false,
    mockFeederActive: true, // Default to true when unconfigured/offline
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
      const { devices, stats, workloads } = action.payload;
      const deviceMap: Record<string, DeviceInfo> = { ...state.devices };
      let thisDev = state.thisDeviceId;
      let peerDev = state.peerDeviceId;

      devices.forEach((d, idx) => {
        deviceMap[d.id] = d;
        if (idx === 0 && (!thisDev || !deviceMap[thisDev])) {
          thisDev = d.id;
        } else if (idx === 1 && !peerDev) {
          peerDev = d.id;
        }
      });

      const statsMap: Record<string, Stats> = { ...state.stats };
      let historyMap = { ...state.history60s };
      stats.forEach((s) => {
        statsMap[s.deviceId] = s;
        historyMap = appendHistory(historyMap, s.deviceId, s);
      });

      const nextWorkloads: WorkloadItem[] = workloads ?? state.workloads;

      const nextState: TeleportState = {
        ...state,
        thisDeviceId: thisDev,
        peerDeviceId: peerDev,
        devices: deviceMap,
        stats: statsMap,
        history60s: historyMap,
        workloads: nextWorkloads,
        agentReachable: true,
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
      const next: TeleportState = { ...state, mockFeederActive: action.payload };
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

    case 'decision.logged':
      return state;

    default:
      return state;
  }
}

