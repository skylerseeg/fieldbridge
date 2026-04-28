import { MsalProvider } from "@azure/msal-react";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import { TooltipProvider } from "@/components/ui/tooltip";
import { getMsalInstance, isMsalConfigured } from "@/lib/msal";
import { queryClient } from "@/lib/queryClient";
import { router } from "@/routes";

/**
 * Top-level provider tree. Lives in its own file so main.tsx stays an
 * entry-point-only module — required by the eslint react-refresh rule
 * (entry files must not declare components inline).
 *
 * If the Azure env vars aren't set (e.g. a developer running the SPA
 * without Microsoft SSO credentials), we skip MsalProvider entirely so
 * the MSAL instance isn't constructed with placeholder client IDs.
 * The LoginPage uses `isMsalConfigured` to hide the SSO button in that
 * case and fall back to the dev stub.
 */
export function Root() {
  const tree = (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>
  );

  if (!isMsalConfigured) {
    return tree;
  }

  return <MsalProvider instance={getMsalInstance()}>{tree}</MsalProvider>;
}
