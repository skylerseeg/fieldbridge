import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import type { OpportunityRow } from "../api/types";

/**
 * Per-brief acceptance: every tab covers four states — empty,
 * loading, error, populated. Mirrors the slice-2 setup used for
 * `CompetitorCurves.test.tsx`:
 *
 *   - Hook mocked at module boundary so we drive state directly.
 *   - Recharts' `ResponsiveContainer` stubbed (happy-dom can't size).
 *   - `MemoryRouter` for `useNavigate` inside the top-10 list.
 *   - A small `<LocationProbe />` route catches the navigated path
 *     so we can assert the gap-detail URL contract.
 */

vi.mock("../hooks/useOpportunityGaps", () => ({
  useOpportunityGaps: vi.fn(),
  opportunityGapsKey: {
    all: ["market-intel", "opportunity-gaps"],
    list: () => ["market-intel", "opportunity-gaps"],
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

import OpportunityGaps from "../components/OpportunityGaps";
import { useOpportunityGaps } from "../hooks/useOpportunityGaps";

// ── Fixtures ────────────────────────────────────────────────────────

const ROW_UT_SLC: OpportunityRow = {
  state: "UT",
  county: "Salt Lake",
  missed_count: 18,
  avg_low_bid: 1_240_000,
  top_scope_codes: ["32 11 23", "31 23 16"],
};

const ROW_ID_ADA: OpportunityRow = {
  state: "ID",
  county: "Ada",
  missed_count: 24,
  avg_low_bid: 1_820_000,
  top_scope_codes: ["32 11 23", "31 23 16"],
};

const ROW_NV_CLARK: OpportunityRow = {
  state: "NV",
  county: "Clark",
  missed_count: 22,
  avg_low_bid: 3_120_000,
  top_scope_codes: ["32 11 23", "33 41 00"],
};

// A row whose scope codes don't intersect with the others — useful
// for the scope-filter exercise.
const ROW_WY_TETON: OpportunityRow = {
  state: "WY",
  county: "Teton",
  missed_count: 3,
  avg_low_bid: 1_980_000,
  top_scope_codes: ["02 23 99"], // unique scope
};

function makeQueryResult(
  partial: Partial<UseQueryResult<OpportunityRow[], Error>>,
): UseQueryResult<OpportunityRow[], Error> {
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
  } as UseQueryResult<OpportunityRow[], Error>;
}

const mockedHook = vi.mocked(useOpportunityGaps);

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <MemoryRouter initialEntries={["/market-intel"]}>
      <QueryClientProvider client={client}>
        <Routes>
          <Route path="/market-intel" element={<OpportunityGaps monthsBack={36} />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
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

describe("OpportunityGaps — empty state", () => {
  it("shows the brief 'no gaps to surface yet' copy when the dataset is empty", () => {
    mockedHook.mockReturnValue(
      makeQueryResult({ data: [], isSuccess: true }),
    );
    renderTab();

    const empty = screen.getByTestId("gaps-empty");
    expect(empty).toBeInTheDocument();
    expect(within(empty).getByText(/no gaps to surface yet/i)).toBeInTheDocument();

    // Empty path must NOT render the chart figure or the top-10 list.
    expect(
      screen.queryByRole("figure", { name: /opportunity gaps bar chart/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /top opportunity gaps/i }),
    ).not.toBeInTheDocument();
  });
});

// ── Loading ─────────────────────────────────────────────────────────

describe("OpportunityGaps — loading state", () => {
  it("shows an aria-busy skeleton while isLoading", () => {
    mockedHook.mockReturnValue(
      makeQueryResult({ isLoading: true, isPending: true }),
    );
    renderTab();

    const status = screen.getByTestId("gaps-loading");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-busy");
    expect(status).toHaveAccessibleName(/loading opportunity gaps/i);

    expect(
      screen.queryByRole("figure", { name: /opportunity gaps bar chart/i }),
    ).not.toBeInTheDocument();
  });
});

// ── Error ───────────────────────────────────────────────────────────

describe("OpportunityGaps — error state", () => {
  it("shows the canonical error banner with a Retry button that calls refetch", async () => {
    const refetch = vi.fn();
    mockedHook.mockReturnValue(
      makeQueryResult({
        isError: true,
        error: new Error("boom"),
        refetch: refetch as unknown as UseQueryResult<
          OpportunityRow[],
          Error
        >["refetch"],
      }),
    );
    renderTab();

    const banner = screen.getByTestId("gaps-error");
    expect(banner).toHaveAttribute("role", "alert");
    expect(banner).toHaveAttribute("aria-live", "assertive");
    expect(within(banner).getByText(/couldn't load opportunity gaps/i))
      .toBeInTheDocument();

    const retry = within(banner).getByRole("button", { name: /retry/i });
    await userEvent.click(retry);
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

// ── Populated ───────────────────────────────────────────────────────

describe("OpportunityGaps — populated state", () => {
  beforeEach(() => {
    mockedHook.mockReturnValue(
      makeQueryResult({
        data: [ROW_UT_SLC, ROW_ID_ADA, ROW_NV_CLARK, ROW_WY_TETON],
        isSuccess: true,
      }),
    );
  });

  it("renders the labelled bar figure and the top-N list with all rows", () => {
    renderTab();

    const figure = screen.getByRole("figure", {
      name: /opportunity gaps bar chart/i,
    });
    expect(figure).toBeInTheDocument();

    const list = screen.getByRole("region", {
      name: /top opportunity gaps ranked by missed count/i,
    });
    expect(within(list).getByText(/ada, id/i)).toBeInTheDocument();
    expect(within(list).getByText(/clark, nv/i)).toBeInTheDocument();
    expect(within(list).getByText(/salt lake, ut/i)).toBeInTheDocument();
    expect(within(list).getByText(/teton, wy/i)).toBeInTheDocument();
  });

  it("ranks the top-list by missed_count desc — Ada (24) leads, Teton (3) trails", () => {
    renderTab();
    const items = screen.getAllByRole("button", {
      name: /open .* bid history/i,
    });
    expect(items[0]).toHaveTextContent(/ada, id/i);
    expect(items[items.length - 1]).toHaveTextContent(/teton, wy/i);
  });

  it("navigates to the gap detail URL when a top-list row is clicked", async () => {
    renderTab();
    const adaRow = screen.getByRole("button", {
      name: /open ada, id bid history/i,
    });
    await userEvent.click(adaRow);
    expect(screen.getByTestId("location-probe")).toHaveTextContent(
      "/market-intel/gap/ID/Ada",
    );
  });

  it("scope-filter — deselecting all scopes shows the no-match empty state with a reset button that restores", async () => {
    renderTab();

    // Pre: all four rows visible.
    expect(
      screen.getAllByRole("button", { name: /open .* bid history/i }),
    ).toHaveLength(4);

    // Open scope filter, click "None" to clear.
    const filterTrigger = screen.getByRole("button", {
      name: /filter by scope code/i,
    });
    await userEvent.click(filterTrigger);
    const noneButton = await screen.findByRole("button", { name: /^none$/i });
    await userEvent.click(noneButton);
    // Close the menu (Escape so we don't depend on outside-click).
    await userEvent.keyboard("{Escape}");

    // No-match empty state appears, original chart + list are gone.
    const noMatch = await screen.findByTestId("gaps-no-match");
    expect(noMatch).toBeInTheDocument();
    expect(
      screen.queryByRole("figure", { name: /opportunity gaps bar chart/i }),
    ).not.toBeInTheDocument();

    // Reset button restores the rows.
    const reset = within(noMatch).getByRole("button", { name: /reset filter/i });
    await userEvent.click(reset);

    expect(
      screen.getAllByRole("button", { name: /open .* bid history/i }),
    ).toHaveLength(4);
  });
});
