import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  fetchProductivityAttention,
  type AttentionRow,
  type ResourceKind,
} from "./productivity-api";

const keys = {
  attention: (p: {
    resource_kind?: ResourceKind;
    top_n: number;
  }) => ["productivity", "attention", p] as const,
};

const resourceLabel: Record<ResourceKind, string> = {
  labor: "Labor",
  equipment: "Equipment",
};

function SelectResource({
  value,
  onChange,
}: {
  value: ResourceKind | "all";
  onChange: (v: ResourceKind | "all") => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as ResourceKind | "all")}
      className="h-9 rounded-md border border-input bg-card px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <option value="all">All resources</option>
      <option value="labor">{resourceLabel.labor}</option>
      <option value="equipment">{resourceLabel.equipment}</option>
    </select>
  );
}

function phaseStatusLabel(s: AttentionRow["status"]): string {
  const m: Record<AttentionRow["status"], string> = {
    over_budget: "Over budget",
    behind_pace: "Behind pace",
    on_track: "On track",
    complete: "Complete",
    unknown: "Unknown",
  };
  return m[s];
}

function phaseStatusClass(s: AttentionRow["status"]): string {
  const m: Record<AttentionRow["status"], string> = {
    complete: "border-primary/40 bg-primary/10 text-primary",
    on_track: "border-info/40 bg-info/10 text-info",
    behind_pace: "border-warning/40 bg-warning/10 text-warning",
    over_budget: "border-critical/40 bg-critical/10 text-critical",
    unknown: "border-border bg-muted text-muted-foreground",
  };
  return m[s];
}

export function AttentionTab({
  onJobSelect,
}: {
  onJobSelect: (jobId: string) => void;
}) {
  const [resource, setResource] = useState<ResourceKind | "all">("all");
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([
    { id: "severity", desc: true },
  ]);

  const queryParams = useMemo(
    () => ({
      top_n: 500 as const,
      ...(resource !== "all" ? { resource_kind: resource } : {}),
    }),
    [resource],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.attention(queryParams),
    queryFn: () => fetchProductivityAttention(queryParams),
    placeholderData: keepPreviousData,
  });

  const filteredItems = useMemo(() => {
    const items = data?.items ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (r) =>
        r.job.toLowerCase().includes(q) ||
        r.phase.toLowerCase().includes(q) ||
        r.job_id.toLowerCase().includes(q),
    );
  }, [data?.items, search]);

  const columns = useMemo<ColumnDef<AttentionRow>[]>(
    () => [
      {
        accessorKey: "job",
        header: "Job",
        cell: ({ row }) => (
          <div className="max-w-[200px]">
            <div className="font-medium leading-snug">{row.original.job}</div>
            <div className="text-[10px] text-muted-foreground">
              {row.original.job_id}
            </div>
          </div>
        ),
      },
      {
        accessorKey: "phase",
        header: "Phase",
        cell: ({ row }) => (
          <div className="max-w-[180px]">
            <div className="text-sm leading-snug">{row.original.phase}</div>
          </div>
        ),
      },
      {
        accessorKey: "resource_kind",
        header: "Resource",
        cell: ({ row }) => (
          <Badge variant="secondary" className="text-[10px]">
            {resourceLabel[row.original.resource_kind]}
          </Badge>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => (
          <Badge
            variant="outline"
            className={cn(
              "border text-[10px] font-medium",
              phaseStatusClass(row.original.status),
            )}
          >
            {phaseStatusLabel(row.original.status)}
          </Badge>
        ),
      },
      {
        accessorKey: "severity",
        header: "Severity",
        cell: ({ row }) => (
          <span className="font-mono text-sm tabular-nums">
            {row.original.severity.toLocaleString(undefined, {
              maximumFractionDigits: 1,
            })}
          </span>
        ),
      },
      {
        accessorKey: "actual_hours",
        header: "Actual",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-xs">
            {row.original.actual_hours == null
              ? "—"
              : row.original.actual_hours.toLocaleString(undefined, {
                  maximumFractionDigits: 1,
                })}
          </span>
        ),
      },
      {
        accessorKey: "est_hours",
        header: "Est.",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-xs">
            {row.original.est_hours == null
              ? "—"
              : row.original.est_hours.toLocaleString(undefined, {
                  maximumFractionDigits: 1,
                })}
          </span>
        ),
      },
      {
        accessorKey: "percent_complete",
        header: "% done",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-xs">
            {row.original.percent_complete == null
              ? "—"
              : `${(row.original.percent_complete * 100).toFixed(0)}%`}
          </span>
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: filteredItems,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 25 } },
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <SelectResource value={resource} onChange={setResource} />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter job or phase…"
          className="w-full sm:w-64"
        />
        {data && (
          <Badge variant="mono" className="w-fit">
            {filteredItems.length} shown · {data.total} from API · as of{" "}
            {new Date(data.as_of).toLocaleString()}
          </Badge>
        )}
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && (
        <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
          Could not load attention list.
        </div>
      )}

      <div className="rounded-lg border border-border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const sort = header.column.getIsSorted();
                  return (
                    <TableHead key={header.id}>
                      {canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 hover:text-foreground"
                        >
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                          {sort === "asc" ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : sort === "desc" ? (
                            <ArrowDown className="h-3 w-3" />
                          ) : (
                            <ArrowUpDown className="h-3 w-3 opacity-40" />
                          )}
                        </button>
                      ) : (
                        flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="text-center text-sm text-muted-foreground"
                >
                  Loading…
                </TableCell>
              </TableRow>
            ) : table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="text-center text-sm text-muted-foreground"
                >
                  No attention rows match the current filters.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer hover:bg-muted/40"
                  onClick={() => onJobSelect(row.original.job_id)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Page {table.getState().pagination.pageIndex + 1} of{" "}
          {table.getPageCount() || 1}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={!table.getCanPreviousPage() || isLoading}
            onClick={() => table.previousPage()}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Prev
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!table.getCanNextPage() || isLoading}
            onClick={() => table.nextPage()}
          >
            Next
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Click a row to open job detail (phase grid). Same job may appear
        multiple times when both labor and equipment need attention.
      </p>
    </div>
  );
}
