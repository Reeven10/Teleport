import type { BusEvent } from '@contract';

// Same origin by default (agent-served build or the Vite proxy). ?agent=http://127.0.0.1:8766 targets another agent.
const agentParam = new URLSearchParams(window.location.search).get('agent');
export const agentBase = agentParam ?? '';

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${agentBase}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return (await res.json()) as T;
}

export function connectEvents(onEvent: (e: BusEvent) => void): () => void {
  const base = agentBase || window.location.origin;
  const ws = new WebSocket(`${base.replace(/^http/, 'ws')}/ws/events`);
  ws.onmessage = (m: MessageEvent<string>) => onEvent(JSON.parse(m.data) as BusEvent);
  return () => ws.close();
}
