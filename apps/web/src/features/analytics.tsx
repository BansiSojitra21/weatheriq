"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { BarSeriesChart, chartColors, LineSeriesChart } from "@/components/charts";
import { useDashboard } from "@/components/dashboard-context";
import { StatePanel } from "@/components/states";
import { Button, Card, Input, Label, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { defaultRange, formatNumber, formatWhen } from "@/lib/format";

const VARIABLES = ["temperature", "precipitation", "humidity", "wind_speed", "pressure", "cloud_cover"] as const;

const FIELD_LABELS: Record<string, string> = {
  temperature_c: "Temperature",
  temperature_min_c: "Daily low",
  temperature_max_c: "Daily high",
  humidity_pct: "Humidity",
  precipitation_mm: "Rain",
  wind_speed_kmh: "Wind",
  pressure_hpa: "Pressure",
  cloud_cover_pct: "Cloud cover",
};

export function AnalyticsPage() {
  const { locationId, locations, units, timeZone } = useDashboard();
  const initial = defaultRange();
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [variable, setVariable] = useState<(typeof VARIABLES)[number]>("temperature");
  const [compareId, setCompareId] = useState("");
  const enabled = locationId != null;
  const trends = useQuery({
    queryKey: ["trends", locationId, start, end, variable, compareId, units],
    enabled,
    queryFn: () => {
      const compare = compareId ? `&compare_location_id=${compareId}` : "";
      return api<{
        series: { observed_at: string; value: number | null; rolling_mean: number | null }[];
        comparison?: { series: { observed_at: string; value: number | null }[] };
      }>(`analytics/trends?location_id=${locationId}&start=${start}&end=${end}&variable=${variable}&units=${units}${compare}`);
    },
  });
  const summary = useQuery({
    queryKey: ["summary", locationId, start, end, units],
    enabled,
    queryFn: () =>
      api<{
        rows: number;
        missing: Record<string, { count: number; missing: number; missing_rate: number | null }>;
        variables: Record<string, { count: number; mean: number | null; min: number | null; max: number | null }>;
        unit_labels: { temperature: string; precipitation: string; wind: string; pressure: string };
        monthly: { month: number; temperature_mean: number | null; precipitation_total: number | null }[];
        seasonal: { season: string; temperature_mean: number | null; precipitation_total: number | null }[];
        season_note: string;
      }>(`analytics/summary?location_id=${locationId}&start=${start}&end=${end}&units=${units}`),
  });
  const matrix = useQuery({
    queryKey: ["correlation", locationId, start, end],
    enabled,
    queryFn: () =>
      api<{ variables: string[]; matrix: (number | null)[][]; note: string }>(
        `analytics/correlation?location_id=${locationId}&start=${start}&end=${end}`,
      ),
  });
  const failed = trends.error || summary.error || matrix.error;
  const fieldUnit = (field: string) => {
    if (field.startsWith("temperature")) return summary.data?.unit_labels.temperature;
    if (field === "precipitation_mm") return summary.data?.unit_labels.precipitation;
    if (field === "wind_speed_kmh") return summary.data?.unit_labels.wind;
    if (field === "pressure_hpa") return summary.data?.unit_labels.pressure;
    return "%";
  };
  const displayValue = (value: number | null, unit: string | undefined) =>
    value == null ? "—" : `${value.toFixed(2)}${unit ? ` ${unit}` : ""}`;
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Historical analytics</h1>
        <p className="text-sm text-muted-foreground">
          Daily observations from {start} through {end}, UTC dates. Values stay blank where the archive has no measurement.
        </p>
      </div>
      <Card className="grid w-full min-w-0 grid-cols-1 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="min-w-0">
          <Label htmlFor="start-date">Start</Label>
          <Input id="start-date" type="date" value={start} onChange={(event) => setStart(event.target.value)} />
        </div>
        <div className="min-w-0">
          <Label htmlFor="end-date">End</Label>
          <Input id="end-date" type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
        </div>
        <div className="min-w-0">
          <Label htmlFor="variable">Variable</Label>
          <Select id="variable" className="w-full" aria-label="Weather variable" value={variable} onChange={(event) => setVariable(event.target.value as (typeof VARIABLES)[number])}>
            {VARIABLES.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </Select>
        </div>
        <div className="min-w-0">
          <Label htmlFor="compare">Compare city</Label>
          <Select id="compare" className="w-full" aria-label="Comparison city" value={compareId} onChange={(event) => setCompareId(event.target.value)}>
            <option value="">None</option>
            {locations.filter((item) => item.id !== locationId).map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </Select>
        </div>
      </Card>
      {trends.isLoading || summary.isLoading ? <StatePanel status="loading" /> : null}
      {failed ? (
        <StatePanel status="error" message={failed instanceof ApiError ? failed.message : "Analytics could not be loaded."} onRetry={() => { trends.refetch(); summary.refetch(); }} />
      ) : null}
      {trends.data && trends.data.series.length === 0 ? <StatePanel status="empty" message="No observations in this date range." /> : null}
      {trends.data && trends.data.series.length > 0 ? (
        <Card className="min-w-0 overflow-hidden p-4">
          <h2 className="mb-3 font-medium">{variable} and 7-day rolling mean</h2>
          <LineSeriesChart
            label={`${variable} time series`}
            data={(() => {
              const comparison = new Map(
                (trends.data.comparison?.series ?? []).map((item) => [item.observed_at, item.value]),
              );
              return trends.data.series.map((row) => ({
                label: formatWhen(row.observed_at, timeZone),
                value: row.value,
                rolling: row.rolling_mean,
                comparison: comparison.get(row.observed_at) ?? null,
              }));
            })()}
            lines={[
              { key: "value", name: variable, color: chartColors.primary },
              { key: "rolling", name: "7-day mean", color: chartColors.secondary },
              ...(compareId ? [{ key: "comparison", name: "Comparison", color: chartColors.tertiary }] : []),
            ]}
          />
        </Card>
      ) : null}
      {summary.data ? (
        <div className="grid w-full min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
          <Card className="min-w-0 overflow-hidden p-4">
            <h2 className="mb-3 font-medium">Monthly comparison</h2>
            <BarSeriesChart
              label="Monthly temperature and precipitation"
              data={summary.data.monthly.map((row) => ({
                label: String(row.month),
                temperature: row.temperature_mean,
                precipitation: row.precipitation_total,
              }))}
              bars={[
                { key: "temperature", name: "Mean temperature", color: chartColors.primary },
                { key: "precipitation", name: "Precipitation total", color: chartColors.tertiary },
              ]}
            />
          </Card>
          <Card className="min-w-0 p-4">
            <h2 className="mb-3 font-medium">Seasonal comparison</h2>
            <p className="mb-3 text-xs text-muted-foreground">{summary.data.season_note}</p>
            <ul className="grid gap-2 text-sm">
              {summary.data.seasonal.map((row) => (
                <li key={row.season} className="grid gap-1 border-b border-border py-2 last:border-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <span>{row.season}</span>
                  <span>{formatNumber(row.temperature_mean)} · {formatNumber(row.precipitation_total)}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card className="p-4 lg:col-span-2">
            <h2 className="font-medium">Correlation</h2>
            <p className="mb-3 text-xs text-muted-foreground">{matrix.data?.note}</p>
            <div className="min-w-0 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-xs">
                <thead>
                  <tr>
                    <th className="p-2">Variable</th>
                    {matrix.data?.variables.map((item) => <th key={item} className="p-2">{item.replace("_c", "").replace("_mm", "")}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {matrix.data?.matrix.map((row, rowIndex) => (
                    <tr key={matrix.data?.variables[rowIndex]}>
                      <th className="p-2">{matrix.data?.variables[rowIndex]}</th>
                      {row.map((value, column) => (
                        <td key={column} className="p-2" style={{ background: value == null ? undefined : `rgba(20,147,184,${Math.abs(value) * 0.35})` }}>
                          {value == null ? "—" : value.toFixed(2)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card className="p-4 lg:col-span-2">
            <h2 className="font-medium">Data coverage and observed values</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {summary.data.rows} daily records in the selected range. Means and ranges use available readings only.
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead>
                  <tr>
                    <th className="py-2 pr-3">Measure</th>
                    <th className="py-2 pr-3">Available</th>
                    <th className="py-2 pr-3">Missing</th>
                    <th className="py-2 pr-3">Mean</th>
                    <th className="py-2 pr-3">Minimum</th>
                    <th className="py-2">Maximum</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.data.rows === 0 ? (
                    <tr><td colSpan={6} className="border-t border-border py-3 text-muted-foreground">No observations in this date range.</td></tr>
                  ) : Object.entries(summary.data.missing).map(([key, coverage]) => {
                    const stats = summary.data.variables[key];
                    const unit = fieldUnit(key);
                    return (
                      <tr key={key} className="border-t border-border">
                        <th className="py-2 pr-3 font-normal">{FIELD_LABELS[key] ?? key}</th>
                        <td className="py-2 pr-3">{coverage.count}</td>
                        <td className="py-2 pr-3">{coverage.missing}</td>
                        <td className="py-2 pr-3">{displayValue(stats?.mean ?? null, unit)}</td>
                        <td className="py-2 pr-3">{displayValue(stats?.min ?? null, unit)}</td>
                        <td className="py-2">{displayValue(stats?.max ?? null, unit)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Button className="mt-4" variant="secondary" asChild>
              <a href={`/api/proxy/analytics/export?location_id=${locationId}&start=${start}&end=${end}&units=${units}`}>Export CSV</a>
            </Button>
          </Card>
        </div>
      ) : null}
    </>
  );
}
