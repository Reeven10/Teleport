import { describe, expect, it } from 'vitest';
import type { BusEvent, DeviceInfo, LinkQuality, Stats } from '@contract';
import { createInitialState, storeReducer } from '@/store/reducer.ts';

describe('storeReducer', () => {
  it('creates clean initial state with defaults', () => {
    const state = createInitialState();
    expect(state.thisDeviceId).toBe('');
    expect(state.peerDeviceId).toBeNull();
    expect(state.mockFeederActive).toBe(true);
    expect(state.isSimulated).toBe(true);
  });

  it('handles INIT_REST and sets devices and stats', () => {
    const initialState = createInitialState();
    const mockDev: DeviceInfo = {
      id: 'dev-1',
      name: 'Test Device 1',
      os: 'macos',
      arch: 'arm64',
      cpuCores: 8,
      ramMb: 8192,
      gpu: null,
      diskFreeMb: 100000,
      runtimes: { python: '3.11' },
      libs: [],
      addrs: [{ addr: '127.0.0.1:8765', link: 'cable' }],
      agentVersion: '0.1.0',
    };
    const mockStat: Stats = {
      deviceId: 'dev-1',
      ts: 1000,
      cpuPct: 25,
      memPct: 50,
      memFreeMb: 4096,
      diskFreeMb: 100000,
      battery: { pct: 80, charging: false },
      online: true,
    };

    const next = storeReducer(initialState, {
      type: 'INIT_REST',
      payload: { devices: [mockDev], stats: [mockStat] },
    });

    expect(next.devices['dev-1']).toEqual(mockDev);
    expect(next.stats['dev-1']).toEqual(mockStat);
    expect(next.history60s['dev-1']?.length).toBe(1);
    expect(next.agentReachable).toBe(true);
  });

  it('updates stats and caps sliding history at 60 points', () => {
    let state = createInitialState();

    for (let i = 0; i < 75; i++) {
      const statsUpdate: BusEvent = {
        t: 'stats.update',
        stats: {
          deviceId: 'device-a',
          ts: 1000 + i * 1000,
          cpuPct: i % 100,
          memPct: 50,
          memFreeMb: 4000,
          diskFreeMb: 50000,
          battery: { pct: 90, charging: false },
          online: true,
        },
      };

      state = storeReducer(state, { type: 'BUS_EVENT', payload: statsUpdate });
    }

    expect(state.stats['device-a']?.cpuPct).toBe(74);
    expect(state.history60s['device-a']?.length).toBe(60);
    expect(state.history60s['device-a']?.[59]?.cpuPct).toBe(74);
  });

  it('handles link.update event', () => {
    const state = createInitialState();
    const link: LinkQuality = {
      peerId: 'device-b',
      link: 'cable',
      rttMs: 1.2,
      mbps: 1000,
      lossPct: 0.0,
      ts: 2000,
    };

    const next = storeReducer(state, {
      type: 'BUS_EVENT',
      payload: { t: 'link.update', link },
    });

    expect(next.link).toEqual(link);
  });

  it('handles device.paired and device.lost events', () => {
    let state = createInitialState();
    const dev: DeviceInfo = {
      id: 'dev-x',
      name: 'Peer X',
      os: 'linux',
      arch: 'x86_64',
      cpuCores: 16,
      ramMb: 32768,
      gpu: 'RTX 4090',
      diskFreeMb: 500000,
      runtimes: {},
      libs: [],
      addrs: [],
      agentVersion: '0.1.0',
    };

    state = storeReducer(state, {
      type: 'BUS_EVENT',
      payload: { t: 'device.paired', device: dev },
    });
    expect(state.devices['dev-x']).toBeDefined();

    // Seed stats for dev-x
    state = storeReducer(state, {
      type: 'BUS_EVENT',
      payload: {
        t: 'stats.update',
        stats: {
          deviceId: 'dev-x',
          ts: 3000,
          cpuPct: 10,
          memPct: 20,
          memFreeMb: 25000,
          diskFreeMb: 400000,
          battery: null,
          online: true,
        },
      },
    });
    expect(state.stats['dev-x']?.online).toBe(true);

    // Now lose device
    state = storeReducer(state, {
      type: 'BUS_EVENT',
      payload: { t: 'device.lost', deviceId: 'dev-x' },
    });
    expect(state.stats['dev-x']?.online).toBe(false);
  });

  it('handles theme switching and peer selection', () => {
    let state = createInitialState();
    state = storeReducer(state, { type: 'SET_THEME', payload: 'light' });
    expect(state.theme).toBe('light');

    state = storeReducer(state, { type: 'SELECT_PEER', payload: 'dev-peer-99' });
    expect(state.peerDeviceId).toBe('dev-peer-99');
  });

  it('toggles mock feeder and updates simulated state', () => {
    let state = createInitialState();
    expect(state.isSimulated).toBe(true);

    state = storeReducer(state, { type: 'TOGGLE_MOCK_FEEDER', payload: false });
    expect(state.mockFeederActive).toBe(false);
  });
});

