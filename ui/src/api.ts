import type {
  BusEvent,
  DecisionLog,
  DeviceInfo,
  MigrationStatus,
  RemoteSession,
  Stats,
  Trigger,
  WorkloadManifest,
  WorkloadRun,
} from '@contract';
import type { WorkloadItem } from './store/types.ts';

const agentParam = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('agent') : null;
export const agentBase = agentParam ?? '';

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${agentBase}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return (await res.json()) as T;
}

/** The agent's own explanation (`{"detail": "..."}`) when there is one, else the HTTP status. */
async function errorMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => '');
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ');
  } catch {
    /* not JSON */
  }
  return text || `${res.status} ${res.statusText}`;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${agentBase}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return (await res.json()) as T;
}

export async function putJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${agentBase}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`${res.status} ${path}: ${errorText || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function connectEvents(
  onEvent: (e: BusEvent) => void,
  onStatusChange?: (connected: boolean) => void,
): () => void {
  let isClosedManually = false;
  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;

  function connect() {
    if (isClosedManually) return;
    try {
      const base = agentBase || window.location.origin;
      const wsUrl = `${base.replace(/^http/, 'ws')}/ws/events`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        if (isClosedManually) {
          ws?.close();
          return;
        }
        onStatusChange?.(true);
      };

      ws.onmessage = (m: MessageEvent<string>) => {
        try {
          const parsed = JSON.parse(m.data) as BusEvent;
          onEvent(parsed);
        } catch (err) {
          console.warn('[Teleport WS] Error parsing BusEvent:', err);
        }
      };

      ws.onerror = () => {
        onStatusChange?.(false);
      };

      ws.onclose = () => {
        onStatusChange?.(false);
        ws = null;
        if (!isClosedManually) {
          reconnectTimer = window.setTimeout(connect, 3000);
        }
      };
    } catch {
      onStatusChange?.(false);
      if (!isClosedManually) {
        reconnectTimer = window.setTimeout(connect, 3000);
      }
    }
  }

  connect();

  return () => {
    isClosedManually = true;
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    if (ws) ws.close();
  };
}

export interface HealthResponse {
  ok: boolean;
  deviceId: string;
  name: string;
  port: number;
  simProfile?: string;
  agentVersion: string;
  ts: number;
}

export async function apiFetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/api/health');
}

export async function apiFetchMigrations(): Promise<MigrationStatus[]> {
  return getJson<MigrationStatus[]>('/api/migrations');
}

export async function apiFetchWorkloadRuns(): Promise<WorkloadRun[]> {
  return getJson<WorkloadRun[]>('/api/workloads/runs');
}

export async function apiFetchRemoteSessions(): Promise<RemoteSession[]> {
  return getJson<RemoteSession[]>('/api/remote/sessions');
}

export async function apiFetchDevices(): Promise<DeviceInfo[]> {
  const data = await getJson<DeviceInfo[] | { devices: DeviceInfo[] }>('/api/devices');
  return Array.isArray(data) ? data : data.devices ?? [];
}

export async function apiFetchStats(): Promise<Stats[]> {
  const data = await getJson<Stats[] | Record<string, Stats> | { stats: Stats[] }>('/api/stats');
  if (Array.isArray(data)) return data;
  if ('stats' in data && Array.isArray(data.stats)) return data.stats;
  return Object.values(data);
}

export async function apiFetchWorkloads(): Promise<WorkloadItem[]> {
  const data = await getJson<WorkloadItem[] | WorkloadManifest[] | { workloads: WorkloadItem[] }>('/api/workloads');
  if (Array.isArray(data)) {
    return data.map((item) => {
      if ('manifest' in item) return item as WorkloadItem;
      return { manifest: item as WorkloadManifest, status: 'RUNNING' };
    });
  }
  if ('workloads' in data && Array.isArray(data.workloads)) {
    return data.workloads;
  }
  return [];
}

export async function apiPairDevice(addr: string, pin: string): Promise<{ ok: boolean; device?: DeviceInfo; error?: string }> {
  // The agent answers with the paired device (DeviceInfo), or an HTTP error with a detail message.
  try {
    const device = await postJson<DeviceInfo>('/api/pair', { addr: addr.trim(), pin: pin.trim() });
    return { ok: true, device };
  } catch (err: unknown) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

export async function apiStartWorkload(manifestPath: string): Promise<{ ok: boolean; workloadId?: string; error?: string }> {
  // The agent answers with the started workload's manifest.
  try {
    const manifest = await postJson<WorkloadManifest>('/api/workloads/start', { manifestPath: manifestPath.trim() });
    return { ok: true, workloadId: manifest.id };
  } catch (err: unknown) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

export async function apiStartMigration(
  workloadId: string,
  targetId: string,
  trigger: Trigger = 'user_command',
): Promise<MigrationStatus> {
  return postJson<MigrationStatus>('/api/migrations', { workloadId, targetId, trigger });
}

export async function apiAbortMigration(migrationId: string): Promise<MigrationStatus> {
  return postJson<MigrationStatus>(`/api/migrations/${migrationId}/abort`, {});
}

export async function apiStartRemote(workloadId: string, viewerId: string): Promise<RemoteSession> {
  return postJson<RemoteSession>('/api/remote/start', { workloadId, viewerId });
}

export async function apiConsentRemote(sessionId: string, allow: boolean): Promise<RemoteSession> {
  return postJson<RemoteSession>('/api/remote/consent', { sessionId, allow });
}

export async function apiStopRemote(sessionId: string): Promise<{ ok: boolean }> {
  return postJson<{ ok: boolean }>('/api/remote/stop', { sessionId });
}

export async function apiGetRemoteToken(sessionId: string): Promise<{ sessionId: string; token: string }> {
  return getJson<{ sessionId: string; token: string }>(`/api/remote/token/${sessionId}`);
}

export interface SettingsPrefs {
  mode: 'recommend' | 'auto';
  batteryLowPct: number;
  cpuHighPct: number;
  memHighPct: number;
  predictionWindowSec?: number;
  preferredLink?: 'auto' | 'cable' | 'wifi';
  chunkSizeKb?: number;
  checkpointChunkKb?: number;
  remoteConsent?: 'prompt' | 'auto_allow' | 'deny_all';
}

export interface DeviceHistorySummary {
  id: string;
  firstSeen: number;
  lastSeen: number;
  device: DeviceInfo;
  linkTypes: string[];
  migrationCount: number;
}

export async function apiGetHistoryDevices(): Promise<DeviceHistorySummary[]> {
  const data = await getJson<Array<DeviceHistorySummary | DeviceInfo>>('/api/history/devices');
  return data.map((d) => {
    if ('device' in d && d.device) {
      return d as DeviceHistorySummary;
    }
    const dev = d as DeviceInfo;
    return {
      id: dev.id,
      firstSeen: Date.now() - 3600000,
      lastSeen: Date.now(),
      device: dev,
      linkTypes: dev.addrs?.map((a) => a.link) ?? ['cable'],
      migrationCount: 0,
    };
  });
}

export async function apiGetHistoryMigrations(limit = 50, offset = 0): Promise<MigrationStatus[]> {
  return getJson<MigrationStatus[]>(`/api/history/migrations?limit=${limit}&offset=${offset}`);
}

export async function apiGetHistoryMigration(id: string): Promise<MigrationStatus> {
  return getJson<MigrationStatus>(`/api/history/migrations/${id}`);
}

export async function apiGetHistoryDecisions(limit = 100, offset = 0): Promise<DecisionLog[]> {
  return getJson<DecisionLog[]>(`/api/history/decisions?limit=${limit}&offset=${offset}`);
}

export async function apiGetSettings(): Promise<SettingsPrefs> {
  return getJson<SettingsPrefs>('/api/settings');
}

export async function apiPutSettings(prefs: Partial<SettingsPrefs>): Promise<SettingsPrefs> {
  return putJson<SettingsPrefs>('/api/settings', prefs);
}

export async function apiStatsOverride(
  deviceId: string,
  stats: {
    cpuPct?: number;
    memPct?: number;
    battery?: { pct: number; charging: boolean } | null;
    online?: boolean;
  } | null,
): Promise<{ ok: boolean }> {
  return postJson<{ ok: boolean }>('/api/dev/stats-override', { deviceId, stats });
}

// ---------------------------------------------------------------- pairing, discovery, ready-made apps

export interface NearbyDevice {
  deviceId: string;
  name: string;
  os: string;
  addr: string;
  lastSeen: number;
  paired: boolean;
}

export interface PairInfo {
  deviceId: string;
  name: string;
  pin?: string; // only given to the dashboard running on this same device
}

export interface AppTemplate {
  id: string;
  title: string;
  description: string;
  manifestPath: string | null;
  needs: 'projectPath' | null;
  available: boolean;
  detail?: string;
}

export async function apiFetchDiscovery(): Promise<NearbyDevice[]> {
  return getJson<NearbyDevice[]>('/api/discovery');
}

export async function apiFetchPairInfo(): Promise<PairInfo> {
  return getJson<PairInfo>('/api/pair');
}

export async function apiFetchApps(): Promise<AppTemplate[]> {
  return getJson<AppTemplate[]>('/api/apps');
}

export async function apiOpenVSCodeProject(projectPath: string): Promise<{ ok: boolean; manifest?: WorkloadManifest; error?: string }> {
  try {
    const manifest = await postJson<WorkloadManifest>('/api/apps/vscode', { projectPath: projectPath.trim() });
    return { ok: true, manifest };
  } catch (err: unknown) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

export async function apiStopWorkload(workloadId: string): Promise<WorkloadRun> {
  return postJson<WorkloadRun>(`/api/workloads/${encodeURIComponent(workloadId)}/stop`, {});
}
