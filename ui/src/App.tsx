// Placeholder dashboard (P4 replaces it): agent health plus the live event stream.
import { useEffect, useState } from 'react';
import type { BusEvent, Stats } from '@contract';
import { connectEvents, getJson } from './api.ts';

interface Health { ok: boolean; deviceId: string; name: string; port: number; simProfile: string | null }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [events, setEvents] = useState(0);

  useEffect(() => {
    getJson<Health>('/api/health').then(setHealth).catch(() => setHealth(null));
    return connectEvents((e: BusEvent) => {
      setEvents((n) => n + 1);
      if (e.t === 'stats.update') setStats(e.stats);
    });
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 p-8 text-slate-100">
      <h1 className="text-3xl font-bold">Teleport</h1>
      <p className="mt-2 text-slate-400">
        {health ? `${health.name} (${health.deviceId}) on :${health.port}` : 'agent not reachable'}
      </p>
      {stats && (
        <p className="mt-4">
          CPU {stats.cpuPct.toFixed(0)}% · RAM {stats.memPct.toFixed(0)}%
          {stats.battery ? ` · Battery ${stats.battery.pct.toFixed(0)}%` : ''}
          {stats.simulated && <span className="ml-2 rounded bg-amber-500 px-2 text-black">SIMULATED</span>}
        </p>
      )}
      <p className="mt-2 text-sm text-slate-500">{events} events received</p>
    </main>
  );
}
