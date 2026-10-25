import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AlertActions } from "@/components/alert-actions";
import { chartColors, LineSeriesChart } from "@/components/charts";
import { StatePanel } from "@/components/states";

describe("interface states", () => {
  it("shows a loading status", () => {
    render(<StatePanel status="loading" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });

  it("shows an error and retries", async () => {
    const onRetry = vi.fn();
    render(<StatePanel status="error" message="Backend unavailable" onRetry={onRetry} />);
    expect(screen.getByText("Backend unavailable")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("shows an empty message", () => {
    render(<StatePanel status="empty" message="No observations in this date range." />);
    expect(screen.getByText("No observations in this date range.")).toBeVisible();
  });
});

describe("charts and alert actions", () => {
  it("renders a labeled chart", () => {
    render(
      <LineSeriesChart
        label="Hourly forecast temperature"
        data={[{ label: "01:00", temperature: 18 }]}
        lines={[{ key: "temperature", name: "Temperature", color: chartColors.primary }]}
      />,
    );
    expect(screen.getByRole("img", { name: "Hourly forecast temperature" })).toBeVisible();
  });

  it("acknowledges an open alert", async () => {
    const onChange = vi.fn();
    render(<AlertActions status="open" onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(onChange).toHaveBeenCalledWith("acknowledged");
  });
});
