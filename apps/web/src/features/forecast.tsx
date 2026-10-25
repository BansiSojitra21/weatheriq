"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { BarSeriesChart, chartColors } from "@/components/charts";
import { useDashboard } from "@/components/dashboard-context";
import { StatePanel } from "@/components/states";
import { Badge, Card, Select } from "@/components/ui";
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
  backtest: { label: string; by_horizon: { horizon_days: number; test: { mae: number; rmse: number; n: number }; persistence_test: { mae: number }; fourier_test: { mae: number }; skill_vs_persistence: number | null }[] | null };
  external_benchmark: { available: boolean; note: string; by_lead_days: { lead_days: number; available: boolean; n?: number; temperature_mae_c?: number }[] };
  limitations: string | null;
  comparison_note: string;
  unit_labels: { temperature: string; precipitation: string };
};

type PrecipitationResponse = {
  model: { version: string; algorithm: string };
  predictions: { horizon_days: number; target_time: string; precipitation_probability: number; precipitation_amount: number; decision_threshold: number }[];
  limitations: string | null;
};

export function ForecastPage() {
  const { locationId, units, timeZone } = useDashboard();
  const [horizon, setHorizon] = useState("1");
  const temperature = useQuery({
    queryKey: ["predict-temperature", locationId, units],
    enabled: locationId != null,
    queryFn: () =>
      api<TemperatureResponse>("predictions/temperature", {
        method: "POST",
        body: JSON.stringify({ location_id: locationId, horizons: [1, 2, 3, 7], units }),
      }),
  });
  const precipitation = useQuery({
    queryKey: ["predict-precipitation", locationId, units],
    enabled: locationId != null,
    queryFn: () =>
      api<PrecipitationResponse>("predictions/precipitation", {
        method: "POST",
        body: JSON.stringify({ location_id: locationId, horizons: [1, 2, 3], units }),
      }),
  });
  if (locationId == null || temperature.isLoading) return <StatePanel status="loading" />;
  if (temperature.isError) {
    return <StatePanel status="error" message={temperature.error instanceof ApiError ? temperature.error.message : "Forecast unavailable."} onRetry={() => temperature.refetch()} />;
  }
  const selected = temperature.data?.predictions.find((item) => String(item.horizon_days) === horizon) ?? temperature.data?.predictions[0];
  const holdout = temperature.data?.backtest.by_horizon ?? [];
  const precip = precipitation.data?.predictions.find((item) => String(item.horizon_days) === horizon);
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Forecast</h1>
          <p className="text-sm text-muted-foreground">The prediction is separate from the weather forecast.</p>
        </div>
        <Select className="w-full sm:w-auto" aria-label="Forecast horizon" value={horizon} onChange={(event) => setHorizon(event.target.value)}>
          {["1", "2", "3", "7"].map((item) => <option key={item} value={item}>{item} day{item === "1" ? "" : "s"}</option>)}
        </Select>
      </div>
      {selected ? (
        <div className="grid w-full min-w-0 grid-cols-1 items-stretch gap-4 lg:grid-cols-3">
          <Card className="flex h-full flex-col p-4 sm:p-5">
            <Badge className="self-start" tone="accent">Prediction</Badge>
            <p className="mt-4 text-3xl font-semibold sm:text-4xl">{formatNumber(selected.predicted_temperature)} {temperature.data?.unit_labels.temperature}</p>
            <dl className="mt-4 grid gap-3 text-sm">
              <div className="flex items-baseline justify-between gap-3 border-t border-border pt-3">
                <dt className="text-muted-foreground">Issued</dt>
                <dd className="text-right">{formatWhen(selected.issued_at, timeZone)}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">For</dt>
                <dd className="text-right">{formatWhen(selected.target_time, timeZone)}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">Likely range</dt>
                <dd className="text-right">{formatNumber(selected.lower)} to {formatNumber(selected.upper)}</dd>
              </div>
            </dl>
            <p className="mt-auto pt-4 text-xs text-muted-foreground">{selected.interval ? `On past days, this range covered the actual temperature about ${(selected.interval.test_coverage * 100).toFixed(0)}% of the time.` : "Range check unavailable."}</p>
          </Card>
          <Card className="flex h-full flex-col p-4 sm:p-5">
            <Badge className="self-start">Weather forecast</Badge>
            {selected.external_forecast ? (
              <>
                <p className="mt-4 text-3xl font-semibold sm:text-4xl">{formatNumber(selected.external_forecast.temperature_max)} {temperature.data?.unit_labels.temperature}</p>
                <p className="text-sm text-muted-foreground">Daily high</p>
                <dl className="mt-4 grid gap-3 text-sm">
                  <div className="flex items-baseline justify-between gap-3 border-t border-border pt-3">
                    <dt className="text-muted-foreground">Daily low</dt>
                    <dd>{formatNumber(selected.external_forecast.temperature_min)} {temperature.data?.unit_labels.temperature}</dd>
                  </div>
                  <div className="flex items-baseline justify-between gap-3">
                    <dt className="text-muted-foreground">For</dt>
                    <dd className="text-right">{formatWhen(selected.target_time, timeZone)}</dd>
                  </div>
                </dl>
                <p className="mt-auto pt-4 text-xs text-muted-foreground">{selected.external_forecast.note}</p>
              </>
            ) : <p className="mt-4 text-sm text-muted-foreground">No weather forecast is stored for this date.</p>}
          </Card>
          <Card className="flex h-full flex-col p-4 sm:p-5">
            <Badge className="self-start" tone="amber">Simple comparisons</Badge>
            <p className="mt-4 text-3xl font-semibold sm:text-4xl">{formatNumber(selected.persistence_baseline)} {temperature.data?.unit_labels.temperature}</p>
            <p className="text-sm text-muted-foreground">Same as the last day</p>
            <dl className="mt-4 grid gap-3 text-sm">
              <div className="flex items-baseline justify-between gap-3 border-t border-border pt-3">
                <dt className="text-muted-foreground">Seasonal average</dt>
                <dd>{formatNumber(selected.statistical_baseline)} {selected.statistical_baseline == null ? "" : temperature.data?.unit_labels.temperature}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">Compared with yesterday</dt>
                <dd>
                  {selected.persistence_baseline == null
                    ? "—"
                    : `${formatNumber(selected.predicted_temperature - selected.persistence_baseline)} ${temperature.data?.unit_labels.temperature}`}
                </dd>
              </div>
            </dl>
            <p className="mt-auto pt-4 text-xs text-muted-foreground">These are simple checks shown beside the prediction.</p>
          </Card>
        </div>
      ) : <StatePanel status="empty" message="The model did not return a prediction." />}
      <Card className="min-w-0 overflow-hidden p-4">
        <h2 className="font-medium">Past accuracy</h2>
        <p className="mb-3 text-xs text-muted-foreground">{temperature.data?.backtest.label}</p>
        <BarSeriesChart
          label="Average error by days ahead"
          data={holdout.map((row) => ({
            label: `${row.horizon_days}d`,
            ml: row.test.mae,
            persistence: row.persistence_test.mae,
            statistical: row.fourier_test.mae,
          }))}
          bars={[
            { key: "ml", name: "Prediction", color: chartColors.primary },
            { key: "persistence", name: "Same as the last day", color: chartColors.secondary },
            { key: "statistical", name: "Seasonal average", color: chartColors.tertiary },
          ]}
        />
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead><tr><th>Days ahead</th><th>Average error</th><th>Error spread</th><th>Compared with yesterday</th><th>Days checked</th></tr></thead>
            <tbody>
              {holdout.map((row) => (
                <tr key={row.horizon_days} className="border-t border-border">
                  <td>{row.horizon_days}d</td>
                  <td>{row.test.mae.toFixed(2)}</td>
                  <td>{row.test.rmse.toFixed(2)}</td>
                  <td>{row.skill_vs_persistence == null ? "—" : row.skill_vs_persistence.toFixed(2)}</td>
                  <td>{row.test.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card className="p-4">
        <h2 className="font-medium">Weather forecast accuracy</h2>
        <p className="text-sm text-muted-foreground">{temperature.data?.external_benchmark.note}</p>
        <ul className="mt-3 grid grid-cols-1 gap-2 text-sm lg:grid-cols-2">
          {temperature.data?.external_benchmark.by_lead_days.map((row) => (
            <li key={row.lead_days}>{row.lead_days} day{row.lead_days === 1 ? "" : "s"} ahead: {row.available ? `${row.temperature_mae_c} °C average error, ${row.n} days` : "unavailable"}</li>
          ))}
        </ul>
      </Card>
      <Card className="p-4">
        <h2 className="font-medium">Rain</h2>
        {precip ? (
          <p className="mt-2 text-sm">Chance of rain {(precip.precipitation_probability * 100).toFixed(0)}% · estimated amount {formatNumber(precip.precipitation_amount)} · for {formatWhen(precip.target_time, timeZone)}</p>
        ) : <p className="mt-2 text-sm text-muted-foreground">{precipitation.isError ? "Rain prediction is unavailable." : "No rain prediction for this number of days ahead."}</p>}
        <p className="mt-3 text-xs text-muted-foreground">{precipitation.data?.limitations || temperature.data?.limitations}</p>
        <p className="mt-2 text-xs text-muted-foreground">{temperature.data?.comparison_note}</p>
      </Card>
    </>
  );
}
