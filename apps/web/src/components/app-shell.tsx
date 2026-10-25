"use client";

import { Activity, Bell, ChartColumn, CloudSun, Gauge, LayoutDashboard } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { DashboardProvider, useDashboard } from "@/components/dashboard-context";
import { Select } from "@/components/ui";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/analytics", label: "Analytics", icon: ChartColumn },
  { href: "/forecast", label: "Forecast", icon: CloudSun },
  { href: "/anomalies", label: "Anomalies", icon: Activity },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/monitoring", label: "Monitoring", icon: Gauge },
];

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { locations, locationId, setLocationId, location, units, setUnits } = useDashboard();

  return (
    <div className="min-h-screen overflow-x-hidden">
      <header className="sticky top-0 z-30 border-b border-border bg-white">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <Link href="/" className="flex min-w-0 items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-accent text-white">
                <CloudSun className="h-5 w-5" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold tracking-tight text-foreground sm:text-base">WeatherIQ</span>
                <span className="block truncate text-[0.7rem] text-muted-foreground sm:text-xs">
                  {location ? `${location.name}, ${location.country} · ${location.timezone}` : "Select a location"}
                </span>
              </span>
            </Link>
            <div className="grid min-w-0 grid-cols-2 gap-2 sm:flex sm:items-center">
              <label className="sr-only" htmlFor="location-select">
                Location
              </label>
              <Select
                id="location-select"
                className="h-10 rounded-full bg-muted px-3"
                aria-label="Location"
                value={locationId ?? ""}
                onChange={(event) => setLocationId(Number(event.target.value))}
              >
                {locations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </Select>
              <Select
                className="h-10 rounded-full bg-muted px-3"
                aria-label="Units"
                value={units}
                onChange={(event) => setUnits(event.target.value as "metric" | "imperial")}
              >
                <option value="metric">Metric</option>
                <option value="imperial">Imperial</option>
              </Select>
            </div>
          </div>
          <label className="sr-only md:hidden" htmlFor="page-select">
            Page
          </label>
          <Select
            id="page-select"
            className="h-11 w-full rounded-full bg-muted px-3 text-sm md:hidden"
            aria-label="Page"
            value={NAV.some((item) => item.href === pathname) ? pathname : "/"}
            onChange={(event) => router.push(event.target.value)}
          >
            {NAV.map((item) => (
              <option key={item.href} value={item.href}>
                {item.label}
              </option>
            ))}
          </Select>
          <nav aria-label="Primary" className="hidden min-w-0 gap-1 rounded-full bg-muted p-1 md:flex">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex min-w-0 flex-1 items-center justify-center gap-1 rounded-full px-2 py-1.5 text-xs font-medium transition-colors lg:gap-2 lg:px-3.5 lg:py-2 lg:text-sm xl:flex-none",
                    active ? "bg-accent text-white shadow-sm" : "text-foreground/75 hover:bg-white",
                  )}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0 lg:h-4 lg:w-4" aria-hidden />
                  <span className="truncate">{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </header>
      <p className="mx-auto w-full min-w-0 max-w-7xl px-4 pt-4 text-xs leading-5 text-muted-foreground sm:text-sm sm:leading-6">
        WeatherIQ is an analytical tool. It is not a replacement for official emergency alerts or professional meteorological forecasts.
      </p>
      <main className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-4 px-4 py-4 [&>*]:min-w-0 [&>*]:max-w-full">{children}</main>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <DashboardProvider>
      <Shell>{children}</Shell>
    </DashboardProvider>
  );
}
