"use client";

import { ChartColumn, CloudSun, LayoutDashboard, Menu, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { DashboardProvider, useDashboard } from "@/components/dashboard-context";
import { NotificationCenter } from "@/components/notification-center";
import { SelectionDropdown } from "@/components/selection-dropdown";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/analytics", label: "Analytics", icon: ChartColumn },
  { href: "/forecast", label: "Forecast", icon: CloudSun },
  { href: "/weather-intelligence", label: "Weather Intel", icon: ShieldAlert },
];

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const { locations, locationId, setLocationId, location, units, setUnits } = useDashboard();

  function renderNavLinks(compact = false) {
    return NAV.map((item) => {
      const Icon = item.icon;
      const active = pathname === item.href;
      return (
        <Link
          key={item.href}
          href={item.href}
          aria-current={active ? "page" : undefined}
          onClick={() => setMenuOpen(false)}
          className={cn(
            compact
              ? "inline-flex min-w-0 items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors"
              : "inline-flex min-w-0 items-center justify-center gap-1 rounded-full px-2 py-1.5 text-xs font-medium transition-colors xl:gap-2 xl:px-3.5 xl:py-2 xl:text-sm",
            active ? "bg-accent text-white shadow-sm" : "text-foreground/75 hover:bg-muted",
          )}
        >
          <Icon className={cn("shrink-0", compact ? "h-4 w-4" : "h-3.5 w-3.5 xl:h-4 xl:w-4")} aria-hidden />
          <span className="truncate">{item.label}</span>
        </Link>
      );
    });
  }

  return (
    <div className="min-h-screen overflow-x-clip">
      <header className="sticky top-0 z-30 border-b border-border bg-white">
        <div className="mx-auto grid w-full max-w-7xl grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-3 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
          <Link href="/" className="col-start-1 row-start-1 flex min-w-0 items-center gap-3">
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
            className="hidden min-w-0 items-center justify-center gap-1 lg:col-start-2 lg:row-start-1 lg:flex lg:w-max lg:justify-self-center"
          >
            {renderNavLinks()}
          </nav>
          <div className="hidden min-w-0 items-center gap-2 lg:col-start-3 lg:row-start-1 lg:flex lg:justify-self-end">
            <SelectionDropdown
              label="Location"
              value={String(locationId ?? "")}
              onChange={(value) => setLocationId(Number(value))}
              options={locations.map((item) => ({ value: String(item.id), label: item.name }))}
              className="w-28 shrink-0"
              menuClassName="w-56 max-w-[calc(100vw-2rem)]"
            />
            <NotificationCenter locations={locations} />
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
              className="w-24 shrink-0"
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            className="col-start-2 row-start-1 lg:hidden"
            aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
            aria-expanded={menuOpen}
            aria-controls="responsive-navigation-menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X className="h-4 w-4" aria-hidden /> : <Menu className="h-4 w-4" aria-hidden />}
          </Button>
          {menuOpen ? (
            <div
              id="responsive-navigation-menu"
              className="col-span-2 grid min-w-0 gap-3 border-t border-border pt-3 lg:hidden"
            >
              <nav aria-label="Primary" className="grid grid-cols-2 gap-1">
                {renderNavLinks(true)}
              </nav>
              <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 border-t border-border pt-3">
                <SelectionDropdown
                  label="Location"
                  value={String(locationId ?? "")}
                  onChange={(value) => setLocationId(Number(value))}
                  options={locations.map((item) => ({ value: String(item.id), label: item.name }))}
                  className="w-full"
                  menuClassName="w-56 max-w-[calc(100vw-2rem)]"
                />
                <NotificationCenter locations={locations} />
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
                  className="w-full"
                />
              </div>
            </div>
          ) : null}
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
