import { QueryClient } from "@tanstack/react-query";

/**
 * Process-wide TanStack Query client.
 *
 * Defaults:
 *   staleTime 30s — matches the "30s stale time" the mockup's
 *     Auto Refresh toggle targets. Individual queries can override per
 *     useQuery call when they need fresher data (e.g. live dashboards).
 *   retry 1    — fail fast in dev; the backend either answers or not.
 *   refetchOnWindowFocus false — dashboards are noisy enough already.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
