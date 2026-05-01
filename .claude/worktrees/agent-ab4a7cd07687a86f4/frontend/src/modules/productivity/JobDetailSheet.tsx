import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

import {
  fetchJobProductivityDetail,
  type JobHoursRollup,
  type JobPhaseRow,
  type PhasePerf,
  type PhaseStatus,
} from "./productivity-api";

const keys = {
  job: (jobId: string) => ["productivity", "job", jobId] as const,
};

const phaseStatusClass: Record<PhaseStatus, string> = {
  complete: "border-primary/40 bg-primary/10 text-primary",
  on_track: "border-info/40 bg-info/10 text-info",
  behind_pace: "border-warning/40 bg-warning/10 text-warning",
  over_budget: "border-critical/40 bg-critical/10 text-critical",
  unknown: "border-border bg-muted text-muted-foreground",
};

function phaseStatusLabel(s: PhaseStatus): string {
  const labels: Record<PhaseStatus, string> = {
    complete: "Complete",
    on_track: "On track",
    behind_pace: "Behind pace",
    over_budget: "Over budget",
    unknown: "Unknown",
  };
  return labels[s];
}

function formatHours(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function formatPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(0)}%`;
}

function PerfCell({ perf }: { perf: PhasePerf | null }) {
  if (!perf) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <div className="space-y-0.5 text-[11px] leading-tight">
      <div className="font-mono tabular-nums">
        act {formatHours(perf.actual_hours)} / est {formatHours(perf.est_hours)}
      </div>
      <div className="text-muted-foreground">
        used {formatPct(perf.percent_used)} · done {formatPct(perf.percent_complete)}
      </div>
      <Badge
        variant="outline"
        className={cn(
          "border px-1.5 py-0 text-[10px] font-medium",
          phaseStatusClass[perf.status],
        )}
      >
        {phaseStatusLabel(perf.status)}
      </Badge>
    </div>
  );
}

function PhaseTable({ phases }: { phases: JobPhaseRow[] }) {
  if (phases.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No phase rows for this job.</p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="min-w-[140px]">Phase</TableHead>
            <TableHead>Worst</TableHead>
            <TableHead className="min-w-[160px]">Labor</TableHead>
            <TableHead className="min-w-[160px]">Equipment</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {phases.map((row) => (
            <TableRow key={row.phase_id}>
              <TableCell className="align-top">
                <div className="font-medium leading-snug">{row.phase}</div>
                <div className="text-[10px] text-muted-foreground">
                  {row.phase_id}
                </div>
              </TableCell>
              <TableCell className="align-top">
                <Badge
                  variant="outline"
                  className={cn(
                    "border text-[10px]",
                    phaseStatusClass[row.worst_status],
                  )}
                >
                  {phaseStatusLabel(row.worst_status)}
                </Badge>
              </TableCell>
              <TableCell className="align-top">
                <PerfCell perf={row.labor} />
              </TableCell>
              <TableCell className="align-top">
                <PerfCell perf={row.equipment} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function JobDetailSheet({
  jobId,
  open,
  onOpenChange,
}: {
  jobId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: jobId ? keys.job(jobId) : ["productivity", "job", "none"],
    queryFn: () => fetchJobProductivityDetail(jobId!),
    enabled: open && Boolean(jobId),
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full max-w-full flex-col gap-0 overflow-y-auto sm:max-w-3xl"
      >
        <SheetHeader className="border-b border-border pb-4 text-left">
          <SheetTitle className="pr-8">
            {isLoading ? "Loading…" : data?.job ?? "Job productivity"}
          </SheetTitle>
          <SheetDescription className="line-clamp-3">
            Phase-level labor and equipment hours from productivity marts.
            {data?.project_end_date && (
              <>
                {" "}
                Project end{" "}
                {new Date(data.project_end_date).toLocaleDateString()}.
              </>
            )}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-4 p-4">
          {isError && (
            <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
              Could not load job detail. The job may be missing from the mart.
            </div>
          )}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Fetching phases…
            </div>
          )}
          {data && (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <RollupCard title="Labor rollup" rollup={data.labor_rollup} />
                <RollupCard
                  title="Equipment rollup"
                  rollup={data.equipment_rollup}
                />
              </div>
              <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                <Badge variant="mono">{data.phases_complete} complete</Badge>
                <Badge variant="mono">{data.phases_on_track} on track</Badge>
                <Badge variant="mono">{data.phases_behind_pace} behind</Badge>
                <Badge variant="mono">{data.phases_over_budget} over budget</Badge>
                <Badge variant="mono">{data.phases_unknown} unknown</Badge>
              </div>
              <PhaseTable phases={data.phases} />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function RollupCard({
  title,
  rollup,
}: {
  title: string;
  rollup: JobHoursRollup | null;
}) {
  if (!rollup) {
    return (
      <div className="rounded-lg border border-border bg-muted/20 p-3 text-sm text-muted-foreground">
        {title}: no data
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <h4 className="mb-2 text-xs font-semibold text-muted-foreground">
        {title}
      </h4>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-muted-foreground">Actual</div>
          <div className="font-mono font-semibold tabular-nums">
            {formatHours(rollup.actual_hours)}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Estimated</div>
          <div className="font-mono font-semibold tabular-nums">
            {formatHours(rollup.est_hours)}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Variance (est − act)</div>
          <div className="font-mono font-semibold tabular-nums">
            {formatHours(rollup.variance_hours)}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">% used</div>
          <div className="font-mono font-semibold tabular-nums">
            {rollup.percent_used == null ? "—" : formatPct(rollup.percent_used)}
          </div>
        </div>
      </div>
    </div>
  );
}
