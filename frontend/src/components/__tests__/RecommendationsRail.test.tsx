import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { InsightResponse } from "@/lib/recommendations";

// Mock the fetcher BEFORE importing the rail, so RecommendationsRail's
// closure picks up the mock instead of the real network client.
vi.mock("@/lib/recommendations", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/recommendations")
  >("@/lib/recommendations");
  return {
    ...actual,
    fetchRecommendations: vi.fn(),
  };
});

import { RecommendationsRail } from "@/components/RecommendationsRail";
import { fetchRecommendations } from "@/lib/recommendations";

/**
 * Locks in the public a11y contract from RecommendationsRail.tsx:
 *   - Card has role="region" + aria-labelledby + aria-busy
 *   - sr-only aria-live="polite" status text
 *   - severity Badge has aria-label="Severity: {level}"
 *   - roving-tabindex over cards (Arrow / Home / End)
 *   - reduced-motion utilities on spinner + skeleton
 */

const MOCK_RESPONSE: InsightResponse = {
  module: "equipment",
  generated_at: "2026-04-28T12:00:00Z",
  model: "claude-sonnet-4-20250514",
  revision_token: "rev-1",
  is_stub: false,
  input_tokens: 0,
  output_tokens: 0,
  recommendations: [
    {
      title: "Replace hydraulic hose on Excavator-CAT-336",
      severity: "critical",
      rationale: "Pressure variance trending high.",
      suggested_action: "Schedule shop visit before Friday's pour.",
      affected_assets: ["EQ-001234", "EQ-001235"],
    },
    {
      title: "Fuel cost spiking on Truck-12",
      severity: "warning",
      rationale: "Cost per hour 35% above peer average.",
      suggested_action: "Inspect injector pump.",
      affected_assets: ["EQ-002001"],
    },
    {
      title: "Coding suggestion available",
      severity: "info",
      rationale: "Pattern match on prior jobs.",
      suggested_action: "Apply with one click.",
      affected_assets: [],
    },
  ],
};

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

describe("RecommendationsRail — ARIA contract", () => {
  beforeEach(() => {
    vi.mocked(fetchRecommendations).mockResolvedValue(MOCK_RESPONSE);
  });

  it("renders a labelled region with aria-busy mirroring fetch state", async () => {
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    const region = screen.getByRole("region", { name: /recommendations/i });
    expect(region).toBeInTheDocument();
    // Initially loading → aria-busy=true
    expect(region).toHaveAttribute("aria-busy", "true");

    // Once data arrives, aria-busy flips to false
    await waitFor(() =>
      expect(region).toHaveAttribute("aria-busy", "false"),
    );
  });

  it("publishes a polite sr-only status announcement", async () => {
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    const region = screen.getByRole("region", { name: /recommendations/i });
    const liveRegions = region.querySelectorAll('[aria-live="polite"]');
    expect(liveRegions.length).toBeGreaterThan(0);
    const live = liveRegions[0] as HTMLElement;
    expect(live.className).toContain("sr-only");

    await waitFor(() =>
      expect(live.textContent).toMatch(/3 recommendations loaded/),
    );
  });

  it("labels severity badges with their level for screen readers", async () => {
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    await waitFor(() =>
      expect(
        screen.getByText("Replace hydraulic hose on Excavator-CAT-336"),
      ).toBeInTheDocument(),
    );

    expect(
      screen.getByLabelText("Severity: critical"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Severity: warning"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Severity: info")).toBeInTheDocument();
  });

  it("exposes affected-assets as a labelled list", async () => {
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    await waitFor(() =>
      expect(
        screen.getByText("Replace hydraulic hose on Excavator-CAT-336"),
      ).toBeInTheDocument(),
    );

    const assetList = screen.getByLabelText(/2 affected assets/i);
    expect(assetList).toBeInTheDocument();
    expect(within(assetList).getByText("EQ-001234")).toBeInTheDocument();
    expect(within(assetList).getByText("EQ-001235")).toBeInTheDocument();
  });
});

describe("RecommendationsRail — roving tabindex", () => {
  beforeEach(() => {
    vi.mocked(fetchRecommendations).mockResolvedValue(MOCK_RESPONSE);
  });

  it("starts with the first card focusable, others non-tabbable", async () => {
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    await waitFor(() =>
      expect(
        screen.getByText("Replace hydraulic hose on Excavator-CAT-336"),
      ).toBeInTheDocument(),
    );

    const articles = screen.getAllByRole("article");
    expect(articles.length).toBe(3);
    expect(articles[0]).toHaveAttribute("tabindex", "0");
    expect(articles[1]).toHaveAttribute("tabindex", "-1");
    expect(articles[2]).toHaveAttribute("tabindex", "-1");
  });

  it("ArrowDown shifts focus to the next card and updates tabindex", async () => {
    const user = userEvent.setup();
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    const articles = await screen.findAllByRole("article");
    articles[0].focus();
    expect(articles[0]).toHaveFocus();

    await user.keyboard("{ArrowDown}");

    expect(articles[1]).toHaveFocus();
    expect(articles[1]).toHaveAttribute("tabindex", "0");
    expect(articles[0]).toHaveAttribute("tabindex", "-1");
  });

  it("End jumps to the last card; Home returns to the first", async () => {
    const user = userEvent.setup();
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    const articles = await screen.findAllByRole("article");
    articles[0].focus();

    await user.keyboard("{End}");
    expect(articles[2]).toHaveFocus();

    await user.keyboard("{Home}");
    expect(articles[0]).toHaveFocus();
  });

  it("ArrowUp at index 0 stays put (no wrap)", async () => {
    const user = userEvent.setup();
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);

    const articles = await screen.findAllByRole("article");
    articles[0].focus();

    await user.keyboard("{ArrowUp}");
    expect(articles[0]).toHaveFocus();
  });
});

describe("RecommendationsRail — reduced motion", () => {
  beforeEach(() => {
    vi.mocked(fetchRecommendations).mockResolvedValue(MOCK_RESPONSE);
  });

  it("skeleton blocks include motion-reduce:animate-none", () => {
    renderWithClient(<RecommendationsRail moduleSlug="equipment" />);
    // Skeleton renders synchronously while the query resolves.
    const skeletons = document.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
    skeletons.forEach((node) => {
      expect(node.className).toContain("motion-reduce:animate-none");
    });
  });
});
