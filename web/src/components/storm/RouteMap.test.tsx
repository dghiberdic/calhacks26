import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { StormRun } from "@/api/types";
import { RouteMap } from "./RouteMap";

const viewport = vi.hoisted(() => ({ width: 1100 }));
vi.mock("./useWidth", () => ({ useWidth: () => [{ current: null }, viewport.width] }));
afterEach(cleanup);

const run = (reverse = false) => ({
  id: "EIDW@2025-01-24", station: "EIDW", date: "2025-01-24",
  windows: [], metar: [], questions: [], learned: [], feed: [],
  flights: [{
    flight: { id: "NS31@2025-01-24", number: "NS31", origin: reverse ? "BOS" : "DUB",
      dest: reverse ? "DUB" : "BOS", pax: 172, status: "cancelled",
      sched_dep: "2025-01-24T16:30:00Z", sched_arr: "2025-01-24T23:45:00Z" },
    decision: null,
  }],
}) as unknown as StormRun;

const pointsOf = (path: string) => [...path.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);

describe("great-circle route map", () => {
  it.each([[360, true], [360, false], [1100, false]] as const)("curves the Atlantic route and fits the whole arc at %i pixels (compact %s)", (width, compact) => {
    viewport.width = width;
    render(<RouteMap run={run()} animate={false} compact={compact} />);
    const route = screen.getByTestId("route-BOS");
    const d = route.querySelector("path")!.getAttribute("d")!;
    const points = pointsOf(d);
    expect(points.length).toBeGreaterThan(2);
    const [start, end] = [points[0], points.at(-1)!];
    const chordLength = Math.hypot(end[0] - start[0], end[1] - start[1]);
    const deviations = points.map(([x, y]) => Math.abs((end[0] - start[0]) * (y - start[1]) - (end[1] - start[1]) * (x - start[0])) / chordLength);
    expect(Math.max(...deviations)).toBeGreaterThan(8);
    const height = Number(screen.getByRole("img").getAttribute("height"));
    for (const [x, y] of points) {
      expect(x).toBeGreaterThanOrEqual(27.9);
      expect(x).toBeLessThanOrEqual(width - 27.9);
      expect(y).toBeGreaterThanOrEqual(27.9);
      expect(y).toBeLessThanOrEqual(height - 27.9);
    }
    const endpoint = route.querySelector("circle")!;
    expect(end[0]).toBeCloseTo(Number(endpoint.getAttribute("cx")), 2);
    expect(end[1]).toBeCloseTo(Number(endpoint.getAttribute("cy")), 2);
  });

  it("uses the same curved hit area for hover and flight selection, including return flights", () => {
    viewport.width = 1100;
    const select = vi.fn();
    render(<RouteMap run={run(true)} animate={false} onSelectFlight={select} />);
    const route = screen.getByTestId("route-BOS");
    const paths = route.querySelectorAll("path");
    expect(paths).toHaveLength(2);
    expect(paths[1].getAttribute("d")).toBe(paths[0].getAttribute("d"));
    fireEvent.pointerEnter(route);
    expect(screen.getByText(/DUB–BOS · Boston/)).toBeVisible();
    fireEvent.click(paths[1]);
    expect(select).toHaveBeenCalledWith("NS31@2025-01-24");
  });

  it("keeps Pacific routes continuous across the geographic date line", () => {
    viewport.width = 1100;
    const pacific = run();
    pacific.station = "KSFO";
    pacific.flights[0].flight.origin = "SFO";
    pacific.flights[0].flight.dest = "NRT";
    pacific.airports = [{ iata: "NRT", icao: "RJAA", name: "Tokyo Narita", lon: 140.39, lat: 35.77 }] as StormRun["airports"];
    render(<RouteMap run={pacific} animate={false} />);
    const d = screen.getByTestId("route-NRT").querySelector("path")!.getAttribute("d")!;
    expect(d.match(/M/g)).toHaveLength(1);
    expect(d).not.toMatch(/NaN|Infinity/);
    expect(pointsOf(d).length).toBeGreaterThan(2);
  });

  it.each([false, true])("keeps the map finite with no distinct destinations (duplicate %s)", (duplicate) => {
    const empty = run();
    if (duplicate) empty.flights[0].flight.dest = "DUB";
    else empty.flights = [];
    render(<RouteMap run={empty} animate={false} />);
    for (const path of screen.getByRole("img").querySelectorAll("path")) {
      expect(path.getAttribute("d")).not.toMatch(/NaN|Infinity/);
    }
    const circle = screen.getByRole("img").querySelector("circle")!;
    expect(Number(circle.getAttribute("cx"))).toBeCloseTo(viewport.width / 2);
  });
});
