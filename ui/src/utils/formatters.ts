import type { Arch, LinkType, OsName } from '@contract';

export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes < 0 || isNaN(bytes)) return '0 B';
  if (bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const safeI = Math.min(i, sizes.length - 1);
  return `${parseFloat((bytes / Math.pow(k, safeI)).toFixed(dm))} ${sizes[safeI]}`;
}

export function formatMb(mb: number, decimals = 1): string {
  if (mb < 0 || isNaN(mb)) return '0 MB';
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(decimals)} GB`;
  }
  return `${mb.toFixed(0)} MB`;
}

export function formatPercent(pct: number, decimals = 0): string {
  if (isNaN(pct)) return '0%';
  const clamped = Math.max(0, Math.min(100, pct));
  return `${clamped.toFixed(decimals)}%`;
}

export function formatMbps(mbps: number, decimals = 0): string {
  if (isNaN(mbps) || mbps < 0) return '0 Mbps';
  if (mbps >= 1000) {
    return `${(mbps / 1000).toFixed(1)} Gbps`;
  }
  return `${mbps.toFixed(decimals)} Mbps`;
}

export function formatMs(ms: number, decimals = 1): string {
  if (isNaN(ms) || ms < 0) return '0 ms';
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return `${ms.toFixed(decimals)} ms`;
}

export function formatDuration(sec: number): string {
  if (isNaN(sec) || sec < 0) return '0s';
  const s = Math.floor(sec);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

export function formatLinkType(link: LinkType | undefined | null): string {
  if (!link) return 'DISCONNECTED';
  switch (link) {
    case 'cable':
      return 'CABLE (Point-to-Point)';
    case 'wifi':
      return 'WIFI';
    case 'loopback':
      return 'LOOPBACK';
    default:
      return String(link).toUpperCase();
  }
}

export function formatArch(arch: Arch | string | undefined): string {
  if (!arch) return 'Unknown';
  if (arch === 'arm64') return 'ARM64 (Apple Silicon / AArch64)';
  if (arch === 'x86_64') return 'x86_64 (AMD64 / Intel)';
  return String(arch);
}

export function formatOs(os: OsName | string | undefined): string {
  if (!os) return 'Unknown OS';
  switch (os) {
    case 'macos':
      return 'macOS';
    case 'linux':
      return 'Linux';
    case 'windows':
      return 'Windows';
    default:
      return String(os);
  }
}

export function formatRelativeTime(ts: number): string {
  const ms = ts < 1e12 ? ts * 1000 : ts; // the agent sends seconds, the mock feeder milliseconds
  const diffSec = Math.floor((Date.now() - ms) / 1000);
  if (diffSec < 2) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const min = Math.floor(diffSec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  return `${hr}h ago`;
}

