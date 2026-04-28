import { AlertTriangle, Check, Clock, Compass, Minus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { fleetInsights, type Tone } from "./dashboard-data";

const toneStyles: Record<
  Tone,
  { iconBg: string; iconFg: string; Icon: typeof Check }
> = {
  good: { iconBg: "bg-primary/10", iconFg: "text-primary", Icon: Check },
  bad: { iconBg: "bg-critical/10", iconFg: "text-critical", Icon: AlertTriangle },
  warn: { iconBg: "bg-warning/10", iconFg: "text-warning", Icon: Clock },
  info: { iconBg: "bg-info/10", iconFg: "text-info", Icon: Compass },
  neutral: {
    iconBg: "bg-muted",
    iconFg: "text-muted-foreground",
    Icon: Minus,
  },
};

/**
 * Fleet Insights — 7-tile grid of Vista emem / emwo-derived counts.
 * One tile is highlighted (Issues Reported) to match the mockup's
 * dark card treatment.
 */
export function FleetInsightsCard() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Fleet Insights</CardTitle>
          <CardDescription>Today · pulled from Vista emem / emwo</CardDescription>
        </div>
        <Badge variant="mono">Today ▾</Badge>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {fleetInsights.map((t) => {
            const { iconBg, iconFg, Icon } = toneStyles[t.tone];
            const highlighted = !!t.highlight;
            return (
              <div
                key={t.label}
                className={cn(
                  "flex flex-col gap-1 rounded-lg border border-border bg-muted/40 px-3 py-3.5",
                  highlighted &&
                    "border-accent bg-accent text-accent-foreground",
                )}
              >
                <div
                  className={cn(
                    "mb-1 flex h-7 w-7 items-center justify-center rounded-md",
                    highlighted ? "bg-white/10" : iconBg,
                  )}
                >
                  <Icon
                    className={cn(
                      "h-3.5 w-3.5",
                      highlighted ? "text-accent-foreground" : iconFg,
                    )}
                  />
                </div>
                <div className="font-mono text-xl font-semibold">{t.count}</div>
                <div
                  className={cn(
                    "text-[11px]",
                    highlighted
                      ? "text-accent-foreground/80"
                      : "text-muted-foreground",
                  )}
                >
                  {t.label}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
