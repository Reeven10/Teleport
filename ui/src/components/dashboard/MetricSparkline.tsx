import { memo } from 'react';
import { Area, AreaChart, ResponsiveContainer, YAxis } from 'recharts';
import type { MetricHistoryPoint } from '../../store/types.ts';

interface MetricSparklineProps {
  data: MetricHistoryPoint[];
  dataKey: 'cpuPct' | 'memPct' | 'diskFreeMb';
  color?: string;
  domain?: [number, number];
  height?: number;
}

export const MetricSparkline = memo(function MetricSparkline({
  data,
  dataKey,
  color = '#38bdf8',
  domain = [0, 100],
  height = 42,
}: MetricSparklineProps) {
  if (!data || data.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded bg-slate-100/50 text-xs text-slate-400 dark:bg-slate-800/40 dark:text-slate-500"
        style={{ height }}
      >
        Waiting for stream...
      </div>
    );
  }

  const gradientId = `gradient-${dataKey}-${color.replace('#', '')}`;

  return (
    <div style={{ height, width: '100%', minWidth: 100 }} className="relative overflow-hidden">
      <ResponsiveContainer width="100%" height={height} minWidth={100} minHeight={height}>
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.4} />
              <stop offset="95%" stopColor={color} stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <YAxis hide domain={domain} />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={1.5}
            fillOpacity={1}
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
});
