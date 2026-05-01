import { ArrowRight } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { Donut } from "./Donut";
import { agentAlerts, donutSlices, type Severity } from "./dashboard-data";

const severityClass: Record<Severity, string> = {
  crit: "bg-critical",
  warn: "bg-warning",
  ok: "bg-primary",
};

export function AgentAlertsCard() {
  const total = donutSlices.reduce((s, d) => s + d.count, 0);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Agent Alerts</CardTitle>
          <CardDescription>Today · severity-ranked</CardDescription>
        </div>
        <a
          href="#"
          className="inline-flex items-center gap-1 text-xs font-medium text-info hover:underline"
        >
          See All <ArrowRight className="h-3 w-3" />
        </a>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-[220px_1fr]">
          {/* Donut + legend */}
          <div className="flex flex-col items-center gap-3">
            <Donut data={donutSlices} total={total} />
            <div className="flex w-full flex-col gap-1.5">
              {donutSlices.map((d) => (
                <div
                  key={d.label}
                  className="flex items-center gap-2 text-xs"
                >
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ background: d.color }}
                  />
                  <span className="flex-1 text-foreground">{d.label}</span>
                  <span className="font-mono font-semibold text-foreground">
                    {d.count}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Feed */}
          <div className="flex flex-col gap-2">
            {agentAlerts.map((a, i) => (
              <div
                key={i}
                className="flex gap-2.5 rounded-lg border border-muted bg-muted/30 p-3"
              >
                <div
                  className={cn(
                    "w-[3px] shrink-0 rounded-sm",
                    severityClass[a.severity],
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-semibold">{a.asset}</span>
                    <span className="whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                      {a.time}
                    </span>
                  </div>
                  <div className="mt-0.5 font-mono text-[11px] text-info">
                    {a.agent}
                  </div>
                  <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {a.msg}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
