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
  await expect(page.getByRole("heading", { name: "See what the next days may bring" })).toBeVisible();
  await expect(
    page.getByText("WeatherIQ model estimate").or(page.getByText(/Forecast unavailable|No trained temperature model/i)),
  ).toBeVisible();
});

test("weather intelligence shows transparent risk and alert controls", async ({ page }) => {
  await page.goto("/weather-intelligence");
  await expect(page.getByRole("heading", { name: "Weather Intelligence & Alerts" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Transparent weather risk index" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Threshold rules" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Alert history" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Evaluate selected city" })).toHaveCount(0);
  await expect(page.getByRole("group", { name: "India city risk map" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open notifications and recent alerts" })).toBeVisible();
  await page.getByRole("button", { name: "Open notifications and recent alerts" }).click();
  await expect(page.getByRole("region", { name: "Notifications and recent alerts" })).toBeVisible();
  await expect(page.getByText("Recent alert history")).toBeVisible();
  await expect(page.getByRole("link", { name: "View full alert history" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Turn (on|off) Chrome notifications/ })).toBeVisible();
  const cityDropdown = page.getByRole("button", { name: "Location" });
  const unitsDropdown = page.getByRole("button", { name: "Units" });
  await expect(cityDropdown).toBeVisible();
  await expect(unitsDropdown).toBeVisible();
  expect(await cityDropdown.getAttribute("class")).toBe(await unitsDropdown.getAttribute("class"));

  await cityDropdown.click();
  const cityOptions = page.getByRole("listbox", { name: "Location" });
  await expect(cityOptions).toBeVisible();
  expect(await cityOptions.evaluate((element) => element.scrollHeight)).toBeGreaterThan(
    await cityOptions.evaluate((element) => element.clientHeight),
  );
  await cityOptions.getByRole("option").first().click();

  await unitsDropdown.click();
  await page.getByRole("listbox", { name: "Units" }).getByRole("option", { name: "Imperial" }).click();
  await expect(unitsDropdown).toContainText("Imperial");
});
