import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface ModulePlaceholderProps {
  /** Human-readable module name. */
  title: string;
  /**
   * Optional API path for a summary endpoint. If provided, the page
   * fetches it on mount and displays the raw JSON response.
   * Omit for modules whose backend isn't built yet.
   */
  apiPath?: string;
  /** Optional one-liner under the title (e.g. "coming soon"). */
  subtitle?: string;
}

/**
 * Placeholder page template used by Commit 1 for all 17 module pages.
 * Commit 2+ replaces these with real feature implementations.
 *
 * Exists so the route tree is wired end-to-end before any module is
 * actually built — click through the nav, confirm API calls land, confirm
 * tenant scoping works, then iterate.
 */
export function ModulePlaceholder({
  title,
  apiPath,
  subtitle,
}: ModulePlaceholderProps) {
  const query = useQuery({
    queryKey: [apiPath ?? title],
    queryFn: async () => {
      if (!apiPath) return null;
      const { data } = await api.get(apiPath);
      return data;
    },
    enabled: !!apiPath,
  });

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {subtitle && (
        <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
      )}

      {apiPath ? (
        <section className="mt-6">
          <div className="text-xs font-mono text-muted-foreground">
            GET {apiPath}
          </div>

          {query.isLoading && (
            <div className="mt-3 text-sm text-muted-foreground">Loading…</div>
          )}

          {query.isError && (
            <div className="mt-3 rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
              Error: {(query.error as Error).message}
            </div>
          )}

          {query.data && (
            <pre className="mt-3 rounded-md border border-border bg-card p-4 text-xs overflow-auto max-h-[60vh]">
              {JSON.stringify(query.data, null, 2)}
            </pre>
          )}
        </section>
      ) : (
        <p className="mt-6 text-sm text-muted-foreground">
          Backend not yet wired for this module. Placeholder page — the
          module's real feature lands in a later commit.
        </p>
      )}
    </div>
  );
}
