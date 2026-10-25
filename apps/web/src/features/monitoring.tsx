"use client";

import { useQuery } from "@tanstack/react-query";
import { chartColors, LineSeriesChart } from "@/components/charts";
import { StatePanel } from "@/components/states";
import { Badge, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatWhen } from "@/lib/format";
import { useDashboard } from "@/components/dashboard-context";

const FIELD_LABELS: Record<string, string> = {
  temperature_c: "Temperature",
  precipitation_mm: "Rain",
  humidity_pct: "Humidity",
  wind_speed_kmh: "Wind",
  pressure_hpa: "Pressure",
};

type Report = {
  version?: string;
  algorithm?: string;
  limitations?: string;
  by_horizon?: { horizon_days: number; test: { mae: number; rmse: number } }[];
  by_location?: { location_id: number; horizon_days: number; mae: number; n: number }[];
  residuals_sample?: { target_time: string; residual: number; horizon_days: number }[];
  trained_at?: string;
};

export function MonitoringPage() {
  const { timeZone } = useDashboard();
  const query = useQuery({
    queryKey: ["monitoring"],
    queryFn: () =>
      api<{
        models: { name: string; version: string; algorithm: string; trained_at: string | null; train_start: string | null; train_end: string | null; limitations: string; status: string }[];
        reports: { temperature: Report | null; precipitation: Report | null; anomaly: Report | null };
        freshness: { latest_daily_observation: string | null; latest_hourly_observation: string | null; latest_ingestion_status: string | null };
        missing_data: Record<string, { missing_rate: number; rows: number }>;
        drift: null | { recent_14_day_mean: number; training_mean: number; difference: number; note: string };
        holdout_residuals: { target_time: string; residual: number }[] | null;
        operational_residuals: { valid_at: string; residual: number }[];
        operational_residual_note: string;
        retraining: string;
      }>("monitoring"),
  });
  if (query.isLoading) return <StatePanel status="loading" />;
  if (query.isError) return <StatePanel status="error" message={query.error instanceof ApiError ? query.error.message : "Monitoring unavailable."} onRetry={() => query.refetch()} />;
  const data = query.data;
  if (!data) return <StatePanel status="empty" message="Monitoring data is unavailable." />;
  const residuals = (data.holdout_residuals ?? []).slice(0, 80).map((row, index) => ({ label: String(index + 1), residual: row.residual }));
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Monitoring</h1>
        <p className="text-sm text-muted-foreground">{data.retraining}</p>
      </div>
      {data.models.length === 0 ? <StatePanel status="empty" message="No model has been trained yet." /> : null}
      <div className="grid w-full min-w-0 grid-cols-1 gap-3 lg:grid-cols-3">
        {data.models.map((model) => (
          <Card key={`${model.name}-${model.version}`} className="p-4">
            <Badge tone="accent">{model.status}</Badge>
            <h2 className="mt-2 font-medium">{model.name === "anomaly" ? "Unusual weather" : model.name === "precipitation" ? "Rain" : "Temperature"}</h2>
            <p className="text-xs text-muted-foreground">Trained {formatWhen(model.trained_at, timeZone)}</p>
            <p className="text-xs text-muted-foreground">Data {formatWhen(model.train_start, timeZone)} – {formatWhen(model.train_end, timeZone)}</p>
          </Card>
        ))}
      </div>
      <Card className="min-w-0 overflow-hidden p-4">
        <h2 className="mb-3 font-medium">How far predictions were off</h2>
        {residuals.length ? <LineSeriesChart label="Past prediction differences" data={residuals} lines={[{ key: "residual", name: "Difference", color: chartColors.primary }]} /> : <p className="text-sm text-muted-foreground">No past prediction differences are stored.</p>}
        <p className="mt-3 text-xs text-muted-foreground">{data.operational_residual_note} Operational pairs: {data.operational_residuals.length}.</p>
      </Card>
      <div className="grid w-full min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="font-medium">Performance by location</h2>
          <ul className="mt-2 text-sm">
            {(data.reports.temperature?.by_location ?? []).filter((row) => row.horizon_days === 1).map((row) => (
              <li key={row.location_id}>Location {row.location_id}: average error {row.mae.toFixed(2)} ({row.n} days)</li>
            ))}
          </ul>
        </Card>
        <Card className="p-4">
          <h2 className="font-medium">Drift and freshness</h2>
          {data.drift ? <p className="mt-2 text-sm">Recent mean {data.drift.recent_14_day_mean} vs training mean {data.drift.training_mean} (difference {data.drift.difference}). {data.drift.note}</p> : <p className="mt-2 text-sm">Drift indicator unavailable until a temperature model and recent observations both exist.</p>}
          <p className="mt-2 text-sm">Latest daily observation {formatWhen(data.freshness.latest_daily_observation, timeZone)}</p>
          <p className="text-sm">Latest hourly observation {formatWhen(data.freshness.latest_hourly_observation, timeZone)}</p>
          <p className="text-sm">Latest ingestion {data.freshness.latest_ingestion_status ?? "none"}</p>
        </Card>
        <Card className="p-4 lg:col-span-2">
          <h2 className="font-medium">Missing data, last 90 days</h2>
          <ul className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
            {Object.entries(data.missing_data).map(([key, value]) => (
              <li key={key}>{FIELD_LABELS[key] ?? key}: {(value.missing_rate * 100).toFixed(1)}% of {value.rows} rows</li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-muted-foreground">{data.reports.temperature?.limitations}</p>
          <p className="mt-2 text-xs text-muted-foreground">{data.reports.anomaly?.limitations}</p>
        </Card>
      </div>
    </>
  );
}
