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
        missing: Record<string, { missing_rate: number | null }>;
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
            <h2 className="font-medium">Missing data</h2>
            <ul className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
              {Object.entries(summary.data.missing).map(([key, value]) => (
                <li key={key} className="flex justify-between border-b border-border py-1">
                  <span>{key}</span>
                  <span>{value.missing_rate == null ? "—" : `${(value.missing_rate * 100).toFixed(1)}%`}</span>
                </li>
              ))}
            </ul>
            <Button className="mt-4" variant="secondary" asChild>
              <a href={`/api/proxy/analytics/export?location_id=${locationId}&start=${start}&end=${end}&units=${units}`}>Export CSV</a>
            </Button>
          </Card>
        </div>
      ) : null}
    </>
  );
}
