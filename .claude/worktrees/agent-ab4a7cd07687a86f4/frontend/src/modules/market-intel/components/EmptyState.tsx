import { Inbox } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Shared empty / error / "not enough data yet" placeholder for the
 * Market Intel tabs. Three flavors driven by `tone`:
 *
 *   default — no data yet, neutral copy.
 *   info    — pipeline-paused / dark-accumulation messaging.
 *   error   — fetch failed, with the canonical retry hint.
 *
 * Lives outside the tab components so all three tabs render an
 * identical empty/error block, no per-tab divergence.
 */

export type EmptyStateTone = "default" | "info" | "error";

export interface EmptyStateProps {
  /** Short headline. Sentence case. */
  title: string;
  /** Optional secondary copy. */
  description?: string;
  tone?: EmptyStateTone;
  /** Right-aligned action slot (e.g. a Retry button). */
  action?: React.ReactNode;
  /** Override the leading icon. Defaults to a tone-appropriate lucide. */
  icon?: React.ReactNode;
  /** Test id passthrough so tests can target tone variants. */
  "data-testid"?: string;
}

const toneStyles: Record<
  EmptyStateTone,
  { border: string; bg: string; text: string }
> = {
  default: {
    border: "border-border",
    bg: "bg-muted/40",
    text: "text-muted-foreground",
  },
  info: {
    border: "border-info/30",
    bg: "bg-info/5",
    text: "text-info",
  },
  error: {
    border: "border-critical/30",
    bg: "bg-critical/5",
    text: "text-critical",
  },
};

export function EmptyState({
  title,
  description,
  tone = "default",
  action,
  icon,
  "data-testid": testId,
}: EmptyStateProps) {
  const styles = toneStyles[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      aria-live={tone === "error" ? "assertive" : "polite"}
      data-testid={testId}
      className={cn(
        "flex flex-col items-start gap-3 rounded-lg border border-dashed p-6 sm:flex-row sm:items-center sm:justify-between",
        styles.border,
        styles.bg,
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-card",
            styles.text,
          )}
          aria-hidden
        >
          {icon ?? <Inbox className="h-4 w-4" />}
        </div>
        <div className="space-y-1">
          <p className={cn("text-sm font-medium", styles.text)}>{title}</p>
          {description && (
            <p className="text-xs text-muted-foreground">{description}</p>
          )}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
