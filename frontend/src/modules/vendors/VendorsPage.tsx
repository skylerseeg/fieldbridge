import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Briefcase,
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleSlash,
  HardHat,
  HelpCircle,
  Layers,
  Pencil,
  Truck,
  UserCheck,
  Wrench,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RecommendationsRail as SharedRecommendationsRail } from "@/components/RecommendationsRail";
import { cn } from "@/lib/utils";

import {
  enrichVendor,
  fetchVendorInsights,
  fetchVendorList,
  fetchVendorSummary,
  type ContactStatus,
  type FirmType,
  type ListParams,
  type SortDir,
  type SortField,
  type VendorListRow,
  type CodingStatus,
  type VendorEnrichmentPayload,
} from "./vendors-api";

/**
 * Vendors module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (data-health) ─────────────────────┐ ┌── Recommendations
 *   │  Total · Complete · Uncoded · Division coverage  │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: firm-type bar + contact/coding mix    │ │
 *   │  List:     paginated TanStack table              │ │
 *   │  Insights: top codes/divisions + recruitment gaps│ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * The vendors mart carries directory data only — no transaction dollars,
 * no activity. So the dashboard surfaces *data-health* (contact tiers,
 * CSI coverage) rather than P&L. Severity follows the same token map
 * used elsewhere in the shell — primary = healthy, info = neutral,
 * warning = gap, critical = missing.
 *
 * Mutations: vendors endpoints are read-only. The Phase 5 brief calls
 * for "TanStack Query mutations with optimistic updates where safe" but
 * there's no write surface yet. The query-key factory below keeps things
 * ready for Phase 6 (e.g. inline contact edits) — invalidate on
 * `keys.list(...)` after a useMutation success and the table snaps back.
 */

// ── Severity / token maps (no new colors) ────────────────────────────

type Tone = "good" | "info" | "warn" | "crit" | "neutral";

const toneStyles: Record<
  Tone,
  { border: string; bg: string; text: string; fill: string }
> = {
  good: {
    border: "border-l-primary",
    bg: "bg-primary/10",
    text: "text-primary",
    fill: "hsl(var(--primary))",
  },
  info: {
    border: "border-l-info",
    bg: "bg-info/10",
    text: "text-info",
    fill: "hsl(var(--info))",
  },
  warn: {
    border: "border-l-warning",
    bg: "bg-warning/10",
    text: "text-warning",
    fill: "hsl(var(--warning))",
  },
  crit: {
    border: "border-l-critical",
    bg: "bg-critical/10",
    text: "text-critical",
    fill: "hsl(var(--critical))",
  },
  neutral: {
    border: "border-l-accent",
    bg: "bg-muted",
    text: "text-muted-foreground",
    fill: "hsl(var(--accent))",
  },
};

const firmStyles: Record<
  FirmType,
  { tone: Tone; label: string; Icon: typeof Truck }
> = {
  supplier: { tone: "info", label: "Supplier", Icon: Truck },
  contractor: { tone: "good", label: "Contractor", Icon: HardHat },
  service: { tone: "warn", label: "Service", Icon: Wrench },
  internal: { tone: "neutral", label: "Internal", Icon: Briefcase },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const contactStyles: Record<
  ContactStatus,
  { tone: Tone; label: string }
> = {
  complete: { tone: "good", label: "Complete" },
  partial: { tone: "info", label: "Partial" },
  minimal: { tone: "warn", label: "Minimal" },
  empty: { tone: "crit", label: "Empty" },
};

// NOTE: Coding status doesn't get a chip column because the `code_count`
// cell already carries the signal (0 lights up a warn-colored icon).
// The select-option labels for the Coding filter are inlined inline below.

const FIRM_ORDER: FirmType[] = [
  "supplier",
  "contractor",
  "service",
  "internal",
  "unknown",
];

const CONTACT_ORDER: ContactStatus[] = [
  "complete",
  "partial",
  "minimal",
  "empty",
];

// Query key factory — invalidations stay consistent across hooks /
// future write mutations.
const keys = {
  all: ["vendors"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number, thinMax: number) =>
    [...keys.all, "insights", topN, thinMax] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function VendorsPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Vendors</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Directory health across every supplier, contractor, and service
          partner — contact completeness, CSI coverage, firm mix.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="space-y-6 lg:col-span-3">
          <KpiTiles />
          <ContentTabs />
        </div>
        <aside className="lg:col-span-1">
          <RecommendationsRail />
        </aside>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// KPI tiles
// ──────────────────────────────────────────────────────────────────────

function KpiTiles() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: fetchVendorSummary,
  });

  // Four directory-health tiles. We grade each based on the same
  // "% of total" rule of thumb — high coverage of contact/coding is
  // good; presence of uncoded rows is a warn/crit signal scaling with
  // share. The thresholds (75/40) match the contact-status tiers in the
  // backend service.
  const tiles = useMemo(() => {
    if (!data) return [];
    const total = data.total_vendors || 0;
    const completePct = total > 0 ? data.complete_contact / total : 0;
    const uncodedPct = total > 0 ? data.uncoded_vendors / total : 0;

    const completeTone: Tone =
      completePct >= 0.75 ? "good" : completePct >= 0.4 ? "info" : "warn";
    const uncodedTone: Tone =
      uncodedPct === 0 ? "good" : uncodedPct < 0.25 ? "warn" : "crit";

    return [
      {
        key: "total",
        tone: "info" as Tone,
        Icon: Building2,
        count: total,
        label: "Total vendors",
        sub: `${data.coded_vendors} coded · ${data.uncoded_vendors} uncoded`,
      },
      {
        key: "complete",
        tone: completeTone,
        Icon: UserCheck,
        count: data.complete_contact,
        label: "Complete contact",
        sub: `${formatPercent(completePct)} of directory`,
      },
      {
        key: "uncoded",
        tone: uncodedTone,
        Icon: CircleSlash,
        count: data.uncoded_vendors,
        label: "Uncoded vendors",
        sub: `${formatPercent(uncodedPct)} missing CSI codes`,
      },
      {
        key: "divisions",
        tone: "neutral" as Tone,
        Icon: Layers,
        count: data.distinct_divisions,
        label: "Division coverage",
        sub: `${data.distinct_codes} distinct CSI codes`,
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Directory health</CardTitle>
          <CardDescription>
            Static snapshot · pulled from the vendor master mart
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">{data.suppliers} suppliers</Badge>
              <Badge variant="mono">{data.contractors} contractors</Badge>
              <Badge variant="mono">{data.services} services</Badge>
            </>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isError && <ErrorBlock message="Couldn't load summary." />}
        {isLoading && <SkeletonGrid count={4} />}
        {data && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {tiles.map((t) => {
              const s = toneStyles[t.tone];
              return (
                <div
                  key={t.key}
                  className={cn(
                    "flex flex-col gap-1.5 rounded-lg border border-border border-l-4 bg-card px-4 py-3.5",
                    s.border,
                  )}
                >
                  <div
                    className={cn(
                      "flex h-7 w-7 items-center justify-center rounded-md",
                      s.bg,
                    )}
                  >
                    <t.Icon className={cn("h-3.5 w-3.5", s.text)} />
                  </div>
                  <div className="font-mono text-2xl font-semibold">
                    {t.count.toLocaleString()}
                  </div>
                  <div className="text-xs font-medium">{t.label}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {t.sub}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tabs
// ──────────────────────────────────────────────────────────────────────

function ContentTabs() {
  return (
    <Card>
      <Tabs defaultValue="overview" className="w-full">
        <CardHeader className="space-y-3">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="list">List</TabsTrigger>
            <TabsTrigger value="insights">Insights</TabsTrigger>
          </TabsList>
        </CardHeader>
        <CardContent>
          <TabsContent value="overview" className="mt-0">
            <OverviewTab />
          </TabsContent>
          <TabsContent value="list" className="mt-0">
            <ListTab />
          </TabsContent>
          <TabsContent value="insights" className="mt-0">
            <InsightsTab />
          </TabsContent>
        </CardContent>
      </Tabs>
    </Card>
  );
}

// ── Overview ─────────────────────────────────────────────────────────

function OverviewTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: fetchVendorSummary,
  });

  if (isError) return <ErrorBlock message="Couldn't load overview." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const firmChart = FIRM_ORDER.map((ft) => ({
    firm: ft,
    count:
      ft === "supplier"
        ? data.suppliers
        : ft === "contractor"
          ? data.contractors
          : ft === "service"
            ? data.services
            : ft === "internal"
              ? data.internal
              : data.unknown_firm_type,
  }));

  const total = data.total_vendors || 0;

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Firm-type mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Vendor count by normalized firm type.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={firmChart}
              margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="firm"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(f: FirmType) => firmStyles[f].label}
                stroke="hsl(var(--border))"
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--border))"
              />
              <RechartsTooltip
                cursor={{ fill: "hsl(var(--muted))" }}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelFormatter={(f: FirmType) => firmStyles[f].label}
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {firmChart.map((d) => (
                  <Cell
                    key={d.firm}
                    fill={toneStyles[firmStyles[d.firm].tone].fill}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Reachability</h3>
        <SummaryRow
          label="With name"
          value={data.with_name.toLocaleString()}
          sub={formatPercent(safeShare(data.with_name, total))}
        />
        <SummaryRow
          label="With contact"
          value={data.with_contact.toLocaleString()}
          sub={formatPercent(safeShare(data.with_contact, total))}
        />
        <SummaryRow
          label="With email"
          value={data.with_email.toLocaleString()}
          sub={formatPercent(safeShare(data.with_email, total))}
        />
        <SummaryRow
          label="With phone"
          value={data.with_phone.toLocaleString()}
          sub={formatPercent(safeShare(data.with_phone, total))}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Coding</h3>
        <SummaryRow
          label="Coded"
          value={data.coded_vendors.toLocaleString()}
          sub={formatPercent(safeShare(data.coded_vendors, total))}
        />
        <SummaryRow
          label="Uncoded"
          value={data.uncoded_vendors.toLocaleString()}
          sub={formatPercent(safeShare(data.uncoded_vendors, total))}
        />
      </div>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-base font-semibold tabular-nums">
        {value}
        {sub && (
          <span className="ml-1.5 text-[11px] font-normal text-muted-foreground">
            {sub}
          </span>
        )}
      </span>
    </div>
  );
}

// ── List ─────────────────────────────────────────────────────────────

function ListTab() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [firmType, setFirmType] = useState<FirmType | "all">("all");
  const [contactStatus, setContactStatus] = useState<ContactStatus | "all">(
    "all",
  );
  const [codingStatus, setCodingStatus] = useState<CodingStatus | "all">("all");
  const [division, setDivision] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "name", desc: false },
  ]);
  const [selectedVendor, setSelectedVendor] = useState<VendorListRow | null>(
    null,
  );

  const sortBy = (sorting[0]?.id ?? "name") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(firmType !== "all" ? { firm_type: firmType } : {}),
      ...(contactStatus !== "all" ? { contact_status: contactStatus } : {}),
      ...(codingStatus !== "all" ? { coding_status: codingStatus } : {}),
      ...(division.trim() ? { division: division.trim() } : {}),
    }),
    [
      page,
      pageSize,
      sortBy,
      sortDir,
      search,
      firmType,
      contactStatus,
      codingStatus,
      division,
    ],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchVendorList(params),
    placeholderData: keepPreviousData,
  });

  const enrichmentMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: VendorEnrichmentPayload;
    }) => enrichVendor(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.all });
      queryClient.invalidateQueries({ queryKey: ["recommendations", "vendors"] });
      setSelectedVendor(null);
    },
  });

  const columns = useMemo<ColumnDef<VendorListRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Vendor",
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium">
              {row.original.name ?? (
                <span className="italic text-muted-foreground">
                  (unnamed)
                </span>
              )}
            </span>
            {row.original.contact && (
              <span className="text-[11px] text-muted-foreground">
                {row.original.contact}
                {row.original.title && ` · ${row.original.title}`}
              </span>
            )}
          </div>
        ),
      },
      {
        accessorKey: "firm_type",
        header: "Firm",
        cell: ({ row }) => {
          const s = firmStyles[row.original.firm_type];
          const ts = toneStyles[s.tone];
          return (
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <s.Icon className="h-3 w-3" />
              {s.label}
            </span>
          );
        },
      },
      {
        id: "contact_status",
        header: "Contact",
        enableSorting: false,
        cell: ({ row }) => {
          const cs = contactStyles[row.original.contact_status];
          const ts = toneStyles[cs.tone];
          return (
            <span
              className={cn(
                "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              {cs.label}
            </span>
          );
        },
      },
      {
        accessorKey: "code_count",
        header: "Codes",
        cell: ({ row }) => {
          const n = row.original.code_count;
          return (
            <span className="font-mono tabular-nums">
              {n}
              {n === 0 && (
                <AlertTriangle className="ml-1 inline h-3 w-3 text-warning" />
              )}
            </span>
          );
        },
      },
      {
        accessorKey: "primary_division",
        header: "Division",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.primary_division ?? (
              <span className="text-muted-foreground">—</span>
            )}
          </span>
        ),
      },
      {
        id: "email_phone",
        header: "Email / Phone",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-col text-[11px] text-muted-foreground">
            <span className="truncate">{row.original.email ?? "—"}</span>
            <span>{row.original.phone ?? "—"}</span>
          </div>
        ),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <Button
            type="button"
            variant={row.original.enriched ? "secondary" : "outline"}
            size="sm"
            onClick={() => setSelectedVendor(row.original)}
          >
            <Pencil className="mr-1.5 h-3.5 w-3.5" />
            {row.original.enriched ? "Enriched" : "Enrich"}
          </Button>
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    onSortingChange: (updater) => {
      setSorting(updater);
      setPage(1);
    },
    state: { sorting },
  });

  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const startRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Search name, contact, email, code…"
          className="w-full sm:w-72"
        />
        <Select<FirmType | "all">
          value={firmType}
          onChange={(v) => {
            setFirmType(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All firms" },
            { value: "supplier", label: "Supplier" },
            { value: "contractor", label: "Contractor" },
            { value: "service", label: "Service" },
            { value: "internal", label: "Internal" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<ContactStatus | "all">
          value={contactStatus}
          onChange={(v) => {
            setContactStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All contact" },
            { value: "complete", label: "Complete" },
            { value: "partial", label: "Partial" },
            { value: "minimal", label: "Minimal" },
            { value: "empty", label: "Empty" },
          ]}
        />
        <Select<CodingStatus | "all">
          value={codingStatus}
          onChange={(v) => {
            setCodingStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All coding" },
            { value: "coded", label: "Coded" },
            { value: "uncoded", label: "Uncoded" },
          ]}
        />
        <Input
          value={division}
          onChange={(e) => {
            // Backend takes a 2-digit MasterFormat division. Strip
            // non-digits and cap at 2 chars so users can paste "03 -
            // Concrete" and get the right query param.
            const cleaned = e.target.value.replace(/\D/g, "").slice(0, 2);
            setDivision(cleaned);
            setPage(1);
          }}
          placeholder="Div ##"
          className="w-24"
          inputMode="numeric"
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load vendor list." />}

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
                  No vendors match the current filters.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
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

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {total === 0
            ? "0 results"
            : `${startRow}–${endRow} of ${total.toLocaleString()}`}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || isLoading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Prev
          </Button>
          <span className="px-2 font-mono">
            {page} / {lastPage}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= lastPage || isLoading}
            onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
          >
            Next
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {selectedVendor && (
        <EnrichmentDrawer
          key={selectedVendor.id}
          vendor={selectedVendor}
          isSaving={enrichmentMutation.isPending}
          error={
            enrichmentMutation.error instanceof Error
              ? enrichmentMutation.error.message
              : null
          }
          onClose={() => setSelectedVendor(null)}
          onSubmit={(payload) =>
            enrichmentMutation.mutate({ id: selectedVendor.id, payload })
          }
        />
      )}
    </div>
  );
}

// Lightweight token-styled select. Hand-rolled instead of pulling in
// @radix-ui/react-select — five filter dropdowns don't justify the
// additional surface area.
function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="h-9 rounded-md border border-input bg-card px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function EnrichmentDrawer({
  vendor,
  isSaving,
  error,
  onClose,
  onSubmit,
}: {
  vendor: VendorListRow;
  isSaving: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (payload: VendorEnrichmentPayload) => void;
}) {
  const [contact, setContact] = useState(vendor.contact ?? "");
  const [title, setTitle] = useState(vendor.title ?? "");
  const [email, setEmail] = useState(vendor.email ?? "");
  const [phone, setPhone] = useState(vendor.phone ?? "");
  const [firmType, setFirmType] = useState<FirmType>(vendor.firm_type);
  const [codesText, setCodesText] = useState(vendor.codes.join("\n"));
  const [notes, setNotes] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const codes = codesText
      .split(/\n|,/)
      .map((code) => code.trim())
      .filter(Boolean);

    onSubmit({
      contact,
      title,
      email,
      phone,
      firm_type: firmType,
      codes,
      notes,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/70 backdrop-blur-sm">
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        aria-label="Close enrichment drawer"
        onClick={onClose}
      />
      <Card className="relative h-full w-full max-w-xl overflow-y-auto rounded-none border-y-0 border-r-0 shadow-xl">
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle>Enrich vendor</CardTitle>
            <CardDescription>
              Overlay clean contact, firm, and CSI data without changing
              mart_vendors.
            </CardDescription>
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={onClose}>
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </Button>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="text-sm font-medium">
                {vendor.name ?? "(unnamed)"}
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>{contactStyles[vendor.contact_status].label} contact</span>
                <span>·</span>
                <span>{vendor.code_count} CSI codes</span>
                {vendor.enriched && (
                  <>
                    <span>·</span>
                    <span>enriched</span>
                  </>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Contact">
                <Input
                  value={contact}
                  onChange={(e) => setContact(e.target.value)}
                  placeholder="Primary contact"
                />
              </Field>
              <Field label="Title">
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Estimator, PM, owner…"
                />
              </Field>
              <Field label="Email">
                <Input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  type="email"
                />
              </Field>
              <Field label="Phone">
                <Input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="555-0101"
                />
              </Field>
            </div>

            <Field label="Firm type">
              <Select<FirmType>
                value={firmType}
                onChange={setFirmType}
                options={[
                  { value: "supplier", label: "Supplier" },
                  { value: "contractor", label: "Contractor" },
                  { value: "service", label: "Service" },
                  { value: "internal", label: "Internal" },
                  { value: "unknown", label: "Unknown" },
                ]}
              />
            </Field>

            <Field label="CSI additions / current codes">
              <textarea
                value={codesText}
                onChange={(e) => setCodesText(e.target.value)}
                placeholder="0330-Cast-in-place Concrete"
                className="min-h-28 w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                One code per line or comma-separated. Backend keeps the first
                five distinct codes after merging with mart_vendors.
              </p>
            </Field>

            <Field label="Notes">
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Source, confidence, next follow-up…"
                className="min-h-20 w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </Field>

            {error && <ErrorBlock message={error} />}

            <div className="flex justify-end gap-2 border-t border-border pt-4">
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSaving}>
                {isSaving ? "Saving…" : "Save enrichment"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

// ── Insights ─────────────────────────────────────────────────────────

function InsightsTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.insights(10, 2),
    queryFn: () => fetchVendorInsights(10, 2),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  return (
    <div className="space-y-6">
      {/* Top divisions and top codes side by side */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Top divisions</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Two-digit MasterFormat divisions ranked by distinct vendors.
          </p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={data.top_divisions}
                layout="vertical"
                margin={{ top: 4, right: 16, bottom: 4, left: 16 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                  horizontal={false}
                />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  stroke="hsl(var(--border))"
                  allowDecimals={false}
                />
                <YAxis
                  type="category"
                  dataKey="division"
                  width={40}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  stroke="hsl(var(--border))"
                />
                <RechartsTooltip
                  cursor={{ fill: "hsl(var(--muted))" }}
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(_v, _n, ctx) => {
                    const row = ctx.payload as
                      | { vendor_count?: number; example_code?: string | null }
                      | undefined;
                    return [
                      `${row?.vendor_count ?? 0} vendors${
                        row?.example_code ? ` · e.g. ${row.example_code}` : ""
                      }`,
                      "",
                    ];
                  }}
                  labelFormatter={(d: string) => `Division ${d}`}
                />
                <Bar
                  dataKey="vendor_count"
                  fill="hsl(var(--info))"
                  radius={[0, 6, 6, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-sm font-semibold">Top CSI codes</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Most-claimed individual codes across the directory.
          </p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={data.top_codes}
                layout="vertical"
                margin={{ top: 4, right: 16, bottom: 4, left: 24 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                  horizontal={false}
                />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  stroke="hsl(var(--border))"
                  allowDecimals={false}
                />
                <YAxis
                  type="category"
                  dataKey="code"
                  width={56}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  stroke="hsl(var(--border))"
                />
                <RechartsTooltip
                  cursor={{ fill: "hsl(var(--muted))" }}
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(v: number) => [`${v} vendors`, "Count"]}
                  labelFormatter={(c: string) => `Code ${c}`}
                />
                <Bar
                  dataKey="vendor_count"
                  fill="hsl(var(--primary))"
                  radius={[0, 6, 6, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* Recruitment gaps + contact health */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-warning" />
            <h4 className="text-sm font-semibold">Recruitment gaps</h4>
          </div>
          <p className="mb-3 text-xs text-muted-foreground">
            Divisions with ≤2 vendors on file — candidate areas to recruit
            new subs into.
          </p>
          {data.thin_divisions.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No thin divisions detected.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {data.thin_divisions.map((d) => (
                <span
                  key={d.division}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
                    toneStyles.warn.bg,
                    toneStyles.warn.text,
                  )}
                >
                  Div {d.division}
                  <span className="font-mono">{d.vendor_count}</span>
                  {d.example_code && (
                    <span className="text-muted-foreground">
                      · {d.example_code}
                    </span>
                  )}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <h4 className="mb-3 text-sm font-semibold">Contact health</h4>
          <div className="space-y-2">
            {CONTACT_ORDER.map((c) => {
              const count = data.contact_health[c];
              const cs = contactStyles[c];
              const ts = toneStyles[cs.tone];
              return (
                <div key={c} className="flex items-center justify-between gap-3">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
                      ts.bg,
                      ts.text,
                    )}
                  >
                    {cs.label}
                  </span>
                  <span className="font-mono text-sm font-semibold tabular-nums">
                    {count.toLocaleString()}
                  </span>
                </div>
              );
            })}
            <div className="border-t border-border pt-2" />
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">Coded</span>
              <span className="font-mono text-sm font-semibold tabular-nums">
                {data.coding_breakdown.coded.toLocaleString()}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">Uncoded</span>
              <span className="font-mono text-sm font-semibold tabular-nums">
                {data.coding_breakdown.uncoded.toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Depth leaders */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Depth leaders</h3>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">
          Vendors with the broadest CSI coverage — versatile multi-trade subs.
        </p>
        {data.depth_leaders.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No coded vendors yet.
          </p>
        ) : (
          <div className="rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Vendor</TableHead>
                  <TableHead>Firm</TableHead>
                  <TableHead className="text-right">Codes</TableHead>
                  <TableHead>Examples</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.depth_leaders.map((v) => {
                  const fs = firmStyles[v.firm_type];
                  const ts = toneStyles[fs.tone];
                  return (
                    <TableRow key={v.id}>
                      <TableCell className="font-medium">
                        {v.name ?? (
                          <span className="italic text-muted-foreground">
                            (unnamed)
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <span
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                            ts.bg,
                            ts.text,
                          )}
                        >
                          <fs.Icon className="h-3 w-3" />
                          {fs.label}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {v.code_count}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {v.codes.slice(0, 5).join(", ")}
                        {v.codes.length > 5 && "…"}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Right rail: Recommendations — Phase 6 LLM panel
// ──────────────────────────────────────────────────────────────────────
//
// Delegates to the shared `RecommendationsRail`. Slug must match the
// FastAPI mount in `app/main.py` — `vendors`.

function RecommendationsRail() {
  return (
    <SharedRecommendationsRail
      moduleSlug="vendors"
      description="Claude-ranked next actions for your vendor bench, refreshed every 6 hours."
    />
  );
}

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
      {message}
    </div>
  );
}

function SkeletonBlock({ height = "h-24" }: { height?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", height)} />;
}

function SkeletonGrid({ count }: { count: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonBlock key={i} height="h-24" />
      ))}
    </div>
  );
}

function safeShare(part: number, total: number): number {
  return total > 0 ? part / total : 0;
}

function formatPercent(n: number): string {
  return `${(n * 100).toFixed(0)}%`;
}
