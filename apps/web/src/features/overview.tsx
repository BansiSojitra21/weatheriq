"use client";

import { useQuery } from "@tanstack/react-query";
import { chartColors, LineSeriesChart } from "@/components/charts";
import { useDashboard } from "@/components/dashboard-context";
import { StatePanel } from "@/components/states";
import { Badge, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatNumber, formatWhen } from "@/lib/format";

type CurrentResponse = {
  observation: null | {
    temperature: number | null;
    apparent_temperature: number | null;
    humidity: number | null;
    precipitation: number | null;
    wind_speed: number | null;
    wind_direction: string | null;
    pressure: number | null;
    cloud_cover: number | null;
    condition: string | null;
    observed_at: string;
    retrieved_at: string;
    kind: string;
  };
  today_forecast: null | {
    kind: string;
    temperature_min: number | null;
    temperature_max: number | null;
    sunrise: string | null;
    sunset: string | null;
    retrieved_at: string | null;
  };
  hourly: { valid_at: string; temperature: number | null; precipitation: number | null; precipitation_probability: number | null }[];
  daily: { valid_at: string; temperature_min: number | null; temperature_max: number | null; precipitation: number | null; condition: string | null; precipitation_probability: number | null }[];
  freshness: { retrieved_at: string | null; stale: boolean | null };
  unit_labels: { temperature: string; precipitation: string; wind: string; pressure: string };
};

function Metric({
  label,
  value,
  unit,
  digits = 1,
}: {
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  digits?: number;
}) {
  const text = typeof value === "number" ? formatNumber(value, digits) : value || "Unavailable";
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-2 text-xl font-semibold sm:text-2xl">
        {text}
        {typeof value === "number" && unit ? <span className="ml-1 text-sm font-normal text-muted-foreground">{unit}</span> : null}
      </p>
    </Card>
  );
}

export function OverviewPage() {
  const { locationId, units, timeZone, location } = useDashboard();
  const query = useQuery({
    queryKey: ["current", locationId, units],
    enabled: locationId != null,
    queryFn: () => api<CurrentResponse>(`weather/current?location_id=${locationId}&units=${units}`),
  });
  if (locationId == null) return <StatePanel status="loading" />;
  if (query.isLoading) return <StatePanel status="loading" />;
  if (query.isError) {
    return (
      <StatePanel
        status="error"
        message={query.error instanceof ApiError ? query.error.message : "Current weather could not be loaded."}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (!data?.observation && data?.daily.length === 0) {
    return <StatePanel status="empty" message="No weather has been ingested for this location yet. Run scripts/bootstrap.py." />;
  }
  const labels = data?.unit_labels;
  const hourly = (data?.hourly ?? []).map((row) => ({
    label: formatWhen(row.valid_at, timeZone),
    temperature: row.temperature,
    precipitation: row.precipitation,
  }));
  return (
    <>
      <Card className="p-5 sm:p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Overview</h1>
            <p className="text-sm text-muted-foreground">{location?.name} current conditions and the weather forecast.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">Observation</Badge>
            {data?.freshness.stale ? <Badge tone="amber">Stale</Badge> : <Badge tone="ok">Freshness checked</Badge>}
            <span className="text-xs text-muted-foreground">Updated {formatWhen(data?.freshness.retrieved_at, timeZone)}</span>
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{data?.observation?.condition ?? "Current condition unavailable"}</p>
            <p className="mt-1 text-4xl font-semibold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
              {formatNumber(data?.observation?.temperature)}
              <span className="ml-1 text-lg font-medium text-accent sm:text-xl">{labels?.temperature}</span>
            </p>
          </div>
          <Badge className="self-start" tone="accent">Current conditions</Badge>
        </div>
      </Card>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Feels like" value={data?.observation?.apparent_temperature} unit={labels?.temperature} />
        <Metric label="Humidity" value={data?.observation?.humidity} unit="%" />
        <Metric label="Wind" value={data?.observation?.wind_speed} unit={labels?.wind} />
        <Metric label="Direction" value={data?.observation?.wind_direction} />
        <Metric
          label="Precipitation"
          value={data?.observation?.precipitation}
          unit={labels?.precipitation}
          digits={units === "imperial" ? 3 : 1}
        />
        <Metric label="Pressure" value={data?.observation?.pressure} unit={labels?.pressure} />
        <Metric label="Cloud cover" value={data?.observation?.cloud_cover} unit="%" />
        <Metric
          label="Forecast high / low"
          value={
            data?.today_forecast
              ? `${formatNumber(data.today_forecast.temperature_max)} / ${formatNumber(data.today_forecast.temperature_min)}`
              : null
          }
        />
      </div>
      <div className="grid w-full min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <Card className="min-w-0 overflow-hidden p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-medium">Next 48 hours</h2>
            <Badge tone="accent">Weather forecast</Badge>
          </div>
          {hourly.length ? (
            <LineSeriesChart
              label="Hourly forecast temperature"
              data={hourly}
              lines={[{ key: "temperature", name: `Temperature (${labels?.temperature})`, color: chartColors.primary }]}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Hourly forecast is unavailable.</p>
          )}
        </Card>
        <Card className="p-4">
          <h2 className="font-medium">Sunrise and sunset</h2>
          <dl className="mt-3 grid gap-2 text-sm">
            <div className="flex justify-between gap-3"><dt>Sunrise</dt><dd>{formatWhen(data?.today_forecast?.sunrise, timeZone)}</dd></div>
            <div className="flex justify-between gap-3"><dt>Sunset</dt><dd>{formatWhen(data?.today_forecast?.sunset, timeZone)}</dd></div>
          </dl>
          <p className="mt-4 text-xs text-muted-foreground">Sunrise and sunset come from the daily forecast, not from a local sensor.</p>
        </Card>
      </div>
      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">Next seven days</h2>
          <Badge tone="accent">Weather forecast</Badge>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          {(data?.daily ?? []).map((day) => (
            <div key={day.valid_at} className="rounded-2xl border border-border bg-muted/60 p-3">
              <p className="text-sm font-medium">{formatWhen(day.valid_at, timeZone).split(",")[0]}</p>
              <p className="mt-2 text-lg">{formatNumber(day.temperature_max)} / {formatNumber(day.temperature_min)}</p>
              <p className="text-xs text-muted-foreground">{day.condition ?? "Condition unavailable"}</p>
              <p className="text-xs text-muted-foreground">
                {formatNumber(day.precipitation, units === "imperial" ? 3 : 1)} {labels?.precipitation}
              </p>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
