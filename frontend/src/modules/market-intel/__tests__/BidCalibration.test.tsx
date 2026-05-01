import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import type { CalibrationPoint } from "../api/types";

/**
 * Final per-tab test (slice 4 — brief-closer). Mirrors the
 * slice-2/3 setup: hook mocked at module boundary, Recharts
 * `ResponsiveContainer` stubbed for happy-dom, four required states
 * exercised, plus the brief's extra ask — assert that exactly one
 * row carries the most-recent-quarter highlight.
 */

vi.mock("../hooks/useBidCalibration", () => ({
  useBidCalibration: vi.fn(),
  bidCalibrationKey: {
    all: ["market-intel", "bid-calibration"],
    list: () => ["market-intel", "bid-calibration"],
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

import BidCalibration from "../components/BidCalibration";
import { useBidCalibration } from "../hooks/useBidCalibration";

// ── Fixtures ────────────────────────────────────────────────────────
//
// 4 quarters in chronological order so the tests can lock both axis
// ordering and most-recent-row highlight.

const Q1_24: CalibrationPoint = {
  quarter: "2024-04-01",
  bids_submitted: 14,
  wins: 2,
  avg_rank: 3.2,
  pct_above_low: 0.094,
};
const Q3_24: CalibrationPoint = {
  quarter: "2024-10-01",
  bids_submitted: 22,
  wins: 5,
  avg_rank: 2.4,
  pct_above_low: 0.078,
};
const Q1_25: CalibrationPoint = {
  quarter: "2025-04-01",
  bids_submitted: 24,
  wins: 6,
  avg_rank: 2.2,
  pct_above_low: 0.061,
};
const Q1_26: CalibrationPoint = {
  quarter: "2026-01-01",
  bids_submitted: 28,
  wins: 9,
  avg_rank: 1.7,
  pct_above_low: 0.018,
};

function makeQueryResult(
  partial: Partial<UseQueryResult<CalibrationPoint[], Error>>,
): UseQueryResult<CalibrationPoint[], Error> {
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
  } as UseQueryResult<CalibrationPoint[], Error>;
}

const mockedHook = vi.mocked(useBidCalibration);

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BidCalibration />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedHook.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ── Empty ───────────────────────────────────────────────────────────

describe("BidCalibration — empty state", () => {
  it("shows the 'no calibration data yet' copy when the dataset is empty", () => {
    mockedHook.mockReturnValue(
      makeQueryResult({ data: [], isSuccess: true }),
    );
    renderTab();

    const empty = screen.getByTestId("calibration-empty");
    expect(within(empty).getByText(/no calibration data yet/i)).toBeInTheDocument();

    // Empty path must NOT render the chart, the annotation, or the table.
    expect(screen.queryByRole("figure")).not.toBeInTheDocument();
    expect(screen.queryByTestId("calibration-annotation")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

// ── Loading ─────────────────────────────────────────────────────────

describe("BidCalibration — loading state", () => {
  it("shows an aria-busy skeleton while isLoading", () => {
    mockedHook.mockReturnValue(
      makeQueryResult({ isLoading: true, isPending: true }),
    );
    renderTab();

    const status = screen.getByTestId("calibration-loading");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveAttribute("aria-busy");
    expect(status).toHaveAccessibleName(/loading bid calibration/i);
  });
});

// ── Error ───────────────────────────────────────────────────────────

describe("BidCalibration — error state", () => {
  it("shows the canonical error banner with a Retry button that calls refetch", async () => {
    const refetch = vi.fn();
    mockedHook.mockReturnValue(
      makeQueryResult({
        isError: true,
        error: new Error("boom"),
        refetch: refetch as unknown as UseQueryResult<
          CalibrationPoint[],
          Error
        >["refetch"],
      }),
    );
    renderTab();

    const banner = screen.getByTestId("calibration-error");
    expect(banner).toHaveAttribute("role", "alert");
    expect(within(banner).getByText(/couldn't load bid calibration/i))
      .toBeInTheDocument();

    const retry = within(banner).getByRole("button", { name: /retry/i });
    await userEvent.click(retry);
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

// ── Populated ───────────────────────────────────────────────────────

describe("BidCalibration — populated state", () => {
  beforeEach(() => {
    // Pass the rows in DESC order to also exercise the chronological
    // sort the component is supposed to apply.
    mockedHook.mockReturnValue(
      makeQueryResult({
        data: [Q1_26, Q1_25, Q3_24, Q1_24],
        isSuccess: true,
      }),
    );
  });

  it("renders the brief annotation copy verbatim", () => {
    renderTab();
    const annotation = screen.getByTestId("calibration-annotation");
    expect(annotation).toHaveTextContent(
      "Lower coral = sharper pricing. Higher teal = more wins. Watch them move together.",
    );
  });

  it("renders the labelled composed chart figure", () => {
    renderTab();
    const figure = screen.getByRole("figure", {
      name: /bid calibration composed chart/i,
    });
    expect(figure).toBeInTheDocument();
  });

  it("renders the table with one row per quarter", () => {
    renderTab();
    const table = screen.getByRole("table");
    // 1 header row + 4 data rows = 5 total
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(within(table).getByText("Q1 '26")).toBeInTheDocument();
    expect(within(table).getByText("Q2 '24")).toBeInTheDocument();
  });

  it("highlights exactly one row as the most-recent quarter", () => {
    const { container } = renderTab();
    const highlighted = container.querySelectorAll('[data-current="true"]');
    expect(highlighted).toHaveLength(1);
    // Q1 '26 (2026-01-01) is the latest in the fixture.
    expect(highlighted[0]).toHaveTextContent("Q1 '26");
    // The brief calls for "subtle background, not a separate component" —
    // assert the muted/40 utility class is on the row.
    expect(highlighted[0].className).toMatch(/bg-muted\/40/);
    // a11y mirror of the highlight via aria-current.
    expect(highlighted[0]).toHaveAttribute("aria-current", "page");
  });

  it("computes win rate per row from bids and wins", () => {
    renderTab();
    const table = screen.getByRole("table");
    // Q1_26: 9 / 28 = 32.1%
    expect(within(table).getByText("32.1%")).toBeInTheDocument();
    // Q1_24: 2 / 14 = 14.3%
    expect(within(table).getByText("14.3%")).toBeInTheDocument();
  });
});
