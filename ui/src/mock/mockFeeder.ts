import type {
  Authority,
  BusEvent,
  DeviceInfo,
  LinkQuality,
  MigrationStatus,
  Recommendation,
  Stats,
} from '@contract';
import type { MetricHistoryPoint, WorkloadItem } from '../store/types.ts';

export const MOCK_DEVICE_A: DeviceInfo = {
  id: 'device-a',
  name: 'Device A (MacBook Pro M2)',
  os: 'macos',
  arch: 'arm64',
  cpuCores: 10,
  ramMb: 16384,
  gpu: 'Apple M2 Pro (16-core GPU)',
  diskFreeMb: 122880,
  runtimes: { python: '3.11.9', node: '20.12.2' },
  libs: ['torch', 'fastapi', 'numpy', 'psutil'],
  addrs: [
    { addr: '192.168.1.101', link: 'cable' },
    { addr: '10.0.0.15', link: 'wifi' },
  ],
  agentVersion: '0.1.0',
  simulated: true,
};

export const MOCK_DEVICE_B: DeviceInfo = {
  id: 'device-b',
  name: 'Device B (Workstation Tower)',
  os: 'linux',
  arch: 'x86_64',
  cpuCores: 16,
  ramMb: 32768,
  gpu: 'NVIDIA GeForce RTX 4080 (16GB VRAM)',
  diskFreeMb: 512000,
  runtimes: { python: '3.11.9', node: '20.12.2' },
  libs: ['torch', 'fastapi', 'numpy', 'cuda-12.4', 'psutil'],
  addrs: [{ addr: '192.168.1.102', link: 'cable' }],
  agentVersion: '0.1.0',
  simulated: true,
};

export const MOCK_WORKLOAD: WorkloadItem = {
  manifest: {
    id: 'wl-token-trainer',
    name: 'ML Token Batch Trainer',
    command: 'python -m examples.trainer --batch-size 64',
    runtime: { name: 'python', minVersion: '3.11' },
    arch: ['arm64', 'x86_64'],
    os: ['macos', 'linux'],
    minRamMb: 4096,
    minCpuCores: 4,
    minDiskMb: 10240,
    needsGpu: false,
    libs: ['torch', 'numpy'],
    remoteCapable: true,
    checkpoints: [
      { id: 'chk-1-mem', name: '1. Memory Map', paths: ['/state/heap.bin'] },
      { id: 'chk-2-fd', name: '2. File Descriptors', paths: ['/state/fds.json'] },
      { id: 'chk-3-proc', name: '3. Process Context', paths: ['/state/proc.json'] },
      { id: 'chk-4-buf', name: '4. Data Buffers', paths: ['/state/buffers.bin'] },
      { id: 'chk-5-sock', name: '5. Sockets & Threads', paths: ['/state/threads.json'] },
      { id: 'chk-6-delta', name: '6. Delta Memory', paths: ['/state/delta.bin'] },
    ],
  },
  status: 'RUNNING',
  authority: {
    workloadId: 'wl-token-trainer',
    holder: 'device-a',
    epoch: 1,
    state: 'SOURCE',
  },
};

export function generateInitialHistory(baseCpu: number, baseMem: number, baseDisk: number): MetricHistoryPoint[] {
  const points: MetricHistoryPoint[] = [];
  const now = Date.now();
  for (let i = 59; i >= 0; i--) {
    const ts = now - i * 1000;
    const cpuNoise = Math.sin(i * 0.4) * 8 + (Math.random() * 6 - 3);
    const memNoise = Math.cos(i * 0.2) * 2 + (Math.random() * 2 - 1);
    points.push({
      ts,
      cpuPct: Math.max(5, Math.min(98, Math.round(baseCpu + cpuNoise))),
      memPct: Math.max(10, Math.min(95, Math.round(baseMem + memNoise))),
      diskFreeMb: Math.round(baseDisk + (Math.random() * 100 - 50)),
    });
  }
  return points;
}

export class MockFeeder {
  private timer: number | null = null;
  private tickCount = 0;
  private batteryPctA = 38;
  private emitCallback: ((e: BusEvent) => void) | null = null;

  constructor(onEvent?: (e: BusEvent) => void) {
    if (onEvent) this.emitCallback = onEvent;
  }

  setCallback(cb: (e: BusEvent) => void): void {
    this.emitCallback = cb;
  }

  start(intervalMs = 1000): void {
    if (this.timer !== null) return;

    // Seed devices immediately
    if (this.emitCallback) {
      this.emitCallback({ t: 'device.paired', device: MOCK_DEVICE_A });
      this.emitCallback({ t: 'device.paired', device: MOCK_DEVICE_B });
    }

    this.timer = window.setInterval(() => {
      this.tick();
    }, intervalMs);

    // Initial immediate tick
    this.tick();
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private tick(): void {
    if (!this.emitCallback) return;
    this.tickCount++;
    const now = Date.now();

    // 1. Drain battery on Device A slowly, down to 11%
    if (this.tickCount % 2 === 0 && this.batteryPctA > 11) {
      this.batteryPctA -= 1;
    }

    // CPU spike simulation on Device A
    const isCpuSpike = this.tickCount % 14 >= 11;
    const cpuA = isCpuSpike ? 88 + Math.random() * 8 : 42 + Math.sin(this.tickCount * 0.5) * 12 + (Math.random() * 6 - 3);

    // Stats for Device A
    const statsA: Stats = {
      deviceId: 'device-a',
      ts: now,
      cpuPct: Math.min(99, Math.max(5, cpuA)),
      memPct: 68 + Math.sin(this.tickCount * 0.2) * 3,
      memFreeMb: 5240,
      diskFreeMb: 122400,
      battery: { pct: this.batteryPctA, charging: false },
      online: true,
      simulated: true,
    };
    this.emitCallback({ t: 'stats.update', stats: statsA });

    // Stats for Device B (Desktop workstation on AC power -> battery is null!)
    const statsB: Stats = {
      deviceId: 'device-b',
      ts: now,
      cpuPct: 18 + Math.cos(this.tickCount * 0.4) * 6 + (Math.random() * 4 - 2),
      memPct: 41 + Math.sin(this.tickCount * 0.1) * 2,
      memFreeMb: 19320,
      diskFreeMb: 511800,
      battery: null, // Desktop honestly has no battery
      online: true,
      simulated: true,
    };
    this.emitCallback({ t: 'stats.update', stats: statsB });

    // 2. Link quality progression: cable -> wifi -> wifi degraded -> back to cable
    const linkCycle = this.tickCount % 36;
    let link: LinkQuality;
    if (linkCycle < 14) {
      // Cable: 1000 Mbps, 1.2ms RTT, 0% loss
      link = {
        peerId: 'device-b',
        link: 'cable',
        rttMs: 1.1 + Math.random() * 0.3,
        mbps: 980 + Math.random() * 30,
        lossPct: 0.0,
        ts: now,
      };
    } else if (linkCycle < 26) {
      // WiFi normal: 160 Mbps, 14ms RTT, 0.2% loss
      link = {
        peerId: 'device-b',
        link: 'wifi',
        rttMs: 14.2 + Math.random() * 4,
        mbps: 165 - Math.random() * 25,
        lossPct: 0.2,
        ts: now,
      };
    } else {
      // WiFi degraded: 42 Mbps, 78ms RTT, 3.1% loss
      link = {
        peerId: 'device-b',
        link: 'wifi',
        rttMs: 78.5 + Math.random() * 15,
        mbps: 42 - Math.random() * 10,
        lossPct: 3.1,
        ts: now,
      };
    }
    this.emitCallback({ t: 'link.update', link });

    // 3. Orchestration Recommendation (battery warning trigger)
    if (this.batteryPctA <= 20) {
      const rec: Recommendation = {
        workloadId: 'wl-token-trainer',
        trigger: 'low_battery',
        targetId: 'device-b',
        decision: 'MIGRATE',
        reasons: [
          {
            code: 'BATTERY_LOW',
            severity: 'warn',
            text: `Device A battery at ${this.batteryPctA}% (below 20% safety threshold)`,
          },
          {
            code: 'PEER_RESOURCE_FIT',
            severity: 'pass',
            text: 'Target Device B has 32GB RAM and 16 CPU cores (adequate for workload floor)',
          },
          {
            code: 'RUNTIME_COMPATIBLE',
            severity: 'pass',
            text: 'Python 3.11.9 available on target',
          },
        ],
        auto: false,
        ts: now,
      };
      this.emitCallback({ t: 'recommendation', rec });
    }

    // 4. Migration sequence progression (demonstrates full 6-checkpoint cycle)
    this.emitMigrationCycle(now);
  }

  private emitMigrationCycle(now: number): void {
    if (!this.emitCallback) return;
    const migCycle = this.tickCount % 40;

    const totalBytes = 240 * 1024 * 1024; // 240 MB

    if (migCycle === 15) {
      // Evaluating
      const status: MigrationStatus = {
        id: 'mig-demo-1',
        workloadId: 'wl-token-trainer',
        sourceId: 'device-a',
        targetId: 'device-b',
        phase: 'EVALUATING',
        trigger: 'low_battery',
        link: 'cable',
        decision: 'MIGRATE',
        reasons: [{ code: 'BATTERY_LOW', severity: 'warn', text: 'Low battery evaluated' }],
        checkpoints: [],
        bytesTotal: totalBytes,
        bytesDone: 0,
        authority: { workloadId: 'wl-token-trainer', holder: 'device-a', epoch: 1, state: 'SOURCE' },
        startedAt: now,
      };
      this.emitCallback({ t: 'migration.status', status });
    } else if (migCycle >= 16 && migCycle <= 21) {
      // Transferring 6 checkpoints sequentially
      const completedIndex = migCycle - 16;
      const checkpoints = MOCK_WORKLOAD.manifest.checkpoints.map((c, idx) => ({
        id: c.id,
        seq: idx + 1,
        sizeBytes: 40 * 1024 * 1024,
        sha256: `sha256-chk-${idx + 1}-validated`,
        createdAt: now - 5000,
        sent: idx <= completedIndex,
        validated: idx <= completedIndex,
      }));

      const bytesDone = Math.round(((completedIndex + 1) / 6) * totalBytes);
      const status: MigrationStatus = {
        id: 'mig-demo-1',
        workloadId: 'wl-token-trainer',
        sourceId: 'device-a',
        targetId: 'device-b',
        phase: 'TRANSFERRING',
        trigger: 'low_battery',
        link: 'cable',
        decision: 'MIGRATE',
        reasons: [{ code: 'ALL_PASS', severity: 'pass', text: 'Pre-flight checks passed' }],
        checkpoints,
        bytesTotal: totalBytes,
        bytesDone,
        authority: { workloadId: 'wl-token-trainer', holder: 'device-a', epoch: 1, state: 'SOURCE' },
        startedAt: now - 6000,
      };
      this.emitCallback({ t: 'migration.status', status });
    } else if (migCycle === 22) {
      // Fencing cutover
      const auth: Authority = { workloadId: 'wl-token-trainer', holder: 'device-a', epoch: 2, state: 'FENCED' };
      this.emitCallback({ t: 'authority.change', authority: auth });
      const status: MigrationStatus = {
        id: 'mig-demo-1',
        workloadId: 'wl-token-trainer',
        sourceId: 'device-a',
        targetId: 'device-b',
        phase: 'FENCING',
        trigger: 'low_battery',
        link: 'cable',
        decision: 'MIGRATE',
        reasons: [{ code: 'FENCED_OK', severity: 'pass', text: 'Workload authority fenced at Epoch 2' }],
        checkpoints: MOCK_WORKLOAD.manifest.checkpoints.map((c, idx) => ({
          id: c.id,
          seq: idx + 1,
          sizeBytes: 40 * 1024 * 1024,
          sha256: `sha256-chk-${idx + 1}`,
          createdAt: now - 6000,
          sent: true,
          validated: true,
        })),
        bytesTotal: totalBytes,
        bytesDone: totalBytes,
        authority: auth,
        startedAt: now - 7000,
      };
      this.emitCallback({ t: 'migration.status', status });
    } else if (migCycle === 23) {
      // Target authority handover
      const auth: Authority = { workloadId: 'wl-token-trainer', holder: 'device-b', epoch: 2, state: 'TARGET' };
      this.emitCallback({ t: 'authority.change', authority: auth });
      const status: MigrationStatus = {
        id: 'mig-demo-1',
        workloadId: 'wl-token-trainer',
        sourceId: 'device-a',
        targetId: 'device-b',
        phase: 'STARTING_TARGET',
        trigger: 'low_battery',
        link: 'cable',
        decision: 'MIGRATE',
        reasons: [{ code: 'TARGET_STARTING', severity: 'pass', text: 'Target starting restored workload copy' }],
        checkpoints: MOCK_WORKLOAD.manifest.checkpoints.map((c, idx) => ({
          id: c.id,
          seq: idx + 1,
          sizeBytes: 40 * 1024 * 1024,
          sha256: `sha256-chk-${idx + 1}`,
          createdAt: now - 7000,
          sent: true,
          validated: true,
        })),
        bytesTotal: totalBytes,
        bytesDone: totalBytes,
        authority: auth,
        interruptionMs: 42,
        startedAt: now - 8000,
      };
      this.emitCallback({ t: 'migration.status', status });
    } else if (migCycle === 24) {
      // Completed
      const auth: Authority = { workloadId: 'wl-token-trainer', holder: 'device-b', epoch: 2, state: 'TARGET' };
      const status: MigrationStatus = {
        id: 'mig-demo-1',
        workloadId: 'wl-token-trainer',
        sourceId: 'device-a',
        targetId: 'device-b',
        phase: 'COMPLETED',
        trigger: 'low_battery',
        link: 'cable',
        decision: 'MIGRATE',
        reasons: [{ code: 'MIGRATION_COMPLETED', severity: 'pass', text: 'Target verified running; source cleaned up' }],
        checkpoints: MOCK_WORKLOAD.manifest.checkpoints.map((c, idx) => ({
          id: c.id,
          seq: idx + 1,
          sizeBytes: 40 * 1024 * 1024,
          sha256: `sha256-chk-${idx + 1}`,
          createdAt: now - 8000,
          sent: true,
          validated: true,
        })),
        bytesTotal: totalBytes,
        bytesDone: totalBytes,
        authority: auth,
        interruptionMs: 42,
        startedAt: now - 9000,
        endedAt: now,
      };
      this.emitCallback({ t: 'migration.status', status });
    }
  }
}
