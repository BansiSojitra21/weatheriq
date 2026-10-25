"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useDashboard } from "@/components/dashboard-context";
import { StatePanel } from "@/components/states";
import { Badge, Button, Card, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatNumber, formatWhen } from "@/lib/format";
import type { AnomalyItem } from "@/lib/types";

const FIELD_LABELS: Record<string, string> = {
  temperature_c: "Temperature",
  precipitation_mm: "Rain",
  humidity_pct: "Humidity",
  wind_speed_kmh: "Wind",
  pressure_hpa: "Pressure",
  multivariate: "Combined",
};

export function AnomaliesPage() {
  const { locationId, timeZone } = useDashboard();
  const [variable, setVariable] = useState("");
  const [review, setReview] = useState("");
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["anomalies", locationId, variable, review],
    queryFn: () => {
      const params = new URLSearchParams();
      if (locationId) params.set("location_id", String(locationId));
      if (variable) params.set("variable", variable);
      if (review) params.set("review_status", review);
      return api<{ items: AnomalyItem[]; note: string }>(`anomalies?${params.toString()}`);
    },
  });
  const reviewMutation = useMutation({
    mutationFn: (input: { id: number; review_status: string }) =>
      api(`anomalies/${input.id}`, { method: "PATCH", body: JSON.stringify({ review_status: input.review_status }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["anomalies"] }),
  });
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Anomaly detection</h1>
        <p className="text-sm text-muted-foreground">Unusual measurements are not the same thing as dangerous weather events. Detection refreshes once a day while the API server is running.</p>
      </div>
      <Card className="grid gap-3 p-4 sm:grid-cols-2">
        <Select className="w-full" aria-label="Anomaly variable" value={variable} onChange={(event) => setVariable(event.target.value)}>
          <option value="">All variables</option>
          <option value="temperature_c">Temperature</option>
          <option value="precipitation_mm">Precipitation</option>
          <option value="humidity_pct">Humidity</option>
          <option value="wind_speed_kmh">Wind</option>
          <option value="multivariate">Combined</option>
        </Select>
        <Select className="w-full" aria-label="Review status" value={review} onChange={(event) => setReview(event.target.value)}>
          <option value="">All reviews</option>
          <option value="unreviewed">Unreviewed</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
        </Select>
      </Card>
      {query.isLoading ? <StatePanel status="loading" /> : null}
      {query.isError ? <StatePanel status="error" message={query.error instanceof ApiError ? query.error.message : "Anomalies could not be loaded."} onRetry={() => query.refetch()} /> : null}
      {query.data && query.data.items.length === 0 ? <StatePanel status="empty" message="No anomaly events match these filters." /> : null}
      <div className="grid gap-3">
        {query.data?.items.map((item) => (
          <Card key={item.id} className="p-4">
            <div className="flex flex-wrap gap-2">
              <Badge tone="amber">{item.method}</Badge>
              <Badge>{item.review_status}</Badge>
              <Badge tone="neutral">Not a hazard warning</Badge>
            </div>
            <h2 className="mt-2 font-medium">{FIELD_LABELS[item.variable] ?? item.variable} · {formatNumber(item.observed_value)}</h2>
            <p className="text-sm text-muted-foreground">{formatWhen(item.observed_at, timeZone)} · reference {formatNumber(item.expected_low)} to {formatNumber(item.expected_high)} · score {formatNumber(item.score, 2)}</p>
            <p className="mt-2 text-sm">{item.explanation}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="secondary" onClick={() => reviewMutation.mutate({ id: item.id, review_status: "confirmed" })}>Confirm</Button>
              <Button type="button" size="sm" variant="secondary" onClick={() => reviewMutation.mutate({ id: item.id, review_status: "rejected" })}>Reject</Button>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
