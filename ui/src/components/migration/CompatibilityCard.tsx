import type { DeviceInfo, FeasibilityResult, LinkQuality, Stats, WorkloadManifest } from '@contract';
import { formatMb, formatOs } from '../../utils/formatters.ts';
import { Icon } from '../ui/Icon.tsx';

type Verdict = 'ok' | 'warn' | 'block' | 'info';

interface Row {
  label: string;
  needs: string;
  here: string;
  there: string;
  verdict: Verdict;
}

function versionAtLeast(have: string | undefined, want: string): boolean {
  if (!have) return false;
  const a = have.split(/[.\-+]/).map((n) => parseInt(n, 10) || 0);
  const b = want.split(/[.\-+]/).map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) > (b[i] ?? 0);
  }
  return true;
}

function rows(m: WorkloadManifest, src?: DeviceInfo, srcStats?: Stats, dst?: DeviceInfo, dstStats?: Stats): Row[] {
  if (!dst) return [];
  const rt = m.runtime;
  const out: Row[] = [
    {
      label: 'System',
      needs: `${m.os.map(formatOs).join(' / ')} · ${m.arch.join(' / ')}`,
      here: src ? `${formatOs(src.os)} · ${src.arch}` : '—',
      there: `${formatOs(dst.os)} · ${dst.arch}`,
      verdict: m.os.includes(dst.os) && m.arch.includes(dst.arch) ? 'ok' : 'block',
    },
    {
      label: rt.name === 'node' ? 'Node.js' : rt.name === 'python' ? 'Python' : rt.name,
      needs: `${rt.minVersion} or newer`,
      here: src?.runtimes[rt.name] ?? 'not installed',
      there: dst.runtimes[rt.name] ?? 'not installed',
      verdict: versionAtLeast(dst.runtimes[rt.name], rt.minVersion) ? 'ok' : 'block',
    },
  ];
  for (const lib of m.libs) {
    out.push({
      label: lib === 'vscode' ? 'VS Code' : lib,
      needs: 'installed',
      here: src?.libs.includes(lib) ? 'installed' : 'missing',
      there: dst.libs.includes(lib) ? 'installed' : 'missing',
      verdict: dst.libs.includes(lib) ? 'ok' : 'block',
    });
  }
  out.push(
    {
      label: 'CPU',
      needs: `${m.minCpuCores} core${m.minCpuCores === 1 ? '' : 's'}`,
      here: src ? `${src.cpuCores} cores${srcStats ? ` · ${Math.round(srcStats.cpuPct)}% busy` : ''}` : '—',
      there: `${dst.cpuCores} cores${dstStats ? ` · ${Math.round(dstStats.cpuPct)}% busy` : ''}`,
      verdict: dst.cpuCores < m.minCpuCores ? 'block' : (dstStats?.cpuPct ?? 0) > 85 ? 'warn' : 'ok',
    },
    {
      label: 'Free memory',
      needs: formatMb(m.minRamMb),
      here: srcStats ? formatMb(srcStats.memFreeMb) : src ? formatMb(src.ramMb) : '—',
      there: dstStats ? formatMb(dstStats.memFreeMb) : formatMb(dst.ramMb),
      verdict: (dstStats?.memFreeMb ?? dst.ramMb) >= m.minRamMb ? 'ok' : 'block',
    },
    {
      label: 'Free disk',
      needs: formatMb(m.minDiskMb),
      here: srcStats ? formatMb(srcStats.diskFreeMb) : src ? formatMb(src.diskFreeMb) : '—',
      there: formatMb(dstStats?.diskFreeMb ?? dst.diskFreeMb),
      verdict: (dstStats?.diskFreeMb ?? dst.diskFreeMb) >= m.minDiskMb ? 'ok' : 'block',
    },
  );
  if (m.needsGpu) {
    out.push({
      label: 'GPU',
      needs: 'required',
      here: src?.gpu ?? 'none',
      there: dst.gpu ?? 'none',
      verdict: dst.gpu ? 'ok' : 'block',
    });
  }
  const battery = dstStats?.battery;
  out.push({
    label: 'Power',
    needs: 'stable',
    here: srcStats?.battery ? `${Math.round(srcStats.battery.pct)}%${srcStats.battery.charging ? ' charging' : ''}` : 'mains',
    there: battery ? `${Math.round(battery.pct)}%${battery.charging ? ' charging' : ''}` : 'mains',
    verdict: battery && !battery.charging && battery.pct < 20 ? 'warn' : 'ok',
  });
  return out;
}

const MARK: Record<Verdict, { icon: 'check' | 'alert' | 'x' | 'link'; tone: string }> = {
  ok: { icon: 'check', tone: 'text-ok' },
  warn: { icon: 'alert', tone: 'text-warn' },
  block: { icon: 'x', tone: 'text-bad' },
  info: { icon: 'link', tone: 'text-muted' },
};

interface CompatibilityCardProps {
  manifest: WorkloadManifest;
  source?: DeviceInfo;
  sourceStats?: Stats;
  target?: DeviceInfo;
  targetStats?: Stats;
  link: LinkQuality | null;
  feasibility: FeasibilityResult | null;
  loading: boolean;
}

/** Both laptops side by side against what the workload needs, then Teleport's own decision. */
export function CompatibilityCard({
  manifest,
  source,
  sourceStats,
  target,
  targetStats,
  link,
  feasibility,
  loading,
}: CompatibilityCardProps) {
  const table = rows(manifest, source, sourceStats, target, targetStats);
  const passed = table.filter((r) => r.verdict === 'ok').length;
  const decision = feasibility?.decision;
  const headline =
    decision === 'MIGRATE'
      ? 'Compatible: ready to migrate'
      : decision === 'REMOTE_ACCESS'
        ? 'Not a full match: remote access instead'
        : decision === 'STAY'
          ? 'Better to stay on this laptop'
          : 'Checking compatibility...';

  return (
    <div data-testid="compatibility-card" className="rounded-2xl border border-line bg-surface">
      <div className="flex items-start justify-between gap-3 border-b border-line p-5">
        <div>
          <p className="tp-label">Compatibility</p>
          <p
            className={`mt-1 font-serif text-2xl leading-tight ${
              decision === 'MIGRATE' ? 'text-ink' : decision ? 'text-warn' : 'text-faint'
            }`}
          >
            {headline}
          </p>
          <p className="mt-1 text-xs text-muted">
            {passed} of {table.length} checks match
            {feasibility && feasibility.estTransferSec > 0 && ` · about ${Math.max(1, Math.round(feasibility.estTransferSec))} s to transfer`}
            {feasibility && feasibility.estInterruptionMs > 0 && `, paused about ${Math.round(feasibility.estInterruptionMs)} ms`}
          </p>
        </div>
        {decision && (
          <span
            data-testid="compatibility-decision"
            className={`tp-chip shrink-0 font-mono ${decision === 'MIGRATE' ? 'border-ok/40 text-ok' : 'border-warn/40 text-warn'}`}
          >
            {decision}
          </span>
        )}
      </div>

      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[10.5px] text-faint">
            <th className="py-2 pl-5 font-normal">Needs</th>
            <th className="py-2 font-normal" />
            <th className="py-2 font-normal">{source?.name ?? 'This laptop'}</th>
            <th className="py-2 font-normal">{target?.name ?? 'Target'}</th>
            <th className="py-2 pr-5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-line border-t border-line">
          {table.map((r) => (
            <tr key={r.label}>
              <td className="py-2 pl-5 text-ink">{r.label}</td>
              <td className="py-2 pr-3 text-faint">{r.needs}</td>
              <td className="py-2 pr-3 font-mono text-muted">{r.here}</td>
              <td className={`py-2 pr-3 font-mono ${r.verdict === 'ok' ? 'text-ink' : MARK[r.verdict].tone}`}>{r.there}</td>
              <td className="py-2 pr-5 text-right">
                <Icon name={MARK[r.verdict].icon} className={`ml-auto h-3.5 w-3.5 ${MARK[r.verdict].tone}`} />
              </td>
            </tr>
          ))}
          <tr>
            <td className="py-2 pl-5 text-ink">Link</td>
            <td className="py-2 pr-3 text-faint">encrypted</td>
            <td colSpan={2} className="py-2 pr-3 font-mono text-muted">
              {link ? `${link.link} · ${Math.round(link.rttMs)} ms · ${Math.round(link.mbps)} Mbps · ${link.lossPct.toFixed(1)}% loss` : 'not measured yet'}
            </td>
            <td className="py-2 pr-5 text-right">
              <Icon name="link" className="ml-auto h-3.5 w-3.5 text-muted" />
            </td>
          </tr>
        </tbody>
      </table>

      {(loading || (feasibility && feasibility.reasons.some((r) => r.severity !== 'pass'))) && (
        <ul className="space-y-1 border-t border-line px-5 py-3 text-xs">
          {loading && <li className="text-faint">Asking Teleport to evaluate both laptops...</li>}
          {feasibility?.reasons
            .filter((r) => r.severity !== 'pass')
            .map((r) => (
              <li key={r.code + r.text} className="flex items-start gap-2">
                <Icon name={r.severity === 'block' ? 'x' : 'alert'} className={`mt-px h-3.5 w-3.5 shrink-0 ${r.severity === 'block' ? 'text-bad' : 'text-warn'}`} />
                <span className="text-ink">{r.text}</span>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
