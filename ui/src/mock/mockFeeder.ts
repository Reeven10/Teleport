import type {
  Authority,
  BusEvent,
  CheckpointDef,
  CheckpointRecord,
  DeviceInfo,
  LinkQuality,
  MigrationStatus,
  Recommendation,
  RemoteSession,
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

export const MOCK_10_CHECKPOINTS: CheckpointDef[] = [
  { id: 'chk-1-mem', name: '1. Memory Map (Heap)', paths: ['/state/heap.bin'] },
  { id: 'chk-2-fd', name: '2. File Descriptors', paths: ['/state/fds.json'] },
  { id: 'chk-3-proc', name: '3. Process Context', paths: ['/state/proc.json'] },
  { id: 'chk-4-buf', name: '4. Data Buffers', paths: ['/state/buffers.bin'] },
  { id: 'chk-5-sock', name: '5. Sockets & Threads', paths: ['/state/threads.json'] },
  { id: 'chk-6-delta', name: '6. Delta Memory', paths: ['/state/delta.bin'] },
  { id: 'chk-7-weights', name: '7. Model Weights', paths: ['/state/weights.bin'] },
  { id: 'chk-8-optimizer', name: '8. Optimizer State', paths: ['/state/optim.pt'] },
  { id: 'chk-9-dataset', name: '9. Dataset Cache Offsets', paths: ['/state/cache.idx'] },
  { id: 'chk-10-env', name: '10. Environment Variables', paths: ['/state/env.json'] },
];

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
    checkpoints: MOCK_10_CHECKPOINTS,
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

export type MockScenario = 'in_flight' | 'completed' | 'rollback' | 'remote_access' | 'normal';

export class MockFeeder {
  private timer: number | null = null;
  private tickCount = 0;
  private batteryPctA = 38;
  private emitCallback: ((e: BusEvent) => void) | null = null;
  public currentScenario: MockScenario = 'normal';

  constructor(onEvent?: (e: BusEvent) => void) {
    if (onEvent) this.emitCallback = onEvent;

    // Check URL parameters for explicit test scenario
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search).get('scenario');
      if (p === 'in_flight' || p === 'completed' || p === 'rollback' || p === 'remote_access' || p === 'normal') {
        this.currentScenario = p;
      }
    }
  }

  setCallback(cb: (e: BusEvent) => void): void {
    this.emitCallback = cb;
  }

  setScenario(s: MockScenario): void {
    this.currentScenario = s;
    this.tick();
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

    // 1. Telemetry Updates for Device A and Device B
    if (this.tickCount % 2 === 0 && this.batteryPctA > 11) {
      this.batteryPctA -= 1;
    }

    const cpuA = this.tickCount % 14 >= 11 ? 92 + Math.random() * 5 : 44 + Math.sin(this.tickCount * 0.5) * 10;
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

    const statsB: Stats = {
      deviceId: 'device-b',
      ts: now,
      cpuPct: 20 + Math.cos(this.tickCount * 0.4) * 6,
      memPct: 41,
      memFreeMb: 19320,
      diskFreeMb: 511800,
      battery: null, // Desktop
      online: true,
      simulated: true,
    };
    this.emitCallback({ t: 'stats.update', stats: statsB });

    // Link Quality
    const link: LinkQuality = {
      peerId: 'device-b',
      link: 'cable',
      rttMs: 1.2,
      mbps: 1000,
      lossPct: 0.0,
      ts: now,
    };
    this.emitCallback({ t: 'link.update', link });

    // 2. Scenario-Specific Execution
    if (this.currentScenario === 'in_flight') {
      this.emitInFlight5Of10(now);
      return;
    }
    if (this.currentScenario === 'completed') {
      this.emitCompleted(now);
      return;
    }
    if (this.currentScenario === 'rollback') {
      this.emitRollback(now);
      return;
    }
    if (this.currentScenario === 'remote_access') {
      this.emitRemoteAccess(now);
      return;
    }

    // Default 'normal' loop
    this.emitNormalLoop(now);
  }

  // --- Scenario 1: 5 of 10 Validated with Authority still on Device A ---
  public emitInFlight5Of10(now: number): void {
    if (!this.emitCallback) return;

    const totalBytes = 250 * 1024 * 1024; // 250 MB
    const totalCount = 10;
    const validatedCount = 5;

    const checkpoints: CheckpointRecord[] = MOCK_10_CHECKPOINTS.map((c, idx) => ({
      id: c.id,
      seq: idx + 1,
      sizeBytes: 25 * 1024 * 1024,
      sha256: `sha256-${c.id}-checksum`,
      createdAt: now - 15000,
      sent: idx < 6, // 1..6 sent (6th is in transit)
      validated: idx < validatedCount, // Exactly 5 validated
    }));

    const bytesDone = Math.round((5.5 / totalCount) * totalBytes);
    const auth: Authority = {
      workloadId: 'wl-token-trainer',
      holder: 'device-a', // Authority strictly remains on Source!
      epoch: 1,
      state: 'SOURCE',
    };

    const status: MigrationStatus = {
      id: 'mig-scenario-inflight',
      workloadId: 'wl-token-trainer',
      sourceId: 'device-a',
      targetId: 'device-b',
      phase: 'TRANSFERRING',
      trigger: 'low_battery',
      link: 'cable',
      decision: 'MIGRATE',
      reasons: [
        { code: 'ARCH_MATCH', severity: 'pass', text: 'Target architecture x86_64 compatible with container runtime' },
        { code: 'RAM_ADEQUATE', severity: 'pass', text: 'Target free RAM (19.3 GB) exceeds required 4 GB floor' },
        { code: 'LINK_FAST', severity: 'pass', text: 'Point-to-point cable link active (1000 Mbps, 1.2ms RTT)' },
      ],
      checkpoints,
      bytesTotal: totalBytes,
      bytesDone,
      authority: auth,
      startedAt: now - 12000,
    };

    this.emitCallback({ t: 'authority.change', authority: auth });
    this.emitCallback({ t: 'migration.status', status });
  }

  // --- Scenario 2: Completed Migration with Interruption Time ---
  public emitCompleted(now: number): void {
    if (!this.emitCallback) return;

    const totalBytes = 250 * 1024 * 1024;
    const checkpoints: CheckpointRecord[] = MOCK_10_CHECKPOINTS.map((c, idx) => ({
      id: c.id,
      seq: idx + 1,
      sizeBytes: 25 * 1024 * 1024,
      sha256: `sha256-${c.id}-ok`,
      createdAt: now - 30000,
      sent: true,
      validated: true,
    }));

    const auth: Authority = {
      workloadId: 'wl-token-trainer',
      holder: 'device-b', // Authority handed over to Target
      epoch: 2,
      state: 'TARGET',
    };

    const status: MigrationStatus = {
      id: 'mig-scenario-completed',
      workloadId: 'wl-token-trainer',
      sourceId: 'device-a',
      targetId: 'device-b',
      phase: 'COMPLETED',
      trigger: 'low_battery',
      link: 'cable',
      decision: 'MIGRATE',
      reasons: [
        { code: 'ALL_VALIDATED', severity: 'pass', text: 'All 10 checkpoints verified by SHA-256 integrity checks' },
        { code: 'FENCE_CONFIRMED', severity: 'pass', text: 'Source fenced at Epoch 2 without state loss' },
        { code: 'TARGET_STARTED', severity: 'pass', text: 'Workload successfully running on target Device B' },
      ],
      checkpoints,
      bytesTotal: totalBytes,
      bytesDone: totalBytes,
      authority: auth,
      interruptionMs: 42, // Exact interruption stopwatch
      startedAt: now - 25000,
      endedAt: now,
    };

    this.emitCallback({ t: 'authority.change', authority: auth });
    this.emitCallback({ t: 'migration.status', status });
  }

  // --- Scenario 3: Rollback with Detailed Reason ---
  public emitRollback(now: number): void {
    if (!this.emitCallback) return;

    const totalBytes = 250 * 1024 * 1024;
    const checkpoints: CheckpointRecord[] = MOCK_10_CHECKPOINTS.map((c, idx) => ({
      id: c.id,
      seq: idx + 1,
      sizeBytes: 25 * 1024 * 1024,
      sha256: idx === 3 ? 'sha256-corrupted-hash' : `sha256-${c.id}-ok`,
      createdAt: now - 18000,
      sent: idx <= 3,
      validated: idx < 3 ? true : false, // Checkpoint 4 failed!
    }));

    // Authority rolled back from FENCED to SOURCE on Device A
    const auth: Authority = {
      workloadId: 'wl-token-trainer',
      holder: 'device-a',
      epoch: 1,
      state: 'SOURCE',
    };

    const status: MigrationStatus = {
      id: 'mig-scenario-rollback',
      workloadId: 'wl-token-trainer',
      sourceId: 'device-a',
      targetId: 'device-b',
      phase: 'ROLLED_BACK',
      trigger: 'low_battery',
      link: 'cable',
      decision: 'MIGRATE',
      reasons: [
        {
          code: 'CHECKPOINT_CORRUPTION',
          severity: 'block',
          text: 'Validation failed at Checkpoint 4 (Data Buffers): SHA-256 hash mismatch. Authority retained at Device A.',
        },
        {
          code: 'ROLLBACK_SAFE',
          severity: 'warn',
          text: 'Source unfenced: workload resumed live on Device A without loss of state',
        },
      ],
      checkpoints,
      bytesTotal: totalBytes,
      bytesDone: 100 * 1024 * 1024,
      authority: auth,
      error: 'Validation failed at Checkpoint 4 (Data Buffers): SHA-256 hash mismatch. Cutover aborted.',
      startedAt: now - 18000,
      endedAt: now,
    };

    this.emitCallback({ t: 'authority.change', authority: auth });
    this.emitCallback({ t: 'migration.status', status });
  }

  // --- Scenario 4: Infeasible Migration Forcing Remote Access Decision ---
  public emitRemoteAccess(now: number): void {
    if (!this.emitCallback) return;

    const auth: Authority = {
      workloadId: 'wl-token-trainer',
      holder: 'device-a',
      epoch: 1,
      state: 'SOURCE',
    };

    const status: MigrationStatus = {
      id: 'mig-scenario-remote',
      workloadId: 'wl-token-trainer',
      sourceId: 'device-a',
      targetId: 'device-b',
      phase: 'REMOTE_ACCESS',
      trigger: 'user_command',
      link: 'cable',
      decision: 'REMOTE_ACCESS',
      reasons: [
        {
          code: 'GPU_REQUIRED_BLOCK',
          severity: 'block',
          text: 'Target Device B lacks required CUDA GPU compute capability (Compute >= 7.0 required).',
        },
        {
          code: 'REMOTE_CAPABLE',
          severity: 'pass',
          text: 'Workload is declared remoteCapable=True: falling back to zero-install remote desktop stream.',
        },
        {
          code: 'LINK_FAST',
          severity: 'pass',
          text: 'High-speed cable connection available: 1000 Mbps throughput supports 30 FPS at 720p.',
        },
      ],
      checkpoints: [],
      bytesTotal: 0,
      bytesDone: 0,
      authority: auth,
      startedAt: now - 5000,
    };

    const rec: Recommendation = {
      workloadId: 'wl-token-trainer',
      trigger: 'user_command',
      targetId: 'device-b',
      decision: 'REMOTE_ACCESS',
      reasons: status.reasons,
      auto: false,
      ts: now,
    };

    const session: RemoteSession = {
      id: 'rs-demo-remote-1',
      workloadId: 'wl-token-trainer',
      hostId: 'device-a',
      viewerId: 'device-b',
      consent: true,
      fps: 24.0,
      ts: now,
    };

    this.emitCallback({ t: 'migration.status', status });
    this.emitCallback({ t: 'recommendation', rec });
    this.emitCallback({ t: 'remote.session', session });
  }

  private emitNormalLoop(now: number): void {
    const cycle = this.tickCount % 40;
    if (cycle < 15) {
      this.emitInFlight5Of10(now);
    } else if (cycle < 28) {
      this.emitCompleted(now);
    } else if (cycle < 34) {
      this.emitRollback(now);
    } else {
      this.emitRemoteAccess(now);
    }
  }
}
