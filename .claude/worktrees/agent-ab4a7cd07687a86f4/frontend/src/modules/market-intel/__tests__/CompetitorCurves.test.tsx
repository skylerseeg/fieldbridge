import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import type { CompetitorCurveRow } from "../api/types";

/**
 * Per-brief acceptance: each tab covers four states — empty,
 * loading, error, populated. The hook is mocked at the module
 * boundary so the test drives the state directly without the
 * TanStack/axios/mock-fixture stack underneath.
 *
 * Recharts' ResponsiveContainer is stubbed because happy-dom can't
 * size the wrapper; the chart's *structure* (figure role + a11y
 * label) is asserted, not its rendered geometry.
 */

vi.mock("../hooks/useCompetitorCurves", () => ({
  useCompetitorCurves: vi.fn(),
  competitorCurvesKey: {
    all: ["market-intel", "competitor-curves"],
    list: () => ["market-intel", "competitor-curves"],
  },
}));

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="rc-mock" style={{ width: 600, height: 300 }}>
        {children}
      </div>
    ),
  };
});

import CompetitorCurves from "../components/CompetitorCurves";
import { useCompetitorCurves } from "../hooks/useCompetitorCurves";

// ── Fixtures ────────────────────────────────────────────────────────

const ROW_A: CompetitorCurveRow = {
  contractor_name: "Sunroc Corporation",
  bid_count: 142,
  avg_premium_over_low: 0.038,
  median_rank: 1.7,
  win_rate: 0.36,
};

const ROW_B: CompetitorCurveRow = {
  contractor_name: "Geneva Rock Products",
  bid_count: 168,
  avg_premium_over_low: 0.045,
  median_rank: 1.9,
  win_rate: 0.32,
};

const ROW_C: CompetitorCurveRow = {
  contractor_name: "Burdick Materials",
  bid_count: 18,
  avg_premium_over_low: 0.176,
  median_rank: 4.8,
  win_rate: 0.05,
};

// Minimal subset of UseQueryResult that the component actually reads.
// We only need data / isLoading / isError / refetch — the rest of the
// massive react-query result type can be cast as any-via-Partial here
// without leaking `any` into the production code.
function makeQueryResult(
  partial: Partial<UseQueryResult<CompetitorCurveRow[], Error>>,
): UseQueryResult<CompetitorCurveRow[], Error> {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    error: null,
    isPending: false,
    isSuccess: false,
    isFetching: false,
    isStale: false,
    status: "pending",
    fetchStatus: "idle",
    ...partial,
  } as UseQueryResult<CompetitorCurveRow[], Error>;
}

const mockedHook = vi.mocked(useCompetitorCurves);

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <CompetitorCurves states={["UT", "ID"]} monthsBack={36} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockedHook.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ── Empty ───────────────────────────────────────────────────────────

describe("CompetitorCurves — empty state", () => {
  it("shows the 'not enough bid history' copy when the dataset is empty", () => {
    mockedHook.mockReturnValue(makeQueryResult({ data: [], isSuccess: true }));
    renderTab();

    const empty = screen.getByTestId("curves-empty");
    expect(empty).toBeInTheDocument();
    expect(within(empty).getByText(/not enough bid history yet/i)).toBeInTheDocument();
    // Brief copy: "Pipeline ingests new awards nightly."
    expect(
      within(empty).getByText(/pipeline ingests new awards nightly/i),
    ).toBeInTheDocument();

    // Empty path must NOT render the chart figure or the table.
    expect(
      screen.queryByRole("figure", { name: /competitor curves scatter/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

// ── Loading ─────────────────────────────────────────────────────────

describe("CompetitorCurves — loading state", () => {
  it("shows an aria-busy skeleton while isLoading", () => {
    mockedHook.mockReturnValue(
      makeQueryResult({ isLoading: true, isPending: true }),
    );
    renderTab();

    const status = screen.getByTestId("curves-loading");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-busy");
    expect(status).toHaveAccessibleName(/loading competitor curves/i);

    // Loading path must NOT render the chart figure or the table.
    expect(
      screen.queryByRole("figure", { name: /competitor curves scatter/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

// ── Error ───────────────────────────────────────────────────────────

describe("CompetitorCurves — error state", () => {
  it("shows the canonical error banner with a Retry button that calls refetch", async () => {
    const refetch = vi.fn();
    mockedHook.mockReturnValue(
      makeQueryResult({
        isError: true,
        error: new Error("boom"),
        refetch: refetch as unknown as UseQueryResult<
          CompetitorCurveRow[],
          Error
        >["refetch"],
      }),
    );
    renderTab();

    const banner = screen.getByTestId("curves-error");
    expect(banner).toHaveAttribute("role", "alert");
    expect(banner).toHaveAttribute("aria-live", "assertive");
    expect(within(banner).getByText(/couldn't load competitor curves/i))
      .toBeInTheDocument();

    const retry = within(banner).getByRole("button", { name: /retry/i });
    await userEvent.click(retry);
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

// ── Populated ───────────────────────────────────────────────────────

describe("CompetitorCurves — populated state", () => {
  beforeEach(() => {
    mockedHook.mockReturnValue(
      makeQueryResult({
        data: [ROW_A, ROW_B, ROW_C],
        isSuccess: true,
      }),
    );
  });

  it("renders the labelled scatter figure and the contractor table", () => {
    renderTab();

    // Chart structure: a <figure role="figure"> with the brief's a11y label.
    const figure = screen.getByRole("figure", {
      name: /competitor curves scatter/i,
    });
    expect(figure).toBeInTheDocument();

    // Table is keyboard-reachable; every contractor present.
    const table = screen.getByRole("table");
    expect(within(table).getByText("Sunroc Corporation")).toBeInTheDocument();
    expect(within(table).getByText("Geneva Rock Products")).toBeInTheDocument();
    expect(within(table).getByText("Burdick Materials")).toBeInTheDocument();
  });

  it("toggles sort direction on the bids column when the header is clicked twice", async () => {
    renderTab();

    const bidsHeader = screen.getByRole("button", { name: /^bids/i });
    // Default state: sorted by bid_count desc → first row should be Geneva (168).
    let rows = screen.getAllByRole("button", { name: /open .* drilldown/i });
    expect(rows[0]).toHaveTextContent("Geneva Rock Products");

    await userEvent.click(bidsHeader); // → asc
    rows = screen.getAllByRole("button", { name: /open .* drilldown/i });
    expect(rows[0]).toHaveTextContent("Burdick Materials"); // bid_count 18

    await userEvent.click(bidsHeader); // → desc again
    rows = screen.getAllByRole("button", { name: /open .* drilldown/i });
    expect(rows[0]).toHaveTextContent("Geneva Rock Products");
  });

  it("opens the drilldown sheet when a table row is activated and exposes 'View bid history'", async () => {
    renderTab();

    // Drilldown is closed initially — no sheet dialog.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // Activate a row by keyboard (Enter) so we lock that path too.
    const sunrocRow = screen.getByRole("button", {
      name: /open sunroc corporation drilldown/i,
    });
    sunrocRow.focus();
    await userEvent.keyboard("{Enter}");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Sunroc Corporation")).toBeInTheDocument();
    // Detail values render through formatted percent / count helpers.
    expect(within(dialog).getByText("142")).toBeInTheDocument(); // bid_count
    expect(within(dialog).getByText("36.0%")).toBeInTheDocument(); // win_rate
    expect(within(dialog).getByText("3.8%")).toBeInTheDocument(); // premium

    expect(
      within(dialog).getByRole("button", { name: /view bid history/i }),
    ).toBeInTheDocument();
  });
});
