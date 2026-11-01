import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  type ReactNode,
} from 'react';
import type { BusEvent, DeviceInfo } from '@contract';
import {
  apiFetchDevices,
  apiFetchHealth,
  apiFetchMigrations,
  apiFetchRemoteSessions,
  apiFetchStats,
  apiFetchWorkloadRuns,
  apiFetchWorkloads,
  connectEvents,
} from '../api.ts';
import {
  MOCK_DEVICE_A,
  MOCK_DEVICE_B,
  MOCK_WORKLOAD,
  MockFeeder,
  generateInitialHistory,
} from '../mock/mockFeeder.ts';
import { createInitialState, storeReducer } from './reducer.ts';
import type { WorkloadItem } from './types.ts';
import { TeleportContext, type TeleportContextValue } from './useTeleport.ts';

export function TeleportProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(storeReducer, undefined, createInitialState);
  const mockFeederRef = useRef<MockFeeder | null>(null);

  // Sync dark class on document element
  useEffect(() => {
    if (state.theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [state.theme]);

  // Handle Mock Feeder lifecycle
  useEffect(() => {
    if (state.mockFeederActive) {
      if (!mockFeederRef.current) {
        mockFeederRef.current = new MockFeeder((event: BusEvent) => {
          dispatch({ type: 'BUS_EVENT', payload: event });
        });
      }

      // Seed initial state for mock devices & history if missing
      dispatch({
        type: 'INIT_REST',
        payload: {
          devices: [MOCK_DEVICE_A, MOCK_DEVICE_B],
          stats: [],
          workloads: [MOCK_WORKLOAD],
        },
      });

      const histA = generateInitialHistory(45, 68, 122880);
      histA.forEach((pt) => {
        dispatch({
          type: 'BUS_EVENT',
          payload: {
            t: 'stats.update',
            stats: {
              deviceId: 'device-a',
              ts: pt.ts,
              cpuPct: pt.cpuPct,
              memPct: pt.memPct,
              memFreeMb: 5240,
              diskFreeMb: pt.diskFreeMb,
              battery: { pct: 38, charging: false },
              online: true,
              simulated: true,
            },
          },
        });
      });

      const histB = generateInitialHistory(18, 41, 512000);
      histB.forEach((pt) => {
        dispatch({
          type: 'BUS_EVENT',
          payload: {
            t: 'stats.update',
            stats: {
              deviceId: 'device-b',
              ts: pt.ts,
              cpuPct: pt.cpuPct,
              memPct: pt.memPct,
              memFreeMb: 19320,
              diskFreeMb: pt.diskFreeMb,
              battery: null,
              online: true,
              simulated: true,
            },
          },
        });
      });

      mockFeederRef.current.start(1000);
    } else {
      mockFeederRef.current?.stop();
    }

    return () => {
      mockFeederRef.current?.stop();
    };
  }, [state.mockFeederActive]);

  // REST initialization & WebSocket connection
  useEffect(() => {
    let unmounted = false;
    let everReachable = false;

    async function initRest() {
      try {
        const health = await apiFetchHealth();
        const [devices, stats, workloads, migrations, workloadRuns, remoteSessions] =
          await Promise.all([
            apiFetchDevices().catch(() => []),
            apiFetchStats().catch(() => []),
            apiFetchWorkloads().catch(() => []),
            apiFetchMigrations().catch(() => []),
            apiFetchWorkloadRuns().catch(() => []),
            apiFetchRemoteSessions().catch(() => []),
          ]);

        if (!unmounted && health.ok) {
          everReachable = true;
          dispatch({
            type: 'INIT_REST',
            payload: {
              thisDeviceId: health.deviceId,
              devices,
              stats,
              workloads,
              migrations,
              workloadRuns,
              remoteSessions,
            },
          });
          dispatch({ type: 'SET_AGENT_REACHABLE', payload: true });
        }
      } catch {
        // Agent never reached: offline mock mode. Once it was reachable, a failure is just a blip.
        if (!unmounted && !everReachable) {
          dispatch({ type: 'SET_AGENT_REACHABLE', payload: false });
          dispatch({ type: 'TOGGLE_MOCK_FEEDER', payload: true });
        }
      }
    }

    initRest();

    const disconnectWs = connectEvents(
      (event: BusEvent) => {
        if (!unmounted) {
          dispatch({ type: 'BUS_EVENT', payload: event });
        }
      },
      (connected: boolean) => {
        if (unmounted) return;
        dispatch({ type: 'SET_WS_CONNECTED', payload: connected });
        if (connected && everReachable) {
          initRest(); // (re)connected: reload the real state, events may have been missed meanwhile
        } else if (!connected && !everReachable) {
          dispatch({ type: 'TOGGLE_MOCK_FEEDER', payload: true });
        }
      },
    );

    // Safety net for "steps not updating": while a migration runs, also poll its status.
    const poll = window.setInterval(async () => {
      if (unmounted || !everReachable) return;
      try {
        const [workloads, runs] = await Promise.all([apiFetchWorkloads(), apiFetchWorkloadRuns()]);
        dispatch({ type: 'SET_WORKLOADS', payload: { workloads, runs } });
        const migrations = await apiFetchMigrations();
        const live = migrations.filter((m) => !['COMPLETED', 'ROLLED_BACK', 'REMOTE_ACCESS', 'FAILED'].includes(m.phase));
        for (const m of live.length ? live : migrations.slice(-1)) {
          dispatch({ type: 'BUS_EVENT', payload: { t: 'migration.status', status: m } });
        }
      } catch {
        /* agent briefly unreachable: the WebSocket reconnect reloads everything */
      }
    }, 1500);

    return () => {
      unmounted = true;
      window.clearInterval(poll);
      disconnectWs();
    };
  }, []);

  const toggleTheme = useCallback(() => {
    dispatch({ type: 'SET_THEME', payload: state.theme === 'dark' ? 'light' : 'dark' });
  }, [state.theme]);

  const toggleMockFeeder = useCallback(
    (enable?: boolean) => {
      dispatch({ type: 'TOGGLE_MOCK_FEEDER', payload: enable ?? !state.mockFeederActive });
    },
    [state.mockFeederActive],
  );

  const selectPeer = useCallback((peerId: string) => {
    dispatch({ type: 'SELECT_PEER', payload: peerId });
  }, []);

  const addPairedDevice = useCallback((device: DeviceInfo) => {
    dispatch({ type: 'ADD_PAIRED_DEVICE', payload: device });
  }, []);

  const addWorkload = useCallback((item: WorkloadItem) => {
    dispatch({ type: 'ADD_WORKLOAD', payload: item });
  }, []);

  const setSimulationScenario = useCallback((scenario: import('../mock/mockFeeder.ts').MockScenario) => {
    if (mockFeederRef.current) {
      mockFeederRef.current.setScenario(scenario);
    }
  }, []);

  const clearRecommendation = useCallback(() => {
    dispatch({ type: 'CLEAR_RECOMMENDATION' });
  }, []);

  const value: TeleportContextValue = {
    state,
    dispatch,
    toggleTheme,
    toggleMockFeeder,
    setSimulationScenario,
    clearRecommendation,
    selectPeer,
    addPairedDevice,
    addWorkload,
  };

  return <TeleportContext.Provider value={value}>{children}</TeleportContext.Provider>;
}
