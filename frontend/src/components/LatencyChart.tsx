import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { format, parseISO } from "date-fns";
import { CheckResultResponse } from "../api/client";

interface DataPoint {
  time: string;
  p50: number | null;
  p99: number | null;
  status: string;
}

function buildChartData(checks: CheckResultResponse[]): DataPoint[] {
  // Group into 5-minute buckets; compute p50/p99 per bucket
  const buckets: Record<string, number[]> = {};
  const bucketStatus: Record<string, string[]> = {};

  for (const c of checks) {
    const d = parseISO(c.checked_at);
    const bucket = format(d, "HH:mm");  // round to minute for display
    if (!buckets[bucket]) { buckets[bucket] = []; bucketStatus[bucket] = []; }
    if (c.response_ms != null) buckets[bucket].push(c.response_ms);
    bucketStatus[bucket].push(c.status);
  }

  return Object.entries(buckets)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([time, vals]) => {
      const sorted = [...vals].sort((a, b) => a - b);
      const p50 = sorted.length ? sorted[Math.floor(sorted.length * 0.5)] ?? null : null;
      const p99 = sorted.length ? sorted[Math.floor(sorted.length * 0.99)] ?? null : null;
      return { time, p50, p99, status: bucketStatus[time].join(",") };
    });
}

interface Props {
  checks: CheckResultResponse[];
  height?: number;
}

export function LatencyChart({ checks, height = 240 }: Props) {
  const data = buildChartData([...checks].reverse());

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 11 }} />
        <YAxis tick={{ fill: "#64748b", fontSize: 11 }} unit="ms" />
        <Tooltip
          contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
          labelStyle={{ color: "#94a3b8" }}
          formatter={(v: number) => [`${v}ms`]}
        />
        <Legend wrapperStyle={{ fontSize: "12px", color: "#94a3b8" }} />
        <Line type="monotone" dataKey="p50" stroke="#22c55e" dot={false} strokeWidth={2} name="p50" />
        <Line type="monotone" dataKey="p99" stroke="#f59e0b" dot={false} strokeWidth={2} name="p99" strokeDasharray="4 2" />
      </LineChart>
    </ResponsiveContainer>
  );
}
