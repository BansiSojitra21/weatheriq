"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useDashboard } from "@/components/dashboard-context";
import { StatePanel } from "@/components/states";
import { Badge, Button, Card, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatNumber, formatWhen } from "@/lib/format";
import type { AlertItem } from "@/lib/types";

export function AlertActions({
  status,
  onChange,
}: {
  status: string;
  onChange: (status: "acknowledged" | "resolved") => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="secondary" size="sm" disabled={status !== "open"} onClick={() => onChange("acknowledged")}>
        Acknowledge
      </Button>
      <Button type="button" variant="secondary" size="sm" disabled={status === "resolved"} onClick={() => onChange("resolved")}>
        Resolve
      </Button>
    </div>
  );
}

export function AlertsPage() {
  const { locationId, timeZone } = useDashboard();
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const queryClient = useQueryClient();
  const alerts = useQuery({
    queryKey: ["alerts", status, severity, locationId],
    queryFn: () => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (severity) params.set("severity", severity);
      if (locationId) params.set("location_id", String(locationId));
      return api<{ items: AlertItem[]; total: number }>(`alerts?${params.toString()}`);
    },
  });
  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: () => api<{ items: { id: number; name: string; variable: string; operator: string; threshold: number; severity: string; enabled: boolean }[] }>("alerts/rules"),
  });
  const update = useMutation({
    mutationFn: (input: { id: number; status: string }) =>
      api(`alerts/${input.id}`, { method: "PATCH", body: JSON.stringify({ status: input.status }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Weather alerts</h1>
        <p className="text-sm text-muted-foreground">Rule matches and workflow events. Delivery is shown only after a delivery result is recorded.</p>
      </div>
      <Card className="grid gap-3 p-4 sm:grid-cols-2">
        <Select className="w-full" aria-label="Alert status" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
        </Select>
        <Select className="w-full" aria-label="Severity" value={severity} onChange={(event) => setSeverity(event.target.value)}>
          <option value="">All severities</option>
          <option value="info">Info</option>
          <option value="watch">Watch</option>
          <option value="warning">Warning</option>
        </Select>
      </Card>
      {alerts.isLoading ? <StatePanel status="loading" /> : null}
      {alerts.isError ? <StatePanel status="error" message={alerts.error instanceof ApiError ? alerts.error.message : "Alerts could not be loaded."} onRetry={() => alerts.refetch()} /> : null}
      {alerts.data && alerts.data.items.length === 0 ? <StatePanel status="empty" message="No alerts match these filters." /> : null}
      <div className="grid gap-3">
        {alerts.data?.items.map((alert) => (
          <Card key={alert.id} className="grid gap-3 p-4 md:grid-cols-[1fr_auto]">
            <div>
              <div className="flex flex-wrap gap-2">
                <Badge tone={alert.severity === "warning" ? "danger" : "amber"}>{alert.severity}</Badge>
                <Badge>{alert.condition_kind}</Badge>
                <Badge tone={alert.delivery.state === "delivered" ? "ok" : "neutral"}>
                  {alert.delivery.state === "delivered" ? `Delivered via ${alert.delivery.channel}` : "Not delivered"}
                </Badge>
              </div>
              <h2 className="mt-2 font-medium">{alert.title}</h2>
              <p className="text-sm text-muted-foreground">{alert.message}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                {formatWhen(alert.event_time, timeZone)} · threshold {formatNumber(alert.threshold)} · actual {formatNumber(alert.actual_value)} · {alert.status}
              </p>
            </div>
            <AlertActions status={alert.status} onChange={(next) => update.mutate({ id: alert.id, status: next })} />
          </Card>
        ))}
      </div>
      <Card className="p-4">
        <h2 className="font-medium">Alert rules</h2>
        <ul className="mt-3 grid gap-2 text-sm">
          {rules.data?.items.map((rule) => (
            <li key={rule.id} className="grid gap-1 border-b border-border py-3 last:border-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4">
              <span>{rule.name}</span>
              <span>{rule.variable} {rule.operator} {rule.threshold} · {rule.enabled ? "enabled" : "disabled"}</span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
