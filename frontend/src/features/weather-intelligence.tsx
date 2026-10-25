"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { BellRing, ShieldAlert } from "lucide-react";
import { AlertActions } from "@/components/alert-actions";
import { useDashboard } from "@/components/dashboard-context";
import { StatePanel } from "@/components/states";
import { Badge, Button, Card, Input, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatNumber, formatWhen } from "@/lib/format";
import { subscribeNotificationPreferences } from "@/lib/notification-preferences";
import type { AlertItem } from "@/lib/types";

type RiskFactor = {
  score: number;
  precipitation_probability?: number | null;
  precipitation_mm?: number | null;
  wind_speed_kmh?: number | null;
  temperature_max_c?: number | null;
  temperature_min_c?: number | null;
};

type CityRisk = {
  location_id: number;
  location_name: string;
  latitude: number;
  longitude: number;
  score: number | null;
  level: "low" | "moderate" | "high" | "critical" | "unavailable";
  primary_driver: string | null;
  valid_at: string | null;
  factors: Record<string, RiskFactor>;
  forecast_retrieved_at: string | null;
  days_with_data: number;
};

type RiskOverview = {
  items: CityRisk[];
  as_of: string;
  period_days: number;
  method: { name: string; description: string };
};

type AlertRule = {
  id: number;
  name: string;
  location_id: number | null;
  variable: string;
  operator: string;
  threshold: number;
  severity: string;
  enabled: boolean;
  cooldown_minutes: number;
  description: string;
};

type AlertList = { items: AlertItem[]; total: number; page: number; page_size: number };
type AlertRuleList = { items: AlertRule[] };
const SEVERITY_LABELS: Record<string, string> = {
  info: "Low",
  low: "Low",
  watch: "Moderate",
  moderate: "Moderate",
  warning: "High",
  high: "High",
  critical: "Critical",
};

const LEVEL_STYLES: Record<CityRisk["level"], string> = {
  low: "border-ok/30 bg-ok/10 text-ok",
  moderate: "border-amber/30 bg-amber/10 text-amber",
  high: "border-danger/30 bg-danger/10 text-danger",
  critical: "border-danger bg-danger/15 text-danger",
  unavailable: "border-border bg-muted text-muted-foreground",
};

const VARIABLE_LABELS: Record<string, string> = {
  temperature_c: "Temperature",
  precipitation_mm: "Rainfall",
  wind_speed_kmh: "Wind speed",
};
const DEFAULT_NOTIFICATION_SEVERITIES = ["low", "moderate", "high", "critical"];

function severityLabel(value: string) {
  return SEVERITY_LABELS[value] ?? value;
}

function normalizedSeverity(value: string) {
  if (value === "info") return "low";
  if (value === "watch") return "moderate";
  if (value === "warning") return "high";
  return value;
}

function operatorLabel(value: string) {
  return ({ gt: ">", gte: "≥", lt: "<", lte: "≤" } as Record<string, string>)[value] ?? value;
}

function formatThreshold(rule: AlertRule, units: "metric" | "imperial") {
  const value = units === "imperial"
    ? rule.variable === "temperature_c"
      ? (rule.threshold * 9) / 5 + 32
      : rule.variable === "precipitation_mm"
        ? rule.threshold / 25.4
        : rule.threshold / 1.609344
    : rule.threshold;
  const unit = rule.variable === "temperature_c"
    ? units === "metric" ? "°C" : "°F"
    : rule.variable === "precipitation_mm"
      ? units === "metric" ? "mm" : "in"
      : units === "metric" ? "km/h" : "mph";
  return `${formatNumber(value)} ${unit}`;
}

function metricValue(
  factor: RiskFactor | undefined,
  field: "precipitation_mm" | "wind_speed_kmh" | "temperature_max_c" | "temperature_min_c",
  units: "metric" | "imperial",
) {
  const value = factor?.[field];
  if (value == null) return "Unavailable";
  if (field === "temperature_max_c" || field === "temperature_min_c") {
    return `${formatNumber(units === "imperial" ? value * 9 / 5 + 32 : value)} ${units === "metric" ? "°C" : "°F"}`;
  }
  if (field === "wind_speed_kmh") {
    return `${formatNumber(units === "imperial" ? value / 1.609344 : value)} ${units === "metric" ? "km/h" : "mph"}`;
  }
  return `${formatNumber(units === "imperial" ? value / 25.4 : value, units === "imperial" ? 2 : 1)} ${units === "metric" ? "mm" : "in"}`;
}

function riskTone(level: CityRisk["level"]): "ok" | "amber" | "danger" | "neutral" {
  if (level === "low") return "ok";
  if (level === "moderate") return "amber";
  if (level === "high" || level === "critical") return "danger";
  return "neutral";
}

function riskPosition(city: CityRisk) {
  return {
    left: `${27.5 + Math.max(0, Math.min(1, (city.longitude - 68) / 30)) * 45}%`,
    top: `${4 + Math.max(0, Math.min(1, (38 - city.latitude) / 32)) * 92}%`,
  };
}

function AlertMessage({ message }: { message: string | null }) {
  return message ? <p role="alert" className="text-sm text-danger">{message}</p> : null;
}

export function WeatherIntelligencePage() {
  const { locationId, setLocationId, locations, timeZone, units } = useDashboard();
  const queryClient = useQueryClient();
  const [ruleName, setRuleName] = useState("");
  const [variable, setVariable] = useState("precipitation_mm");
  const [threshold, setThreshold] = useState("");
  const [severity, setSeverity] = useState("high");
  const [alertPage, setAlertPage] = useState(1);
  const [actionError, setActionError] = useState<string | null>(null);
  const seenAlertIds = useRef<Set<number> | null>(null);
  const browserNotifications = useSyncExternalStore(
    subscribeNotificationPreferences,
    () => window.localStorage.getItem("weatheriq.alert-notifications") === "true",
    () => false,
  );
  const storedSeverities = useSyncExternalStore(
    subscribeNotificationPreferences,
    () => window.localStorage.getItem("weatheriq.alert-notification-severities") ?? "",
    () => "",
  );
  const notificationSeverities = useMemo(() => {
    if (!storedSeverities) return DEFAULT_NOTIFICATION_SEVERITIES;
    try {
      const parsed: unknown = JSON.parse(storedSeverities);
      if (Array.isArray(parsed) && parsed.every((item) => DEFAULT_NOTIFICATION_SEVERITIES.includes(item))) {
        return parsed;
      }
    } catch {
      return DEFAULT_NOTIFICATION_SEVERITIES;
    }
    return DEFAULT_NOTIFICATION_SEVERITIES;
  }, [storedSeverities]);

  const riskQuery = useQuery({
    queryKey: ["risk-overview"],
    queryFn: () => api<RiskOverview>("risk/overview"),
  });
  const alertQuery = useQuery({
    queryKey: ["alerts", alertPage],
    queryFn: () => api<AlertList>(`alerts?page=${alertPage}&page_size=20`),
  });
  const notificationQuery = useQuery({
    queryKey: ["alerts", "notifications"],
    queryFn: () => api<AlertList>("alerts?page=1&page_size=20"),
    refetchInterval: 30_000,
  });
  const rulesQuery = useQuery({
    queryKey: ["alert-rules"],
    queryFn: () => api<AlertRuleList>("alerts/rules"),
  });

  useEffect(() => {
    const items = notificationQuery.data?.items;
    if (!items) return;
    const knownIds = seenAlertIds.current;
    seenAlertIds.current = new Set([...(knownIds ?? []), ...items.map((alert) => alert.id)]);
    if (!knownIds || !browserNotifications || typeof Notification === "undefined" || Notification.permission !== "granted") return;
    const newAlerts = items.filter(
      (alert) => !knownIds.has(alert.id) && notificationSeverities.includes(normalizedSeverity(alert.severity)),
    );
    if (!newAlerts.length) return;
    try {
      const title = newAlerts.length === 1 ? newAlerts[0].title : `${newAlerts.length} weather threshold alerts`;
      const body = newAlerts.length === 1 ? newAlerts[0].message : newAlerts.map((alert) => alert.title).join("; ");
      const notification = new Notification(title, {
        body,
        icon: "/icon.svg",
        tag: `weatheriq-alert-${newAlerts[newAlerts.length - 1].id}`,
      });
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    } catch (error) {
      console.error("New weather alerts were recorded, but browser notification could not be shown.", error);
    }
  }, [notificationQuery.data, browserNotifications, notificationSeverities]);

  const acknowledgeMutation = useMutation({
    mutationFn: ({ alertId, status }: { alertId: number; status: "acknowledged" | "resolved" }) =>
      api<AlertItem>(`alerts/${alertId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    onSuccess: async () => {
      setActionError(null);
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : "Alert status could not be updated."),
  });

  const ruleMutation = useMutation({
    mutationFn: ({ ruleId, enabled }: { ruleId: number; enabled: boolean }) =>
      api<AlertRule>(`alerts/rules/${ruleId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: async () => {
      setActionError(null);
      await queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : "Rule could not be updated."),
  });

  const createRuleMutation = useMutation({
    mutationFn: (body: object) =>
      api<AlertRule>("alerts/rules", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: async () => {
      setRuleName("");
      setThreshold("");
      setActionError(null);
      await queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : "Rule could not be saved."),
  });

  if (locationId == null) return <StatePanel status="loading" />;
  if (riskQuery.isLoading) return <StatePanel status="loading" />;
  if (riskQuery.isError) {
    return (
      <StatePanel
        status="error"
        message={riskQuery.error instanceof ApiError ? riskQuery.error.message : "Forecast risk overview could not be loaded."}
        onRetry={() => riskQuery.refetch()}
      />
    );
  }

  const riskItems = riskQuery.data?.items ?? [];
  const selectedRisk = riskItems.find((item) => item.location_id === locationId);
  const cityTimeZone = (cityId: number) => locations.find((item) => item.id === cityId)?.timezone ?? timeZone;
  const availableFactors = selectedRisk?.factors ?? {};
  const alertPages = Math.max(1, Math.ceil((alertQuery.data?.total ?? 0) / (alertQuery.data?.page_size ?? 20)));
  const factorCards: { label: string; factor: RiskFactor | undefined; detail: string }[] = [
    {
      label: "Rain",
      factor: availableFactors.rain,
      detail: `${availableFactors.rain?.precipitation_probability == null ? "Rain chance unavailable" : `${formatNumber(availableFactors.rain.precipitation_probability, 0)}% chance`} · ${metricValue(availableFactors.rain, "precipitation_mm", units)}`,
    },
    { label: "Wind", factor: availableFactors.wind, detail: metricValue(availableFactors.wind, "wind_speed_kmh", units) },
    { label: "Heat", factor: availableFactors.heat, detail: metricValue(availableFactors.heat, "temperature_max_c", units) },
    { label: "Cold", factor: availableFactors.cold, detail: metricValue(availableFactors.cold, "temperature_min_c", units) },
  ];

  function submitRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const thresholdValue = Number(threshold);
    if (!ruleName.trim() || !Number.isFinite(thresholdValue) || locationId == null) return;
    const thresholdMetric = units === "imperial"
      ? variable === "temperature_c"
        ? (thresholdValue - 32) * 5 / 9
        : variable === "precipitation_mm"
          ? thresholdValue * 25.4
          : thresholdValue * 1.609344
      : thresholdValue;
    createRuleMutation.mutate({
      name: ruleName.trim(),
      location_id: locationId,
      variable,
      operator: "gt",
      threshold: thresholdMetric,
      severity,
      enabled: true,
      description: `Forecast or observed ${VARIABLE_LABELS[variable].toLowerCase()} exceeds ${thresholdValue}.`,
    });
  }

  return (
    <div className="space-y-5">
      <header>
        <Badge tone="accent">Forecast signals · configured rules</Badge>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Weather Intelligence &amp; Alerts</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Compare forecast risk across saved locations, inspect the factors behind each score, and manage threshold alerts.
        </p>
      </header>

      <Card className="grid gap-4 p-4 sm:grid-cols-[1.2fr_0.8fr] sm:p-5">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-accent" aria-hidden />
            <h2 className="font-semibold">Transparent weather risk index</h2>
            {selectedRisk ? <Badge tone={riskTone(selectedRisk.level)}>{selectedRisk.level}</Badge> : null}
          </div>
          {selectedRisk?.score == null ? (
            <p className="mt-3 text-sm text-muted-foreground">No complete forecast factors are available for this location in the next {riskQuery.data?.period_days ?? 3} days. Missing data is not treated as zero risk.</p>
          ) : (
            <>
              <p className="mt-3 text-5xl font-semibold tracking-tight">{formatNumber(selectedRisk.score, 0)}<span className="ml-1 text-lg text-muted-foreground">/100</span></p>
              <p className="mt-2 text-sm text-muted-foreground">
                Highest factor: {selectedRisk.primary_driver ?? "Unavailable"} · {selectedRisk.valid_at ? formatWhen(selectedRisk.valid_at, timeZone) : "Date unavailable"}
              </p>
            </>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          {factorCards.map(({ label, factor, detail }) => (
            <div key={label} className="rounded-xl bg-muted/60 p-3">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-1 font-semibold">{factor ? `${factor.score}/100` : "Unavailable"}</p>
              <p className="mt-1 text-xs text-muted-foreground">{factor ? detail : "Forecast factor unavailable"}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">Three-day city risk map</h2>
            <p className="mt-1 text-xs text-muted-foreground">City positions use saved latitude/longitude. Select a marker to change the dashboard location.</p>
          </div>
          <Badge tone="neutral">Highest forecast factor · {riskItems.length} locations</Badge>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="relative min-h-[360px] overflow-hidden rounded-2xl border border-border bg-sky-50/50" role="group" aria-label="India city risk map">
            <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(148,163,184,.14)_1px,transparent_1px),linear-gradient(to_bottom,rgba(148,163,184,.14)_1px,transparent_1px)] bg-[size:20%_20%]" />
            <span className="absolute left-2 top-2 text-[10px] text-muted-foreground">38°N</span>
            <span className="absolute bottom-2 left-2 text-[10px] text-muted-foreground">6°N</span>
            <span className="absolute bottom-2 right-2 text-[10px] text-muted-foreground">98°E</span>
            <svg className="pointer-events-none absolute inset-y-2 left-[27.5%] h-[calc(100%-1rem)] w-[45%]" viewBox="0 0 300 320" preserveAspectRatio="none" aria-hidden="true">
              <path
                d="M4 140 L24 115 L35 83 L56 66 L77 51 L93 29 L111 14 L129 28 L139 43 L154 53 L169 63 L184 73 L203 85 L222 81 L240 84 L258 75 L278 79 L294 95 L283 111 L265 119 L249 132 L236 147 L227 164 L220 184 L204 187 L194 209 L176 211 L162 231 L147 249 L134 275 L121 309 L107 286 L96 257 L81 231 L66 205 L51 183 L34 163 L16 151 Z"
                fill="rgba(34,197,94,.08)"
                stroke="rgba(100,116,139,.55)"
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
              <path d="M221 82 L229 98 L241 107 L258 108 M204 187 L215 180 L227 164" fill="none" stroke="rgba(100,116,139,.4)" strokeWidth="1" />
            </svg>
            {riskItems.map((city) => (
              <button
                key={city.location_id}
                type="button"
                title={`${city.location_name}: ${city.score == null ? "risk unavailable" : `${city.score}/100 ${city.level}`}`}
                aria-label={`Select ${city.location_name}, ${city.score == null ? "risk unavailable" : `${city.score} out of 100, ${city.level} risk`}`}
                onClick={() => setLocationId(city.location_id)}
                style={riskPosition(city)}
                className={`absolute z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-md transition-transform hover:z-20 hover:scale-150 focus-visible:z-20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground ${
                  city.location_id === locationId ? "ring-2 ring-accent ring-offset-2" : ""
                } ${LEVEL_STYLES[city.level]}`}
              >
                <span className="sr-only">{city.location_name}: {city.score == null ? "risk unavailable" : `${Math.round(city.score)} ${city.level}`}</span>
              </button>
            ))}
          </div>
          <div className="max-h-[310px] overflow-y-auto divide-y divide-border">
            {riskItems.map((city) => (
              <button
                key={city.location_id}
                type="button"
                onClick={() => setLocationId(city.location_id)}
                className={`flex w-full items-center justify-between gap-3 py-2 text-left text-sm ${city.location_id === locationId ? "font-semibold" : "hover:text-accent"}`}
              >
                <span className="min-w-0 truncate">{city.location_name}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge tone={riskTone(city.level)}>{city.score == null ? "No data" : `${Math.round(city.score)} · ${city.level}`}</Badge>
                  {city.primary_driver ? <span className="hidden text-xs text-muted-foreground sm:inline">{city.primary_driver}</span> : null}
                </span>
              </button>
            ))}
          </div>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
          {riskQuery.data?.method.description} Scores use rain probability and rainfall (50 mm = 100), wind (60 km/h = 100), heat (30–45 °C), and cold (5 to −10 °C); the highest available factor sets the index. Levels: Low 0–24, Moderate 25–49, High 50–74, Critical 75–100.
          {selectedRisk?.forecast_retrieved_at ? ` ${selectedRisk.days_with_data} forecast day(s) included; selected location data retrieved ${formatWhen(selectedRisk.forecast_retrieved_at, timeZone)}.` : " Forecast update time unavailable."}
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">Threshold rules</h2>
              <p className="mt-1 text-xs text-muted-foreground">Rules compare enabled thresholds with the latest stored observations and forecast values.</p>
            </div>
          </div>
          <div className="mt-3 divide-y divide-border">
            {rulesQuery.isLoading ? <p className="py-3 text-sm text-muted-foreground">Loading rules…</p> : null}
            {rulesQuery.isError ? <p role="alert" className="py-3 text-sm text-danger">Alert rules could not be loaded.</p> : null}
            {(rulesQuery.data?.items ?? []).map((rule) => (
              <div key={rule.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{rule.name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {VARIABLE_LABELS[rule.variable] ?? rule.variable} {operatorLabel(rule.operator)} {formatThreshold(rule, units)} · {severityLabel(rule.severity)}
                    {rule.location_id == null ? " · all cities" : rule.location_id === locationId ? " · selected city" : " · another city"}
                  </p>
                </div>
                <Button
                  type="button"
                  variant={rule.enabled ? "secondary" : "ghost"}
                  size="sm"
                  disabled={ruleMutation.isPending}
                  onClick={() => ruleMutation.mutate({ ruleId: rule.id, enabled: !rule.enabled })}
                >
                  {rule.enabled ? "Enabled" : "Disabled"}
                </Button>
              </div>
            ))}
            {!rulesQuery.isLoading && !rulesQuery.isError && !rulesQuery.data?.items.length ? (
              <p className="py-3 text-sm text-muted-foreground">No alert rules configured yet.</p>
            ) : null}
          </div>
          <form onSubmit={submitRule} className="mt-4 space-y-3 border-t border-border pt-4">
            <h3 className="text-sm font-semibold">Add a location threshold</h3>
            <label className="block text-xs text-muted-foreground">
              Rule name
              <Input className="mt-1" value={ruleName} onChange={(event) => setRuleName(event.target.value)} required maxLength={160} placeholder="For example, Strong wind" />
            </label>
            <div className="grid gap-2 sm:grid-cols-3">
              <label className="block text-xs text-muted-foreground">
                Weather variable
                <Select className="mt-1 w-full" value={variable} onChange={(event) => setVariable(event.target.value)}>
                  <option value="precipitation_mm">Rainfall</option>
                  <option value="wind_speed_kmh">Wind speed</option>
                  <option value="temperature_c">Temperature</option>
                </Select>
              </label>
              <label className="block text-xs text-muted-foreground">
                Above ({variable === "temperature_c" ? units === "metric" ? "°C" : "°F" : variable === "precipitation_mm" ? units === "metric" ? "mm" : "in" : units === "metric" ? "km/h" : "mph"})
                <Input className="mt-1" type="number" min={variable === "temperature_c" ? "-100" : "0"} step="any" value={threshold} onChange={(event) => setThreshold(event.target.value)} required />
              </label>
              <label className="block text-xs text-muted-foreground">
                Severity
                <Select className="mt-1 w-full" value={severity} onChange={(event) => setSeverity(event.target.value)}>
                  <option value="low">Low</option>
                  <option value="moderate">Moderate</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </Select>
              </label>
            </div>
            <Button type="submit" variant="secondary" disabled={createRuleMutation.isPending}>
              {createRuleMutation.isPending ? "Saving…" : `Save rule for ${locations.find((item) => item.id === locationId)?.name ?? "selected city"}`}
            </Button>
          </form>
        </Card>

        <Card id="alert-history" className="flex min-h-[520px] flex-col p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">Alert history</h2>
              <p className="mt-1 text-xs text-muted-foreground">Stored rule events and their in-app acknowledgement status.</p>
            </div>
            <Badge tone="accent">{alertQuery.data?.total ?? "…"}</Badge>
          </div>
          {alertQuery.isLoading ? <p className="mt-4 text-sm text-muted-foreground">Loading alert history…</p> : null}
          {alertQuery.isError ? <p role="alert" className="mt-4 text-sm text-danger">Alert history could not be loaded.</p> : null}
          <div className="mt-3 min-h-0 flex-1 divide-y divide-border overflow-y-auto">
            {(alertQuery.data?.items ?? []).map((alert) => {
              const zone = cityTimeZone(alert.location_id);
              return (
                <article key={alert.id} className="py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-medium">{alert.title}</h3>
                    <Badge tone={alert.severity === "critical" || alert.severity === "high" || alert.severity === "warning" ? "danger" : alert.severity === "moderate" || alert.severity === "watch" ? "amber" : "neutral"}>
                      {severityLabel(alert.severity)}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{alert.location_name ?? "Location"} · {formatWhen(alert.event_time, zone)} · {alert.status}</p>
                  <p className="mt-2 text-sm">{alert.message}</p>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">
                      Delivery: {alert.delivery.state}{alert.delivery.attempts ? ` · ${alert.delivery.attempts} attempt(s)` : ""}
                    </span>
                    <AlertActions
                      status={alert.status}
                      onChange={(status) => acknowledgeMutation.mutate({ alertId: alert.id, status })}
                    />
                  </div>
                </article>
              );
            })}
            {!alertQuery.isLoading && !alertQuery.isError && !alertQuery.data?.items.length ? (
              <p className="py-4 text-sm text-muted-foreground">No alert events have been recorded yet. Enabled rules are checked automatically every five minutes.</p>
            ) : null}
          </div>
          {alertQuery.data && alertPages > 1 ? (
            <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-xs">
              <Button type="button" variant="secondary" size="sm" disabled={alertPage <= 1} onClick={() => setAlertPage((page) => page - 1)}>Previous</Button>
              <span className="text-muted-foreground">Page {alertPage} of {alertPages} · {alertQuery.data.total} alerts</span>
              <Button type="button" variant="secondary" size="sm" disabled={alertPage >= alertPages} onClick={() => setAlertPage((page) => page + 1)}>Next</Button>
            </div>
          ) : null}
        </Card>
      </div>

      <AlertMessage message={actionError} />
      <Card className="flex gap-3 p-4">
        <BellRing className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
        <p className="text-xs leading-relaxed text-muted-foreground">
          Scores are transparent threshold heuristics, not an AI probability or official hazard assessment. The app records alerts and supports acknowledgement; push, SMS, and email delivery are not configured. For urgent conditions, follow official local advisories.
        </p>
      </Card>
    </div>
  );
}
