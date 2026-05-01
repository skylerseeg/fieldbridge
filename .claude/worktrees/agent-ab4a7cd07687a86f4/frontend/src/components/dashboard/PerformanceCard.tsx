import { ArrowRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { chartData, perfMetrics } from "./dashboard-data";

/**
 * Performance card — metric strip on the left, 6-bar monthly savings
 * chart on the right. Chart is hand-rolled SVG-less (plain divs) to
 * avoid dragging in Recharts for a single sparkline.
 */
export function PerformanceCard() {
  const maxVal = Math.max(...chartData.map((d) => d.v));

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Performance</CardTitle>
          <CardDescription>Last 6 months · all agents</CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="mono">Nov — Apr</Badge>
          <Badge variant="mono">Savings $k/mo</Badge>
          <a
            href="#"
            className="inline-flex items-center gap-1 text-xs font-medium text-info hover:underline"
          >
            See More <ArrowRight className="h-3 w-3" />
          </a>
        </div>
      </CardHeader>

      <CardContent>
        {/*
          Two-column layout at lg+: metric strip on the left, bar chart
          on the right. The chart's y-axis labels sit at the LEFT edge
          of the chart column (in its pl-12 padding zone), and the
          metric strip's values are right-aligned at its RIGHT edge —
          so the gap between columns is what gives the eye separation
          between the two stacks of numbers. lg:gap-12 is deliberate
          breathing room; tightening it back to gap-6 reintroduces the
          visual collision the user flagged.
        */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1.1fr] lg:gap-12">
          {/* Metric strip */}
          <div className="flex flex-col">
            {perfMetrics.map((m) => (
              <div
                key={m.label}
                className="border-b border-muted py-3 last:border-b-0"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[13px] text-muted-foreground">
                    {m.label}
                  </span>
                  <span
                    className={cn(
                      "font-mono text-[15px] font-semibold",
                      m.valueClass,
                    )}
                  >
                    {m.value}
                  </span>
                </div>
                <div className="mt-2 h-[5px] overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full", m.barClass)}
                    style={{ width: `${m.barPct}%` }}
                  />
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  {m.sub}
                </div>
              </div>
            ))}
          </div>

          {/* Bar chart */}
          <div className="relative h-56 pl-12">
            {/* Grid lines + y-axis labels — labels sit in the pl-12 zone
                via -left-10 so they stay clear of the metric strip's
                right-aligned values across breakpoints. */}
            <div className="pointer-events-none absolute inset-0 pl-12">
              {[2000, 1500, 1000, 500, 0].map((v, i) => (
                <div
                  key={v}
                  className="absolute left-0 right-0 flex items-center"
                  style={{ top: `${i * 25}%` }}
                >
                  <span className="absolute -left-10 -top-1.5 w-8 text-right font-mono text-[10px] text-muted-foreground">
                    {v === 0 ? "0" : `$${v / 10}k`}
                  </span>
                  <div className="h-px w-full border-t border-dashed border-border" />
                </div>
              ))}
            </div>
            {/* Bars */}
            <div className="relative z-10 flex h-full items-end justify-around gap-1.5">
              {chartData.map((d) => {
                const pct = (d.v / maxVal) * 100;
                return (
                  <div
                    key={d.m}
                    className="relative flex flex-1 flex-col items-center"
                  >
                    {d.highlight && (
                      <div className="absolute -top-7 rounded bg-accent px-2 py-0.5 font-mono text-[11px] font-semibold text-accent-foreground">
                        ${d.v}k
                      </div>
                    )}
                    <div
                      className={cn(
                        "w-[70%] max-w-[40px] rounded-t transition-[height] duration-200",
                        d.highlight ? "bg-accent" : "bg-info/20",
                      )}
                      style={{ height: `${pct}%` }}
                    />
                    <div className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                      {d.m}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
