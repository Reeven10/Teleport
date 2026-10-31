import type { BusEvent, DeviceInfo, Stats, WorkloadManifest } from '@contract';
import type { WorkloadItem } from './store/types.ts';

const agentParam = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('agent') : null;
export const agentBase = agentParam ?? '';

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${agentBase}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return (await res.json()) as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${agentBase}${path}`, {
    method: 'POST',
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
  return postJson<{ ok: boolean; device?: DeviceInfo; error?: string }>('/api/pair', { addr, pin });
}

export async function apiStartWorkload(manifestPath: string): Promise<{ ok: boolean; workloadId?: string; error?: string }> {
  return postJson<{ ok: boolean; workloadId?: string; error?: string }>('/api/workloads/start', { manifestPath });
}
