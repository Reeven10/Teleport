import type { DecisionLog, DeviceInfo, MigrationStatus } from '@contract';

export interface DeviceHistoryItem {
  device: DeviceInfo;
  firstSeen: number;
  lastSeen: number;
  migrationCount: number;
}

const NOW = Date.now();
const ONE_HOUR = 3600 * 1000;
const ONE_DAY = 24 * ONE_HOUR;

export const MOCK_HISTORY_DEVICES: DeviceHistoryItem[] = [
  {
    device: {
      id: 'device-a',
      name: 'MacBook Pro M3 Max (Local Host)',
      os: 'macos',
      arch: 'arm64',
      cpuCores: 16,
      ramMb: 36864,
      gpu: 'Apple M3 Max (38-core Metal GPU)',
      diskFreeMb: 420000,
      runtimes: { python: '3.11.8', node: '20.11.0' },
      libs: ['teleport-sdk', 'numpy', 'torch'],
      addrs: [{ addr: '127.0.0.1:8765', link: 'cable' }],
      agentVersion: '0.1.0',
    },
    firstSeen: NOW - 7 * ONE_DAY,
    lastSeen: NOW - 2 * 60 * 1000,
    migrationCount: 4,
  },
  {
    device: {
      id: 'device-b',
      name: 'Dell XPS 15 (Primary Peer)',
      os: 'linux',
      arch: 'x86_64',
      cpuCores: 14,
      ramMb: 32768,
      gpu: 'NVIDIA GeForce RTX 4070 (CUDA 12.2)',
      diskFreeMb: 280000,
      runtimes: { python: '3.11.6', node: '20.9.0' },
      libs: ['teleport-sdk', 'torch-cuda', 'scipy'],
      addrs: [{ addr: '192.168.1.105:8765', link: 'cable' }],
      agentVersion: '0.1.0',
    },
    firstSeen: NOW - 5 * ONE_DAY,
    lastSeen: NOW - 15 * 60 * 1000,
    migrationCount: 3,
  },
  {
    device: {
      id: 'device-c',
      name: 'ThinkPad P1 Gen 6',
      os: 'windows',
      arch: 'x86_64',
      cpuCores: 12,
      ramMb: 16384,
      gpu: 'NVIDIA RTX A1000',
      diskFreeMb: 150000,
      runtimes: { python: '3.11.5' },
      libs: ['teleport-sdk'],
      addrs: [{ addr: '192.168.1.140:8765', link: 'wifi' }],
      agentVersion: '0.1.0',
    },
    firstSeen: NOW - 12 * ONE_DAY,
    lastSeen: NOW - 2 * ONE_DAY,
    migrationCount: 1,
  },
  {
    device: {
      id: 'device-d',
      name: 'NVIDIA Jetson AGX Orin (Edge Node)',
      os: 'linux',
      arch: 'arm64',
      cpuCores: 8,
      ramMb: 8192,
      gpu: 'Ampere GPU 1792-core',
      diskFreeMb: 64000,
      runtimes: { python: '3.11.2' },
      libs: ['teleport-sdk', 'tensorrt'],
      addrs: [{ addr: '192.168.1.210:8765', link: 'wifi' }],
      agentVersion: '0.1.0',
    },
    firstSeen: NOW - 3 * ONE_DAY,
    lastSeen: NOW - 4 * ONE_HOUR,
    migrationCount: 0,
  },
];

export const MOCK_HISTORY_MIGRATIONS: MigrationStatus[] = [
  {
    id: 'mig-2026-001',
    workloadId: 'wl-token-trainer',
    sourceId: 'device-a',
    targetId: 'device-b',
    phase: 'COMPLETED',
    trigger: 'low_battery',
    link: 'cable',
    decision: 'MIGRATE',
    reasons: [
      {
        code: 'BATTERY_CRITICAL',
        severity: 'warn',
        text: 'Device A battery at 14% and discharging; Device B on AC power',
      },
      {
        code: 'RESOURCE_HEADROOM',
        severity: 'pass',
        text: 'Target Device B has 32GB RAM and compatible x86_64 execution runtime',
      },
      {
        code: 'LINK_HIGH_SPEED',
        severity: 'pass',
        text: 'Wired Gigabit Cable link confirmed (RTT 1.2ms, 0% packet loss)',
      },
    ],
    checkpoints: [
      { id: 'config', seq: 1, sizeBytes: 1024 * 64, sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08', createdAt: NOW - 2 * ONE_HOUR, sent: true, validated: true },
      { id: 'weights_init', seq: 2, sizeBytes: 50 * 1024 * 1024, sha256: '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8', createdAt: NOW - 2 * ONE_HOUR, sent: true, validated: true },
      { id: 'optimizer_state', seq: 3, sizeBytes: 80 * 1024 * 1024, sha256: '4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a', createdAt: NOW - 2 * ONE_HOUR, sent: true, validated: true },
      { id: 'dataset_cache', seq: 4, sizeBytes: 120 * 1024 * 1024, sha256: 'ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d', createdAt: NOW - 2 * ONE_HOUR, sent: true, validated: true },
    ],
    bytesTotal: 250 * 1024 * 1024,
    bytesDone: 250 * 1024 * 1024,
    authority: {
      workloadId: 'wl-token-trainer',
      holder: 'device-b',
      epoch: 2,
      state: 'TARGET',
    },
    interruptionMs: 42,
    startedAt: NOW - 2 * ONE_HOUR - 45000,
    endedAt: NOW - 2 * ONE_HOUR,
  },
  {
    id: 'mig-2026-002',
    workloadId: 'pipeline-job',
    sourceId: 'device-a',
    targetId: 'device-b',
    phase: 'ROLLED_BACK',
    trigger: 'cpu_pressure',
    link: 'wifi',
    decision: 'MIGRATE',
    reasons: [
      {
        code: 'CPU_SPIKE',
        severity: 'warn',
        text: 'Device A sustained CPU compute pressure above 94% threshold',
      },
      {
        code: 'CHECKPOINT_CORRUPT',
        severity: 'block',
        text: 'Validation failed at Checkpoint 4 (stage2_output): SHA-256 hash mismatch. Cutover aborted.',
      },
      {
        code: 'ROLLBACK_SAFE',
        severity: 'pass',
        text: 'Authority reverted to Device A (Epoch 1). Workload resumed live without state corruption.',
      },
    ],
    checkpoints: [
      { id: 'config', seq: 1, sizeBytes: 1024 * 16, sha256: 'a1b2c3d4e5f6', createdAt: NOW - 5 * ONE_HOUR, sent: true, validated: true },
      { id: 'input_data', seq: 2, sizeBytes: 10 * 1024 * 1024, sha256: 'b2c3d4e5f6a1', createdAt: NOW - 5 * ONE_HOUR, sent: true, validated: true },
      { id: 'stage1_output', seq: 3, sizeBytes: 25 * 1024 * 1024, sha256: 'c3d4e5f6a1b2', createdAt: NOW - 5 * ONE_HOUR, sent: true, validated: true },
      { id: 'stage2_output', seq: 4, sizeBytes: 30 * 1024 * 1024, sha256: 'd4e5f6a1b2c3-mismatch', createdAt: NOW - 5 * ONE_HOUR, sent: true, validated: false },
    ],
    bytesTotal: 85 * 1024 * 1024,
    bytesDone: 65 * 1024 * 1024,
    authority: {
      workloadId: 'pipeline-job',
      holder: 'device-a',
      epoch: 1,
      state: 'SOURCE',
    },
    error: 'Validation failed at Checkpoint 4 (stage2_output): SHA-256 hash mismatch. Authority retained at Device A.',
    startedAt: NOW - 5 * ONE_HOUR - 20000,
    endedAt: NOW - 5 * ONE_HOUR,
  },
  {
    id: 'mig-2026-003',
    workloadId: 'gpu-only-job',
    sourceId: 'device-b',
    targetId: 'device-a',
    phase: 'REMOTE_ACCESS',
    trigger: 'user_command',
    link: 'wifi',
    decision: 'REMOTE_ACCESS',
    reasons: [
      {
        code: 'GPU_REQUIRED',
        severity: 'block',
        text: 'Workload requires dedicated NVIDIA CUDA runtime; target node Device A uses Apple Metal',
      },
      {
        code: 'REMOTE_CAPABLE',
        severity: 'pass',
        text: 'Workload is flagged remoteCapable; fallback to zero-install interactive viewport activated',
      },
    ],
    checkpoints: [],
    bytesTotal: 0,
    bytesDone: 0,
    authority: {
      workloadId: 'gpu-only-job',
      holder: 'device-b',
      epoch: 1,
      state: 'SOURCE',
    },
    startedAt: NOW - 1 * ONE_DAY,
    endedAt: NOW - 1 * ONE_DAY + 5000,
  },
  {
    id: 'mig-2026-004',
    workloadId: 'notepad-app',
    sourceId: 'device-c',
    targetId: 'device-a',
    phase: 'COMPLETED',
    trigger: 'user_command',
    link: 'cable',
    decision: 'MIGRATE',
    reasons: [
      {
        code: 'USER_DIRECTED',
        severity: 'pass',
        text: 'Operator initiated transfer from ThinkPad to MacBook',
      },
      {
        code: 'STATE_COMPACT',
        severity: 'pass',
        text: 'All scratchpad document checkpoints serialized and verified in 18ms',
      },
    ],
    checkpoints: [
      { id: 'note_content', seq: 1, sizeBytes: 1024 * 8, sha256: '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069', createdAt: NOW - 2 * ONE_DAY, sent: true, validated: true },
    ],
    bytesTotal: 8 * 1024,
    bytesDone: 8 * 1024,
    authority: {
      workloadId: 'notepad-app',
      holder: 'device-a',
      epoch: 2,
      state: 'TARGET',
    },
    interruptionMs: 24,
    startedAt: NOW - 2 * ONE_DAY - 10000,
    endedAt: NOW - 2 * ONE_DAY,
  },
];

export const MOCK_HISTORY_DECISIONS: DecisionLog[] = [
  {
    id: 'dec-101',
    ts: NOW - 2 * ONE_HOUR - 50000,
    workloadId: 'wl-token-trainer',
    trigger: 'low_battery',
    decision: 'MIGRATE',
    migrationId: 'mig-2026-001',
    reasons: [
      { code: 'BATTERY_LOW', severity: 'warn', text: 'Device A battery level 14% below safe threshold (20%)' },
      { code: 'TARGET_HEALTHY', severity: 'pass', text: 'Target Device B has 32GB RAM and AC line power' },
    ],
  },
  {
    id: 'dec-102',
    ts: NOW - 5 * ONE_HOUR - 25000,
    workloadId: 'pipeline-job',
    trigger: 'cpu_pressure',
    decision: 'MIGRATE',
    migrationId: 'mig-2026-002',
    reasons: [
      { code: 'CPU_HIGH', severity: 'warn', text: 'Device A sustained CPU compute pressure above 90%' },
    ],
  },
  {
    id: 'dec-103',
    ts: NOW - 8 * ONE_HOUR,
    workloadId: 'pipeline-job',
    trigger: 'connectivity_lost',
    decision: 'STAY',
    reasons: [
      {
        code: 'LINK_DEGRADED',
        severity: 'block',
        text: 'Transport packet loss rose to 12.8% on wireless link; migrating state exceeds failure budget',
      },
      {
        code: 'EXECUTION_HEALTHY',
        severity: 'pass',
        text: 'Local host has sufficient battery (78%) and memory to continue running uninterrupted',
      },
    ],
  },
  {
    id: 'dec-104',
    ts: NOW - 1 * ONE_DAY,
    workloadId: 'gpu-only-job',
    trigger: 'user_command',
    decision: 'REMOTE_ACCESS',
    migrationId: 'mig-2026-003',
    reasons: [
      { code: 'GPU_CUDA_REQUIRED', severity: 'block', text: 'Workload requires CUDA-capable NVIDIA GPU' },
      { code: 'REMOTE_FALLBACK', severity: 'pass', text: 'Workload declared remoteCapable; launching screen viewport' },
    ],
  },
  {
    id: 'dec-105',
    ts: NOW - 3 * ONE_DAY,
    workloadId: 'analytics-daemon',
    trigger: 'predicted',
    decision: 'STAY',
    reasons: [
      { code: 'TREND_STABLE', severity: 'pass', text: 'Predicted CPU utilization over next 60s is nominal (24%)' },
      { code: 'NO_ACTION_REQUIRED', severity: 'pass', text: 'Proactive orchestrator: migration unnecessary' },
    ],
  },
];

