import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "@/layouts/AppShell";
import { RequireAuth } from "@/layouts/RequireAuth";
import { LoginPage } from "@/pages/LoginPage";

// Main menu
import { HomePage } from "@/modules/home/HomePage";
import { ExecutiveDashboardPage } from "@/modules/executive-dashboard/ExecutiveDashboardPage";
import { ActivityFeedPage } from "@/modules/activity-feed/ActivityFeedPage";

// Operations
import { EquipmentPage } from "@/modules/equipment/EquipmentPage";
import { WorkOrdersPage } from "@/modules/work-orders/WorkOrdersPage";
import { TimecardsPage } from "@/modules/timecards/TimecardsPage";
import { JobsPage } from "@/modules/jobs/JobsPage";

// Finance
import { FleetPnlPage } from "@/modules/fleet-pnl/FleetPnlPage";
import { VendorsPage } from "@/modules/vendors/VendorsPage";
import { CostCodingPage } from "@/modules/cost-coding/CostCodingPage";

// Intelligence
import { PredictiveMaintenancePage } from "@/modules/predictive-maintenance/PredictiveMaintenancePage";
import { RecommendationsPage } from "@/modules/recommendations/RecommendationsPage";
import { BidsPage } from "@/modules/bids/BidsPage";
import { ProposalsPage } from "@/modules/proposals/ProposalsPage";

// Knowledge
import { ProjectSearchPage } from "@/modules/project-search/ProjectSearchPage";
import { MediaLibraryPage } from "@/modules/media-library/MediaLibraryPage";
import { SafetyPage } from "@/modules/safety/SafetyPage";

// Internal — design system reference (no sidebar nav, dev-only URL)
import { StyleGuide } from "@/components/style-guide/StyleGuide";

/**
 * Route tree.
 *
 * Nesting:
 *   /login                  — public
 *   <RequireAuth>           — everything below requires a token
 *     <AppShell>            — sidebar + topbar + <Outlet />
 *       /dashboard          — home
 *       /executive-dashboard
 *       /activity-feed
 *       /equipment … /safety
 *
 * Path conventions match the backend module prefixes exactly
 * (/api/work-orders → /work-orders in the UI, etc.). Keeps the nav
 * predictable when you stare at URLs.
 */
export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },

          // Main menu
          { path: "dashboard", element: <HomePage /> },
          { path: "executive-dashboard", element: <ExecutiveDashboardPage /> },
          { path: "activity-feed", element: <ActivityFeedPage /> },

          // Operations
          { path: "equipment", element: <EquipmentPage /> },
          // Direct bookmark URL for the field Status Board. EquipmentPage's
          // <Tabs defaultValue="status"> means both /equipment and
          // /equipment/status land on the same view; this route just
          // gives field users a copy-pasteable URL.
          { path: "equipment/status", element: <EquipmentPage /> },
          { path: "work-orders", element: <WorkOrdersPage /> },
          { path: "timecards", element: <TimecardsPage /> },
          { path: "jobs", element: <JobsPage /> },

          // Finance
          { path: "fleet-pnl", element: <FleetPnlPage /> },
          { path: "vendors", element: <VendorsPage /> },
          { path: "cost-coding", element: <CostCodingPage /> },

          // Intelligence
          { path: "predictive-maintenance", element: <PredictiveMaintenancePage /> },
          { path: "recommendations", element: <RecommendationsPage /> },
          { path: "bids", element: <BidsPage /> },
          { path: "proposals", element: <ProposalsPage /> },

          // Knowledge
          { path: "project-search", element: <ProjectSearchPage /> },
          { path: "media-library", element: <MediaLibraryPage /> },
          { path: "safety", element: <SafetyPage /> },

          // Internal — design system reference (no sidebar nav, dev-only)
          { path: "style-guide", element: <StyleGuide /> },

          { path: "*", element: <Navigate to="/dashboard" replace /> },
        ],
      },
    ],
  },
]);
