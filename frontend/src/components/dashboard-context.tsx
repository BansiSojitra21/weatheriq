"use client";

import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { Location } from "@/lib/types";

type DashboardValue = {
  locations: Location[];
  locationId: number | null;
  setLocationId: (id: number) => void;
  location?: Location;
  units: "metric" | "imperial";
  setUnits: (units: "metric" | "imperial") => void;
  timeZone: string;
};

const DashboardContext = createContext<DashboardValue | null>(null);
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function storedLocation() {
  return window.localStorage.getItem("weatheriq.location");
}

function storedUnits() {
  const value = window.localStorage.getItem("weatheriq.units");
  return value === "imperial" ? "imperial" : "metric";
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const locationsQuery = useQuery({
    queryKey: ["locations"],
    queryFn: () => api<{ items: Location[] }>("locations"),
  });
  const savedLocation = useSyncExternalStore(subscribe, storedLocation, () => null);
  const units = useSyncExternalStore(subscribe, storedUnits, () => "metric" as const);
  const locations = useMemo(
    () =>
      (locationsQuery.data?.items ?? [])
        .filter((item) => item.country === "India")
        .sort((left, right) => left.name.localeCompare(right.name)),
    [locationsQuery.data],
  );
  const preferred = locations.find((item) => item.is_default) || locations[0];
  const parsedLocation = savedLocation ? Number(savedLocation) : null;
  const locationId = locations.some((item) => item.id === parsedLocation) ? parsedLocation : preferred?.id ?? null;
  const location = locations.find((item) => item.id === locationId);
  const timeZone = location?.timezone || "UTC";
  const value = useMemo<DashboardValue>(
    () => ({
      locations,
      locationId,
      setLocationId: (id: number) => {
        window.localStorage.setItem("weatheriq.location", String(id));
        emit();
      },
      location,
      units,
      setUnits: (next) => {
        window.localStorage.setItem("weatheriq.units", next);
        emit();
      },
      timeZone,
    }),
    [location, locationId, locations, timeZone, units],
  );
  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard() {
  const value = useContext(DashboardContext);
  if (!value) throw new Error("useDashboard must be used inside DashboardProvider");
  return value;
}
