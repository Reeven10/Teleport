import type {
  Authority,
  AuthorityConflict,
  BusEvent,
  DeviceInfo,
  LinkQuality,
  MigrationStatus,
  Recommendation,
  RemoteSession,
  Stats,
  WorkloadManifest,
  WorkloadRun,
} from '@contract';

export interface MetricHistoryPoint {
  ts: number;
  cpuPct: number;
  memPct: number;
  diskFreeMb: number;
}

export type WorkloadStatus = 'RUNNING' | 'STOPPED' | 'PAUSED' | 'MIGRATING';

export interface WorkloadItem {
  manifest: WorkloadManifest;
  status: WorkloadStatus;
  authority?: Authority;
}

export interface TeleportState {
  thisDeviceId: string;
  peerDeviceId: string | null;
  devices: Record<string, DeviceInfo>;
  stats: Record<string, Stats>;
  history60s: Record<string, MetricHistoryPoint[]>;
  link: LinkQuality | null;
  workloads: WorkloadItem[];
  recommendation: Recommendation | null;
  migrationStatus: MigrationStatus | null;
  authority: Authority | null;
  remoteSession: RemoteSession | null;
  authorityConflict: AuthorityConflict | null;
  wsConnected: boolean;
  agentReachable: boolean;
  mockFeederActive: boolean;
  theme: 'dark' | 'light';
  isSimulated: boolean;
}

export type StoreAction =
  | {
      type: 'INIT_REST';
      payload: {
        thisDeviceId?: string;
        devices: DeviceInfo[];
        stats: Stats[];
        workloads?: WorkloadItem[];
        migrations?: MigrationStatus[];
        workloadRuns?: WorkloadRun[];
        remoteSessions?: RemoteSession[];
      };
    }
  | { type: 'BUS_EVENT'; payload: BusEvent }
  | { type: 'SET_WS_CONNECTED'; payload: boolean }
  | { type: 'SET_AGENT_REACHABLE'; payload: boolean }
  | { type: 'TOGGLE_MOCK_FEEDER'; payload: boolean }
  | { type: 'SET_THEME'; payload: 'dark' | 'light' }
  | { type: 'SELECT_PEER'; payload: string }
  | { type: 'ADD_PAIRED_DEVICE'; payload: DeviceInfo }
  | { type: 'ADD_WORKLOAD'; payload: WorkloadItem }
  | { type: 'SET_WORKLOADS'; payload: { workloads: WorkloadItem[]; runs: WorkloadRun[] } }
  | { type: 'CLEAR_RECOMMENDATION' };

