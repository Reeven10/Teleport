import { describe, expect, it } from 'vitest';
import {
  formatArch,
  formatBytes,
  formatDuration,
  formatLinkType,
  formatMb,
  formatMbps,
  formatMs,
  formatOs,
  formatPercent,
  formatRelativeTime,
} from '@/utils/formatters.ts';

describe('formatters', () => {
  it('formats bytes into human readable units', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1024)).toBe('1 KB');
    expect(formatBytes(1024 * 1024)).toBe('1 MB');
    expect(formatBytes(1024 * 1024 * 1024)).toBe('1 GB');
  });

  it('formats megabytes into GB or MB', () => {
    expect(formatMb(500)).toBe('500 MB');
    expect(formatMb(1024)).toBe('1.0 GB');
    expect(formatMb(16384)).toBe('16.0 GB');
  });

  it('formats percentages within 0-100 bounds', () => {
    expect(formatPercent(50)).toBe('50%');
    expect(formatPercent(-10)).toBe('0%');
    expect(formatPercent(120)).toBe('100%');
    expect(formatPercent(33.333, 1)).toBe('33.3%');
  });

  it('formats network throughput Mbps / Gbps', () => {
    expect(formatMbps(150)).toBe('150 Mbps');
    expect(formatMbps(1000)).toBe('1.0 Gbps');
    expect(formatMbps(2500)).toBe('2.5 Gbps');
  });

  it('formats latency milliseconds', () => {
    expect(formatMs(1.23)).toBe('1.2 ms');
    expect(formatMs(1250)).toBe('1.25 s');
  });

  it('formats durations in seconds/minutes/hours', () => {
    expect(formatDuration(42)).toBe('42s');
    expect(formatDuration(125)).toBe('2m 5s');
    expect(formatDuration(3665)).toBe('1h 1m');
  });

  it('formats link types and descriptions', () => {
    expect(formatLinkType('cable')).toContain('CABLE');
    expect(formatLinkType('wifi')).toBe('WIFI');
    expect(formatLinkType(null)).toBe('DISCONNECTED');
  });

  it('formats architecture and OS tags', () => {
    expect(formatArch('arm64')).toContain('ARM64');
    expect(formatArch('x86_64')).toContain('x86_64');
    expect(formatOs('macos')).toBe('macOS');
    expect(formatOs('linux')).toBe('Linux');
    expect(formatOs('windows')).toBe('Windows');
  });

  it('formats relative timestamps', () => {
    const now = Date.now();
    expect(formatRelativeTime(now - 500)).toBe('just now');
    expect(formatRelativeTime(now - 15000)).toBe('15s ago');
  });
});

