"use client";

import { ChartColumn, CloudSun, LayoutDashboard, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { DashboardProvider, useDashboard } from "@/components/dashboard-context";
import { NotificationCenter } from "@/components/notification-center";
import { SelectionDropdown } from "@/components/selection-dropdown";
import { Select } from "@/components/ui";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/analytics", label: "Analytics", icon: ChartColumn },
  { href: "/forecast", label: "Forecast", icon: CloudSun },
  { href: "/weather-intelligence", label: "Weather Intelligence", icon: ShieldAlert },
];

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { locations, locationId, setLocationId, location, units, setUnits } = useDashboard();

  return (
    <div className="min-h-screen overflow-x-clip">
      <header className="sticky top-0 z-30 border-b border-border bg-white">
        <div className="mx-auto grid w-full max-w-7xl grid-cols-1 items-center gap-x-4 gap-y-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] xl:grid-cols-[auto_minmax(0,1fr)_auto]">
          <Link href="/" className="flex min-w-0 items-center gap-3 sm:col-start-1 sm:row-start-1">
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
          <nav
            aria-label="Primary"
            className="hidden min-w-0 items-center justify-center gap-1 md:col-span-2 md:row-start-2 md:flex xl:col-span-1 xl:col-start-2 xl:row-start-1 xl:w-fit xl:justify-self-center"
          >
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
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] gap-2 sm:col-start-2 sm:row-start-1 sm:flex sm:items-center xl:col-start-3">
            <NotificationCenter locations={locations} />
            <SelectionDropdown
              label="Location"
              value={String(locationId ?? "")}
              onChange={(value) => setLocationId(Number(value))}
              options={locations.map((item) => ({ value: String(item.id), label: item.name }))}
              menuClassName="w-56 max-w-[calc(100vw-2rem)]"
            />
            <SelectionDropdown
              label="Units"
              value={units}
              onChange={(value) => {
                if (value === "metric" || value === "imperial") setUnits(value);
              }}
              options={[
                { value: "metric", label: "Metric" },
                { value: "imperial", label: "Imperial" },
              ]}
              className="w-28 shrink-0"
            />
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
        </div>
      </header>
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
