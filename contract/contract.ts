// SOURCE OF TRUTH. Changes only via P1. contract/contract.py mirrors this with identical camelCase names (pydantic v2 models, Protocols for the module interfaces).
export type Arch = 'x86_64' | 'arm64';
export type OsName = 'windows' | 'linux' | 'macos';
export type LinkType = 'wifi' | 'cable' | 'loopback';
export type Decision = 'MIGRATE' | 'REMOTE_ACCESS' | 'STAY';
export type Trigger = 'low_battery' | 'cpu_pressure' | 'memory_pressure' | 'connectivity_lost' | 'predicted' | 'user_command';
export type AuthorityState = 'SOURCE' | 'FENCED' | 'TARGET';
export type RunState = 'idle' | 'running' | 'paused' | 'stopped' | 'exited';
export type Phase = 'IDLE' | 'CONNECTING' | 'EVALUATING' | 'TRANSFERRING' | 'VALIDATING' | 'FENCING' | 'STARTING_TARGET' | 'COMPLETED' | 'ROLLING_BACK' | 'ROLLED_BACK' | 'REMOTE_ACCESS' | 'FAILED';

export interface DeviceInfo { id: string; name: string; os: OsName; arch: Arch; cpuCores: number; ramMb: number; gpu: string | null; diskFreeMb: number; runtimes: Record<string, string>; libs: string[]; addrs: { addr: string; link: LinkType }[]; agentVersion: string; simulated?: boolean }
export interface Stats { deviceId: string; ts: number; cpuPct: number; memPct: number; memFreeMb: number; diskFreeMb: number; battery: { pct: number; charging: boolean } | null; online: boolean; simulated?: boolean; stale?: boolean }
export interface LinkQuality { peerId: string; link: LinkType; rttMs: number; mbps: number; lossPct: number; ts: number; online?: boolean; simulated?: boolean }
export interface CheckpointDef { id: string; name: string; paths: string[] }
export interface WorkloadManifest { id: string; name: string; command: string; runtime: { name: string; minVersion: string }; arch: Arch[]; os: OsName[]; minRamMb: number; minCpuCores: number; minDiskMb: number; needsGpu: boolean; libs: string[]; checkpoints: CheckpointDef[]; remoteCapable: boolean }
export interface CheckpointRecord { id: string; seq: number; sizeBytes: number; sha256: string; createdAt: number; sent?: boolean; validated?: boolean }
export interface Reason { code: string; severity: 'pass' | 'warn' | 'block'; text: string }
export interface FeasibilityResult { workloadId: string; sourceId: string; targetId: string; decision: Decision; reasons: Reason[]; estTransferSec: number; estInterruptionMs: number; ts: number }
export interface Authority { workloadId: string; holder: string | null; epoch: number; state: AuthorityState }
export interface MigrationStatus { id: string; workloadId: string; sourceId: string; targetId: string; phase: Phase; trigger: Trigger; link: LinkType; decision?: Decision; reasons: Reason[]; checkpoints: CheckpointRecord[]; bytesTotal: number; bytesDone: number; authority: Authority; interruptionMs?: number; error?: string; startedAt: number; endedAt?: number; metrics?: MigrationMetrics }
export interface CheckpointMetric { id: string; stage: 'initial' | 'catchup' | 'delta' | 'precopy'; sizeBytes: number; chunks: number; retries: number; transferMs: number; mbps: number; skipped: boolean }
export interface MigrationMetrics { migrationId: string; link: LinkType; chunkSize: number; durationMs: number; interruptionMs?: number; bytesTotal: number; bytesDone: number; bytesSkipped: number; throughputMbps: number; checkpoints: CheckpointMetric[]; ts: number; cutover?: CutoverTiming }
export interface CutoverTiming { catchupRounds: number; fenceMs: number; deltaBytes: number; deltaMs: number; startMs: number }
export interface AuthorityConflict { workloadId: string; deviceId: string; peerId: string; localEpoch: number; remoteEpoch: number; winner: string; stopped: string; reason: string; ts: number }
export interface Recommendation { workloadId: string; trigger: Trigger; targetId: string | null; decision: Decision; reasons: Reason[]; auto: boolean; ts: number }
export interface RemoteSession { id: string; workloadId: string; hostId: string; viewerId: string; consent: boolean; fps: number; ts: number }
export interface WorkloadRun { workloadId: string; state: RunState; pid: number | null; exitCode: number | null; startedAt: number | null; restored: string[]; logTail: string[] }
export interface DecisionLog { id: string; ts: number; workloadId: string; trigger: Trigger; decision: Decision; reasons: Reason[]; migrationId?: string }

// Peer link messages (device to device, always encrypted)
export type PeerMessage =
  | { t: 'peer.hello'; device: DeviceInfo }
  | { t: 'peer.stats'; stats: Stats }
  | { t: 'peer.ping'; n: number } | { t: 'peer.pong'; n: number }
  | { t: 'mig.prepare'; migrationId: string; manifest: WorkloadManifest; checkpoints: CheckpointRecord[]; epoch: number; signature: string; chunkSize?: number; precopy?: boolean }
  | { t: 'mig.ready'; migrationId: string; ok: boolean; reasons: Reason[]; have?: string[] }
  | { t: 'mig.chunk'; migrationId: string; checkpointId: string; index: number; total: number; dataB64: string; sha256: string; epoch: number }
  | { t: 'mig.chunkAck'; migrationId: string; checkpointId: string; index: number; ok: boolean }
  | { t: 'mig.validated'; migrationId: string; ok: boolean; failed?: string[] }
  | { t: 'mig.fence'; migrationId: string; epoch: number }
  | { t: 'mig.fenced'; migrationId: string; changed: CheckpointRecord[] }
  | { t: 'mig.start'; migrationId: string; epoch: number }
  | { t: 'mig.started'; migrationId: string; ok: boolean; error?: string }
  | { t: 'mig.abort'; migrationId: string; reason: string }
  | { t: 'auth.leases'; leases: Authority[]; conflicts?: AuthorityConflict[] };

// Event bus (inside one agent) and the /ws/events stream
export type BusEvent =
  | { t: 'stats.update'; stats: Stats }
  | { t: 'link.update'; link: LinkQuality }
  | { t: 'device.paired'; device: DeviceInfo } | { t: 'device.lost'; deviceId: string }
  | { t: 'recommendation'; rec: Recommendation }
  | { t: 'decision.logged'; log: DecisionLog }
  | { t: 'migration.status'; status: MigrationStatus }
  | { t: 'authority.change'; authority: Authority }
  | { t: 'remote.session'; session: RemoteSession }
  | { t: 'authority.conflict'; conflict: AuthorityConflict };

// REST: GET /api/health, /api/devices, /api/stats, /api/workloads (WorkloadManifest[]), /api/workloads/runs (WorkloadRun[]), /api/settings, /api/history/devices, /api/history/migrations, /api/history/decisions, /api/migrations, /api/migrations/{id}/metrics (MigrationMetrics)
// POST /api/pair {addr, pin}, /api/workloads/start {manifestPath}, /api/feasibility {workloadId, targetId}, /api/migrations {workloadId, targetId, trigger}, /api/migrations/{id}/abort, /api/workloads/{id}/precopy {targetId}, /api/remote/start {workloadId, viewerId}, /api/dev/stats-override {deviceId, stats | null}; PUT /api/settings
// Agent-local SDK API (127.0.0.1, Authorization: Bearer <per-run token>), used by sdk/teleport_sdk: POST /api/sdk/workloads/{id}/checkpoints/{checkpointId} (tar.gz unit), GET /api/sdk/workloads/{id}/control {fenceSeq, stop}, POST /api/sdk/workloads/{id}/fenced {fenceSeq}
// WebSocket: /ws/events (BusEvent as JSON), /ws/remote/{sessionId} (binary JPEG frames out, JSON input events in)
