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

/** A thin 60-second trace with a flat, faint fill: no gradient, no axes. */
export const MetricSparkline = memo(function MetricSparkline({
  data,
  dataKey,
  color = 'var(--tp-ink)',
  domain = [0, 100],
  height = 40,
}: MetricSparklineProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center border-b border-dashed border-line text-[10.5px] text-faint" style={{ height }}>
        waiting for data
      </div>
    );
  }

  return (
    <div style={{ height, width: '100%', minWidth: 100 }} className="relative overflow-hidden border-b border-line">
      <ResponsiveContainer width="100%" height={height} minWidth={100} minHeight={height}>
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <YAxis hide domain={domain} />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={1.25}
            fill={color}
            fillOpacity={0.06}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
});
