import { expect, test } from "@playwright/test";

test("overview page loads", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("not a replacement for official emergency alerts")).toBeVisible();
});

test("historical filters change the selected variable", async ({ page }) => {
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Historical analytics" })).toBeVisible();
  await page.getByLabel("Weather variable").selectOption("precipitation");
  await expect(page.getByRole("heading", { name: "precipitation and 7-day rolling mean" })).toBeVisible();
});

test("forecast page shows a model prediction or an honest unavailable state", async ({ page }) => {
  await page.goto("/forecast");
  await expect(page.getByRole("heading", { name: "Forecast" })).toBeVisible();
  await expect(
    page.getByText("Prediction", { exact: true }).or(page.getByText(/Forecast unavailable|No trained temperature model/i)),
  ).toBeVisible();
});

test("a simulated alert appears after the workflow records it", async ({ page, request }) => {
  const locations = await request.get("http://127.0.0.1:8000/api/v1/locations");
  const items = (await locations.json()).items as { id: number; is_default: boolean }[];
  const locationId = (items.find((item) => item.is_default) ?? items[0]).id;
  const eventId = `e2e-${Date.now()}`;
  const ruleName = `Playwright simulated heat ${eventId}`;
  const created = await request.post("http://127.0.0.1:8000/api/v1/workflows/weather-event", {
    headers: { "X-API-Key": "dev-weatheriq-key", "Content-Type": "application/json" },
    data: {
      event_id: eventId,
      location_id: locationId,
      timestamp: "2026-10-20T00:00:00Z",
      source: "playwright",
      variable: "temperature_c",
      actual_value: 47,
      threshold: 40,
      severity: "warning",
      rule_name: ruleName,
    },
  });
  expect(created.ok()).toBeTruthy();
  await page.goto("/alerts");
  await expect(page.getByRole("heading", { name: `${ruleName} at Mumbai` })).toBeVisible();
});
