"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowDown, ArrowUp, CloudSun, Droplets, Gauge, ThermometerSun } from "lucide-react";
import { useDashboard } from "@/components/dashboard-context";
import { StatePanel } from "@/components/states";
import { Badge, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatNumber, formatWhen } from "@/lib/format";

type TemperatureResponse = {
  model: { name: string; version: string; algorithm: string };
  predictions: {
    horizon_days: number;
    issued_at: string;
    target_time: string;
    predicted_temperature: number;
    lower: number | null;
    upper: number | null;
    persistence_baseline: number | null;
    statistical_baseline: number | null;
    interval: { test_coverage: number; note: string } | null;
    external_forecast: null | { temperature_min: number | null; temperature_max: number | null; note: string };
  }[];
  backtest: {
    label: string;
    by_horizon: {
      horizon_days: number;
      test: { mae: number; rmse: number; n: number };
      persistence_test: { mae: number };
      fourier_test: { mae: number };
      skill_vs_persistence: number | null;
    }[] | null;
  };
  external_benchmark: {
    available: boolean;
    note: string;
    by_lead_days: { lead_days: number; available: boolean; n?: number; temperature_mae_c?: number }[];
  };
  limitations: string | null;
  comparison_note: string;
  unit_labels: { temperature: string; precipitation: string };
};

const HORIZONS = [1, 2, 3, 7] as const;

type DailyWeatherResponse = {
  daily: {
    valid_at: string;
    precipitation_probability: number | null;
    precipitation: number | null;
  }[];
};

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof ThermometerSun;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="h-4 w-4 text-accent" aria-hidden />
        <span>{label}</span>
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </Card>
  );
}

export function ForecastPage() {
  const { locationId, units, timeZone } = useDashboard();
  const [horizon, setHorizon] = useState<number>(1);
  const temperature = useQuery({
    queryKey: ["predict-temperature", locationId, units],
    enabled: locationId != null,
    queryFn: () =>
      api<TemperatureResponse>("predictions/temperature", {
        method: "POST",
        body: JSON.stringify({ location_id: locationId, horizons: [...HORIZONS], units }),
      }),
  });
  const weather = useQuery({
    queryKey: ["current", locationId, units],
    enabled: locationId != null,
    queryFn: () => api<DailyWeatherResponse>(`weather/current?location_id=${locationId}&units=${units}`),
  });
  if (locationId == null || temperature.isLoading) return <StatePanel status="loading" />;
  if (temperature.isError) {
    return (
      <StatePanel
        status="error"
        message={temperature.error instanceof ApiError ? temperature.error.message : "Forecast unavailable."}
        onRetry={() => temperature.refetch()}
      />
    );
  }

  const data = temperature.data;
  const selected = data?.predictions.find((item) => item.horizon_days === horizon) ?? data?.predictions[0];
  const holdout = data?.backtest.by_horizon?.find((item) => item.horizon_days === selected?.horizon_days);
  const targetDay = selected?.target_time.slice(0, 10);
  const dailyOutlook = weather.data?.daily.find((item) => new Date(item.valid_at).toISOString().slice(0, 10) === targetDay);
  const unit = data?.unit_labels.temperature ?? "°C";
  const change = selected?.persistence_baseline == null
    ? null
    : selected.predicted_temperature - selected.persistence_baseline;
  const ChangeIcon = change != null && change < 0 ? ArrowDown : ArrowUp;
  const direction = change == null ? "Yesterday comparison unavailable" : Math.abs(change) < 0.05
    ? "Close to the previous day's average"
    : `${formatNumber(Math.abs(change))} ${unit} ${change > 0 ? "warmer" : "cooler"} than the previous day's average`;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Badge tone="accent">Forecast outlook</Badge>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">See what the next days may bring</h1>
          <p className="mt-1 text-sm text-muted-foreground">Explore the model estimate, daily outlook, and the evidence behind each lead time.</p>
        </div>
        <p className="text-sm text-muted-foreground">
          {selected ? formatWhen(selected.target_time, timeZone) : "Forecast date unavailable"}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Forecast horizon">
        <span className="mr-1 text-sm font-medium">Look ahead</span>
        {HORIZONS.map((days) => (
          <button
            key={days}
            type="button"
            aria-pressed={horizon === days}
            onClick={() => setHorizon(days)}
            className={`rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
              horizon === days
                ? "border-accent bg-accent text-white"
                : "border-border bg-white text-foreground hover:bg-muted"
            }`}
          >
            {days} day{days === 1 ? "" : "s"}
          </button>
        ))}
      </div>

      {selected ? (
        <>
          <Card className="overflow-hidden bg-white">
            <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="accent">WeatherIQ model estimate</Badge>
                  <span className="text-xs text-muted-foreground">{horizon}-day outlook</span>
                </div>
                <p className="mt-6 text-sm text-muted-foreground">Expected daily mean temperature</p>
                <p className="mt-1 text-6xl font-semibold tracking-tight sm:text-7xl">
                  {formatNumber(selected.predicted_temperature)}<span className="ml-2 text-3xl text-muted-foreground">{unit}</span>
                </p>
                <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                  <span className="inline-flex items-center gap-1.5 text-foreground">
                    <ChangeIcon className="h-4 w-4" aria-hidden />
                    {direction}
                  </span>
                  <span className="text-muted-foreground">Issued {formatWhen(selected.issued_at, timeZone)}</span>
                </div>
                <p className="mt-5 max-w-xl text-xs leading-relaxed text-muted-foreground">{data?.limitations}</p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <div className="rounded-2xl border border-border bg-muted/50 p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <ThermometerSun className="h-4 w-4" aria-hidden />
                    Model range
                  </div>
                  <p className="mt-2 text-2xl font-semibold">
                    {formatNumber(selected.lower)} <span className="text-muted-foreground">to</span> {formatNumber(selected.upper)} {unit}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {selected.interval
                      ? `Covered actual temperatures on ${(selected.interval.test_coverage * 100).toFixed(0)}% of past test days.`
                      : "Historical range check unavailable."}
                  </p>
                </div>
                <div className="rounded-2xl border border-border bg-muted/50 p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <CloudSun className="h-4 w-4" aria-hidden />
                    Daily range
                  </div>
                  {selected.external_forecast ? (
                    <>
                      <p className="mt-2 text-2xl font-semibold">
                        {formatNumber(selected.external_forecast.temperature_min)} <span className="text-muted-foreground">to</span> {formatNumber(selected.external_forecast.temperature_max)} {unit}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">Low to high</p>
                    </>
                  ) : <p className="mt-2 text-sm text-muted-foreground">No daily outlook is stored for this date.</p>}
                </div>
              </div>
            </div>
          </Card>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              icon={Droplets}
              label="Rain probability"
              value={dailyOutlook?.precipitation_probability == null ? "—" : `${dailyOutlook.precipitation_probability.toFixed(0)}%`}
              detail={dailyOutlook
                ? dailyOutlook.precipitation == null
                  ? "Daily outlook · amount unavailable"
                  : `Daily outlook · ${formatNumber(dailyOutlook.precipitation)} ${data?.unit_labels.precipitation} expected`
                : weather.isError
                  ? "Rain outlook unavailable"
                  : "No rain estimate for this date"}
            />
            <MetricCard
              icon={Gauge}
              label="Past mean error"
              value={holdout ? `${holdout.test.mae.toFixed(2)} °C` : "—"}
              detail={holdout ? `MAE on ${holdout.test.n} held-out days · lower is better` : "No matching backtest"}
            />
            <MetricCard
              icon={ThermometerSun}
              label="Past error spread"
              value={holdout ? `${holdout.test.rmse.toFixed(2)} °C` : "—"}
              detail="RMSE on the chronological holdout"
            />
            <MetricCard
              icon={change != null && change < 0 ? ArrowDown : ArrowUp}
              label="Versus yesterday"
              value={change == null ? "—" : `${change > 0 ? "+" : ""}${formatNumber(change)} ${unit}`}
              detail="Difference from the persistence baseline"
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
            <Card className="p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold">How reliable has this lead been?</h2>
                  <p className="mt-1 text-xs text-muted-foreground">{data?.backtest.label} Errors are in °C; lower is better.</p>
                </div>
                <Badge tone={holdout?.skill_vs_persistence != null && holdout.skill_vs_persistence > 0 ? "ok" : "amber"}>
                  {holdout?.skill_vs_persistence == null
                    ? "Baseline comparison unavailable"
                    : holdout.skill_vs_persistence > 0
                      ? `${(holdout.skill_vs_persistence * 100).toFixed(2)}% less error than yesterday`
                      : holdout.skill_vs_persistence < 0
                        ? `${(Math.abs(holdout.skill_vs_persistence) * 100).toFixed(2)}% more error than yesterday`
                        : "Same error as yesterday"}
                </Badge>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {(data?.backtest.by_horizon ?? []).map((row) => (
                  <button
                    key={row.horizon_days}
                    type="button"
                    onClick={() => setHorizon(row.horizon_days)}
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      row.horizon_days === selected.horizon_days
                        ? "border-accent bg-accent/5"
                        : "border-border hover:bg-muted"
                    }`}
                  >
                    <span className="block text-xs text-muted-foreground">{row.horizon_days} day{row.horizon_days === 1 ? "" : "s"}</span>
                    <span className="mt-1 block text-lg font-semibold">{row.test.mae.toFixed(2)}°</span>
                    <span className="text-xs text-muted-foreground">MAE · {row.test.n} days</span>
                  </button>
                ))}
              </div>
              <p className="mt-4 text-xs text-muted-foreground">A positive skill means lower average error than repeating yesterday; a negative skill means higher error. Past performance does not guarantee future results.</p>
            </Card>

            <Card className="p-4 sm:p-5">
              <h2 className="font-semibold">Forecast archive benchmark</h2>
              <p className="mt-1 text-xs text-muted-foreground">{data?.external_benchmark.note}</p>
              <div className="mt-3 divide-y divide-border">
                {(data?.external_benchmark.by_lead_days ?? []).map((row) => (
                  <div key={row.lead_days} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <span>{row.lead_days}-day lead</span>
                    <span className="text-right font-medium">
                      {row.available && row.temperature_mae_c != null
                        ? `${row.temperature_mae_c.toFixed(2)} °C MAE · ${row.n} matched days`
                        : "Not enough matched data"}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          </div>

        </>
      ) : <StatePanel status="empty" message="The model did not return a prediction for this lead time." />}
    </div>
  );
}
