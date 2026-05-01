import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  AlertTriangle,
  Info,
  RefreshCcw,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  fetchRecommendations,
  type InsightResponse,
  type Recommendation,
  type Severity,
} from "@/lib/recommendations";

/**
 * Phase-6 right-rail card that renders Claude-generated next-actions
 * for a module.
 *
 * Behavior:
 *   - Fetches `GET /api/<moduleSlug>/recommendations` via TanStack
 *     Query, keyed on the slug. The backend caches the underlying
 *     LLM call for 6h, so repeated mounts are essentially free.
 *   - `staleTime: 5 minutes` — within a session we don't want to
 *     re-hit the endpoint on every tab switch even though the
 *     server-side cache would short-circuit anyway.
 *   - Renders a "stub" affordance when `is_stub` is true, so the
 *     operator sees a clear "configure ANTHROPIC_API_KEY" hint
 *     instead of mistaking the placeholder copy for real advice.
 *
 * Used by the Equipment and Vendors module pages today; remaining
 * modules wire it in as their backend prompts.py + insights.py
 * pipelines come online.
 *
 * ─────────────────────────────────────────────────────────────────
 * A11y contract (Frontend Polish a11y pass — sketch, not yet wired)
 * ─────────────────────────────────────────────────────────────────
 *
 * Intent: a sighted-keyboard user or a screen-reader user should be
 * able to (a) understand this is a region of AI recommendations,
 * (b) understand each card's severity at a glance, and (c) traverse
 * the cards with arrow keys without having to tab through every
 * inline badge.
 *
 * ARIA tree:
 *
 *   <Card role="region"
 *         aria-labelledby="recs-{slug}-title"
 *         aria-busy={isFetching}>
 *     <CardHeader>
 *       <CardTitle id="recs-{slug}-title">Recommendations</CardTitle>
 *       <span aria-live="polite" class="sr-only">
 *         {isFetching ? "Refreshing recommendations" :
 *          isError    ? "Failed to load recommendations" :
 *          data       ? `${data.recommendations.length} recommendations loaded` :
 *                       "Loading recommendations"}
 *       </span>
 *     </CardHeader>
 *     <CardContent>
 *       <ul role="list" aria-label="Ranked recommendations">
 *         <li role="listitem">
 *           <article tabIndex={0}                           ← focusable card
 *                    aria-labelledby="rec-{idx}-title"
 *                    aria-describedby="rec-{idx}-action">
 *             <Icon aria-hidden="true" />
 *             <p id="rec-{idx}-title">{rec.title}</p>
 *             <Badge aria-label={`Severity: ${rec.severity}`}>
 *               {rec.severity}
 *             </Badge>
 *             <p>{rec.rationale}</p>
 *             <p id="rec-{idx}-action">
 *               <span>Action: </span>{rec.suggested_action}
 *             </p>
 *             {assets && (
 *               <ul role="list"
 *                   aria-label={`${rec.affected_assets.length} affected assets`}>
 *                 {assets.map(a => <li><Badge>{a}</Badge></li>)}
 *               </ul>
 *             )}
 *           </article>
 *         </li>
 *         …
 *       </ul>
 *     </CardContent>
 *   </Card>
 *
 * Keyboard model:
 *
 *   The <article> elements are roving-tabindex: only the focused card
 *   has tabIndex={0}, the rest tabIndex={-1}. Tab/Shift+Tab moves into
 *   and out of the rail (single stop), arrow keys move between cards.
 *
 *     ArrowDown / ArrowRight  → focus next card (no wrap)
 *     ArrowUp   / ArrowLeft   → focus previous card (no wrap)
 *     Home                    → focus first card
 *     End                     → focus last card
 *     Tab                     → leaves the rail entirely (cards have
 *                               no internal interactive children today,
 *                               so we don't need to manage in-card tab
 *                               order).
 *
 *   Implementation note: a single `useRef<HTMLUListElement>(null)` plus
 *   `useState<number>(0)` for activeIndex; on focus event of any
 *   child <article>, sync activeIndex. On keydown, prevent default
 *   for the captured keys and call `.focus()` on the target sibling.
 *   No focus trap — the rail isn't modal.
 *
 *   When the cards eventually become clickable (Phase 6.5 — link to
 *   the affected asset), each card's <article> gets role="link" plus
 *   Enter/Space activation, but the roving-tabindex shape stays.
 *
 * Reduced motion:
 *
 *   The refresh spinner uses `animate-spin`. Wrap with `motion-reduce:
 *   animate-none`. The skeleton's `animate-pulse` gets the same
 *   treatment. Stub banner has no motion to gate.
 *
 * Severity announcement:
 *
 *   `aria-label={`Severity: ${rec.severity}`}` on the badge replaces
 *   the visible token text for screen-reader output, so the SR says
 *   "Severity: critical" rather than "critical" with no context.
 *
 * Backwards-compat:
 *
 *   None of the public props change. EquipmentPage's existing
 *   `<RecommendationsRail moduleSlug="equipment" description="…" />`
 *   call site continues to work without edits.
 */
export interface RecommendationsRailProps {
  /**
   * Slug used to build the endpoint URL — `equipment`, `vendors`, …
   * Matches the FastAPI module mount in `backend/app/main.py`.
   */
  moduleSlug: string;
  /**
   * Optional override for the card title (defaults to "Recommendations").
   */
  title?: string;
  /**
   * Optional descriptive copy under the title.
   */
  description?: string;
}

export function RecommendationsRail({
  moduleSlug,
  title = "Recommendations",
  description = "AI-generated next actions, refreshed every 6 hours.",
}: RecommendationsRailProps) {
  const titleId = React.useId();
  const listId = React.useId();

  const { data, isPending, isError, error, isFetching } = useQuery({
    queryKey: ["recommendations", moduleSlug],
    queryFn: () => fetchRecommendations(moduleSlug),
    staleTime: 5 * 60 * 1000,
    // Don't keep retrying a 404/503 forever — the backend may not
    // have wired this module yet (still on Phase 5). One retry is
    // enough to ride out a transient network blip.
    retry: 1,
  });

  // Single SR-only string updates as state transitions. aria-live="polite"
  // means screen readers wait for a pause before announcing — perfect for
  // the staleTime-driven refetches that happen quietly in the background.
  const statusMessage = isError
    ? "Failed to load recommendations"
    : isPending
      ? "Loading recommendations"
      : isFetching
        ? "Refreshing recommendations"
        : data
          ? `${data.recommendations.length} recommendation${
              data.recommendations.length === 1 ? "" : "s"
            } loaded`
          : "Recommendations idle";

  return (
    <Card
      role="region"
      aria-labelledby={titleId}
      aria-busy={isPending || isFetching}
      className="lg:sticky lg:top-6"
    >
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
            <CardTitle id={titleId}>{title}</CardTitle>
          </div>
          {isFetching && !isPending && (
            <RefreshCcw
              className="h-3.5 w-3.5 animate-spin text-muted-foreground motion-reduce:animate-none"
              aria-hidden="true"
            />
          )}
        </div>
        <CardDescription>{description}</CardDescription>
        <span className="sr-only" aria-live="polite">
          {statusMessage}
        </span>
      </CardHeader>
      <CardContent className="space-y-3">
        {isPending && <RailSkeleton />}
        {isError && (
          <RailError
            message={
              error instanceof Error
                ? error.message
                : "Failed to load recommendations."
            }
          />
        )}
        {data && <RailBody data={data} listId={listId} />}
      </CardContent>
    </Card>
  );
}

function RailBody({ data, listId }: { data: InsightResponse; listId: string }) {
  if (data.recommendations.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center text-xs text-muted-foreground">
        No recommendations yet. Once enough activity is logged, Claude will
        surface ranked next actions here.
      </div>
    );
  }

  return (
    <>
      {data.is_stub && <StubBanner />}
      <RecommendationList recs={data.recommendations} listId={listId} />
      <div className="text-[11px] text-muted-foreground">
        Generated {formatGeneratedAt(data.generated_at)} · {data.model}
      </div>
    </>
  );
}

/**
 * Roving-tabindex list. Single tab-stop into the rail, then arrow keys
 * (and Home/End) navigate between cards. Implementation matches the
 * sketch in the file header — see "Keyboard model" section.
 *
 * Why not a Radix primitive? Radix doesn't ship a generic "roving tab
 * list" — Toolbar is closest but enforces horizontal layout. Hand-roll
 * is ~30 lines and stays internal to this file.
 */
function RecommendationList({
  recs,
  listId,
}: {
  recs: Recommendation[];
  listId: string;
}) {
  const [activeIndex, setActiveIndex] = React.useState(0);
  const itemRefs = React.useRef<(HTMLElement | null)[]>([]);

  const focusItem = (index: number) => {
    setActiveIndex(index);
    itemRefs.current[index]?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLUListElement>) => {
    let next: number | null = null;
    switch (e.key) {
      case "ArrowDown":
      case "ArrowRight":
        next = Math.min(recs.length - 1, activeIndex + 1);
        break;
      case "ArrowUp":
      case "ArrowLeft":
        next = Math.max(0, activeIndex - 1);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = recs.length - 1;
        break;
      default:
        return;
    }
    e.preventDefault();
    if (next !== null && next !== activeIndex) {
      focusItem(next);
    }
  };

  return (
    <ul
      role="list"
      aria-label="Ranked recommendations"
      onKeyDown={onKeyDown}
      className="space-y-3"
    >
      {recs.map((rec, idx) => (
        <li key={`${rec.title}-${idx}`} role="listitem">
          <RecommendationItem
            rec={rec}
            idx={idx}
            listId={listId}
            isActive={activeIndex === idx}
            onFocus={() => setActiveIndex(idx)}
            registerRef={(el) => {
              itemRefs.current[idx] = el;
            }}
          />
        </li>
      ))}
    </ul>
  );
}

function RecommendationItem({
  rec,
  idx,
  listId,
  isActive,
  onFocus,
  registerRef,
}: {
  rec: Recommendation;
  idx: number;
  listId: string;
  isActive: boolean;
  onFocus: () => void;
  registerRef: (el: HTMLElement | null) => void;
}) {
  const tone = severityTone(rec.severity);
  const Icon = tone.Icon;
  const titleId = `${listId}-rec-${idx}-title`;
  const actionId = `${listId}-rec-${idx}-action`;

  return (
    <article
      ref={registerRef}
      tabIndex={isActive ? 0 : -1}
      onFocus={onFocus}
      aria-labelledby={titleId}
      aria-describedby={actionId}
      className={cn(
        "rounded-lg border p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        tone.borderClass,
        tone.bgClass,
      )}
    >
      <div className="flex items-start gap-2">
        <Icon
          className={cn("mt-0.5 h-4 w-4 shrink-0", tone.textClass)}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <p id={titleId} className="text-sm font-semibold leading-tight">
              {rec.title}
            </p>
            <Badge
              variant="outline"
              aria-label={`Severity: ${rec.severity}`}
              className={cn("text-[10px]", tone.textClass)}
            >
              {rec.severity}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">{rec.rationale}</p>
          <p id={actionId} className="text-xs">
            <span className="font-medium">Action: </span>
            {rec.suggested_action}
          </p>
          {rec.affected_assets.length > 0 && (
            <div
              className="flex flex-wrap gap-1 pt-1"
              role="list"
              aria-label={`${rec.affected_assets.length} affected ${
                rec.affected_assets.length === 1 ? "asset" : "assets"
              }`}
            >
              {rec.affected_assets.slice(0, 6).map((a) => (
                <Badge
                  key={a}
                  variant="secondary"
                  role="listitem"
                  className="text-[10px]"
                >
                  {a}
                </Badge>
              ))}
              {rec.affected_assets.length > 6 && (
                <span className="text-[10px] text-muted-foreground">
                  +{rec.affected_assets.length - 6} more
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function StubBanner() {
  return (
    <div className="rounded-md border border-dashed border-amber-300 bg-amber-50 p-2.5 text-[11px] text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/5 dark:text-amber-300">
      Stub mode — set <code className="font-mono">ANTHROPIC_API_KEY</code> on
      the backend to enable live recommendations.
    </div>
  );
}

function RailSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="h-24 animate-pulse rounded-md bg-muted motion-reduce:animate-none"
          aria-hidden
        />
      ))}
    </div>
  );
}

function RailError({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-xs text-critical">
      Couldn't load recommendations: {message}
    </div>
  );
}

function severityTone(severity: Severity) {
  switch (severity) {
    case "critical":
      return {
        Icon: AlertOctagon,
        textClass: "text-critical",
        borderClass: "border-critical/30",
        bgClass: "bg-critical/5",
      };
    case "warning":
      return {
        Icon: AlertTriangle,
        textClass: "text-amber-600 dark:text-amber-400",
        borderClass: "border-amber-300/60 dark:border-amber-500/40",
        bgClass: "bg-amber-50/60 dark:bg-amber-500/5",
      };
    case "info":
    default:
      return {
        Icon: Info,
        textClass: "text-primary",
        borderClass: "border-border",
        bgClass: "bg-muted/20",
      };
  }
}

function formatGeneratedAt(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
