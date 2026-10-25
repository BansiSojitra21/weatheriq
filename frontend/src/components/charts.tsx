"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Point = Record<string, string | number | null>;
type Series = { key: string; name: string; color: string };

export const chartColors = {
  primary: "#6366F1",
  secondary: "#94A3B8",
  tertiary: "#14B8A6",
} as const;

export function LineSeriesChart({
  data,
  lines,
  label,
}: {
  data: Point[];
  lines: Series[];
  label: string;
}) {
  return (
    <div className="h-72 w-full min-w-0 max-w-full overflow-hidden" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} minTickGap={24} />
          <YAxis tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} width={46} />
          <Tooltip shared={false} />
          <Legend />
          {lines.map((line) => (
            <Line
              key={line.key}
              type="monotone"
              dataKey={line.key}
              name={line.name}
              stroke={line.color}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarSeriesChart({
  data,
  bars,
  label,
}: {
  data: Point[];
  bars: Series[];
  label: string;
}) {
  return (
    <div className="h-72 w-full min-w-0 max-w-full overflow-hidden" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} />
          <YAxis tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} width={46} />
          <Tooltip shared={false} />
          <Legend />
          {bars.map((bar) => (
            <Bar key={bar.key} dataKey={bar.key} name={bar.name} fill={bar.color} radius={3} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
