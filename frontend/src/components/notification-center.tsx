"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, BellOff, ChevronDown } from "lucide-react";
import { useState, useSyncExternalStore } from "react";
import { Badge, Button } from "@/components/ui";
import { api } from "@/lib/api";
import {
  getNotificationPermission,
  NOTIFICATION_PERMISSION_EVENT,
  subscribeNotificationPermission,
  subscribeNotificationPreferences,
  updateNotificationPreference,
} from "@/lib/notification-preferences";
import { formatWhen } from "@/lib/format";
import type { AlertItem, Location } from "@/lib/types";

type AlertList = { items: AlertItem[]; total: number; page: number; page_size: number };
const NOTIFICATIONS_KEY = "weatheriq.alert-notifications";
const DEFAULT_NOTIFICATION_SEVERITIES = ["low", "moderate", "high", "critical"];
const SEVERITIES_KEY = "weatheriq.alert-notification-severities";

export function NotificationCenter({ locations }: { locations: Location[] }) {
  const [open, setOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const enabled = useSyncExternalStore(
    subscribeNotificationPreferences,
    () => window.localStorage.getItem(NOTIFICATIONS_KEY) === "true",
    () => false,
  );
  const storedSeverities = useSyncExternalStore(
    subscribeNotificationPreferences,
    () => window.localStorage.getItem(SEVERITIES_KEY) ?? "",
    () => "",
  );
  let severities = DEFAULT_NOTIFICATION_SEVERITIES;
  if (storedSeverities) {
    try {
      const parsed: unknown = JSON.parse(storedSeverities);
      if (Array.isArray(parsed) && parsed.every((item) => DEFAULT_NOTIFICATION_SEVERITIES.includes(item))) {
        severities = parsed;
      }
    } catch {
      severities = DEFAULT_NOTIFICATION_SEVERITIES;
    }
  }
  const permission = useSyncExternalStore(
    subscribeNotificationPermission,
    getNotificationPermission,
    () => "default",
  );
  const alertsQuery = useQuery({
    queryKey: ["alerts", "notification-center"],
    queryFn: () => api<AlertList>("alerts?page=1&page_size=5"),
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  });

  async function toggleNotifications() {
    setActionError(null);
    if (enabled && permission === "granted") {
      updateNotificationPreference(NOTIFICATIONS_KEY, "false");
      return;
    }
    if (typeof Notification === "undefined") {
      setActionError("This browser does not support desktop notifications.");
      return;
    }
    try {
      const result = permission === "granted" ? "granted" : await Notification.requestPermission();
      window.dispatchEvent(new Event(NOTIFICATION_PERMISSION_EVENT));
      if (result !== "granted") {
        setActionError(result === "denied"
          ? "Chrome has blocked notifications for this site. Allow them in the site controls, then try again."
          : "Chrome notification permission was not granted.");
        return;
      }
      const notification = new Notification("WeatherIQ notifications are on", {
        body: "New weather alerts will appear here while WeatherIQ is open.",
        icon: "/icon.svg",
        tag: "weatheriq-notification-test",
      });
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
      updateNotificationPreference(NOTIFICATIONS_KEY, "true");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Chrome notifications could not be enabled.");
    }
  }

  function toggleSeverity(level: string) {
    const next = severities.includes(level)
      ? severities.filter((item) => item !== level)
      : [...severities, level];
    updateNotificationPreference(SEVERITIES_KEY, JSON.stringify(next));
  }

  const notificationsActive = enabled && permission === "granted";

  return (
    <div className="relative">
      <Button
        type="button"
        variant="secondary"
        size="icon"
        aria-label="Open notifications and recent alerts"
        aria-expanded={open}
        aria-controls="notification-center-panel"
        onClick={() => setOpen((value) => !value)}
        className="relative shrink-0 rounded-full"
      >
        {notificationsActive ? <Bell className="h-4 w-4" aria-hidden /> : <BellOff className="h-4 w-4" aria-hidden />}
        {notificationsActive ? <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-ok" aria-hidden /> : null}
      </Button>
      {open ? (
        <section
          id="notification-center-panel"
          aria-label="Notifications and recent alerts"
          className="absolute right-0 top-full z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-border bg-white p-4 shadow-xl"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Notifications</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Chrome permission: {permission === "granted" ? "Allowed" : permission === "denied" ? "Blocked" : permission === "unsupported" ? "Unsupported" : "Not enabled"}
              </p>
            </div>
            <Button
              type="button"
              variant={notificationsActive ? "secondary" : "default"}
              size="sm"
              aria-label={notificationsActive ? "Turn off Chrome notifications" : "Turn on Chrome notifications"}
              onClick={() => void toggleNotifications()}
            >
              {notificationsActive ? "Turn off" : "Turn on"}
            </Button>
          </div>
          {actionError ? <p role="alert" className="mt-2 text-xs text-danger">{actionError}</p> : null}
          <fieldset disabled={!notificationsActive} className="mt-3 flex flex-wrap gap-x-3 gap-y-2 border-t border-border pt-3 text-xs text-muted-foreground">
            <legend className="sr-only">Notify for severity</legend>
            {DEFAULT_NOTIFICATION_SEVERITIES.map((level) => (
              <label key={level} className="flex items-center gap-1.5 capitalize">
                <input
                  type="checkbox"
                  checked={severities.includes(level)}
                  onChange={() => toggleSeverity(level)}
                />
                {level}
              </label>
            ))}
          </fieldset>
          <div className="mt-4 border-t border-border pt-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-semibold">Recent alert history</h3>
              <Badge tone="neutral">{alertsQuery.data?.total ?? "…"}</Badge>
            </div>
            {alertsQuery.isLoading ? <p className="mt-3 text-xs text-muted-foreground">Loading recent alerts…</p> : null}
            {alertsQuery.isError ? <p role="alert" className="mt-3 text-xs text-danger">Recent alerts could not be loaded.</p> : null}
            {!alertsQuery.isLoading && !alertsQuery.isError && !alertsQuery.data?.items.length ? (
              <p className="mt-3 text-xs text-muted-foreground">No alerts recorded yet.</p>
            ) : null}
            <div className="mt-2 max-h-64 divide-y divide-border overflow-y-auto">
              {alertsQuery.data?.items.map((alert) => {
                const zone = locations.find((location) => location.id === alert.location_id)?.timezone ?? "UTC";
                return (
                  <a key={alert.id} href="#alert-history" onClick={() => setOpen(false)} className="block py-2.5 hover:text-accent">
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-medium">{alert.title}</span>
                      <Badge tone={alert.severity === "critical" || alert.severity === "high" || alert.severity === "warning" ? "danger" : alert.severity === "moderate" || alert.severity === "watch" ? "amber" : "neutral"}>
                        {alert.severity}
                      </Badge>
                    </span>
                    <span className="mt-1 block text-[11px] text-muted-foreground">
                      {alert.location_name ?? "Location"} · {formatWhen(alert.event_time, zone)} · {alert.status}
                    </span>
                    <span className="mt-1 block line-clamp-2 text-xs">{alert.message}</span>
                  </a>
                );
              })}
            </div>
            <a href="#alert-history" onClick={() => setOpen(false)} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
              View full alert history <ChevronDown className="h-3 w-3 rotate-[-90deg]" aria-hidden />
            </a>
          </div>
        </section>
      ) : null}
    </div>
  );
}
