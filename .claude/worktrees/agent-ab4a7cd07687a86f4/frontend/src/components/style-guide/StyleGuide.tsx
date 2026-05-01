import { useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  Check,
  Info,
  Sparkles,
} from "lucide-react";

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
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

/**
 * StyleGuide — Storybook-style preview page mounted at /style-guide.
 *
 * Owned by the Frontend Polish lane. Single source of visual truth for
 * the cross-module design system: tokens, severity tones, typography,
 * primitives, and the new Sheet + field-mode work.
 *
 * Conventions on this page:
 *   - No new color tokens. Every swatch references an existing semantic
 *     variable from src/index.css.
 *   - No fetches. The Recommendations preview is a static visual mock
 *     of the rail's card pattern — the real <RecommendationsRail/>
 *     hits an API and isn't appropriate to render in a style guide.
 *   - The field-mode preview scopes `data-field="true"` to a single
 *     wrapper so toggling it doesn't disturb the rest of the chrome
 *     (Topbar already has a global toggle; this one is for comparison).
 */
export function StyleGuide() {
  return (
    <div className="space-y-10 p-6 lg:p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Style Guide</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Cross-module design system reference. Every primitive, token, and
          severity tone the FieldBridge UI uses today.
        </p>
      </header>

      <SectionTokens />
      <SectionSeverity />
      <SectionTypography />
      <SectionButtons />
      <SectionBadges />
      <SectionCards />
      <SectionInputs />
      <SectionTabsDemo />
      <SectionSheet />
      <SectionRecommendationsPreview />
      <SectionFieldMode />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Section wrapper — keeps headings + spacing consistent across sections.
// ──────────────────────────────────────────────────────────────────────

function StyleSection({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-3">
      <div>
        <h2 id={`${id}-heading`} className="text-lg font-semibold tracking-tight">
          {title}
        </h2>
        {description && (
          <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      <div>{children}</div>
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tokens
// ──────────────────────────────────────────────────────────────────────

interface Swatch {
  name: string;
  className: string; // bg-* token class
  hex: string;
  textOn?: string; // class to use when rendering text on this color
}

const surfaceSwatches: Swatch[] = [
  { name: "background", className: "bg-background", hex: "#F5F3EE", textOn: "text-foreground" },
  { name: "card", className: "bg-card", hex: "#FFFFFF", textOn: "text-card-foreground" },
  { name: "sidebar", className: "bg-sidebar", hex: "#FAFAF8", textOn: "text-sidebar-foreground" },
  { name: "muted", className: "bg-muted", hex: "#F1F5F9", textOn: "text-muted-foreground" },
  { name: "popover", className: "bg-popover", hex: "#FFFFFF", textOn: "text-popover-foreground" },
];

const semanticSwatches: Swatch[] = [
  { name: "primary", className: "bg-primary", hex: "#10B981", textOn: "text-primary-foreground" },
  { name: "info", className: "bg-info", hex: "#3B82F6", textOn: "text-info-foreground" },
  { name: "warning", className: "bg-warning", hex: "#F97316", textOn: "text-warning-foreground" },
  { name: "critical", className: "bg-critical", hex: "#EF4444", textOn: "text-critical-foreground" },
  { name: "monitor", className: "bg-monitor", hex: "#F59E0B", textOn: "text-monitor-foreground" },
  { name: "accent", className: "bg-accent", hex: "#0F172A", textOn: "text-accent-foreground" },
];

function SectionTokens() {
  return (
    <StyleSection
      id="tokens"
      title="Color tokens"
      description="HSL triples live in src/index.css; every Tailwind utility resolves through hsl(var(--token))."
    >
      <div className="space-y-4">
        <TokenGroup heading="Surfaces" swatches={surfaceSwatches} />
        <TokenGroup heading="Semantic" swatches={semanticSwatches} />
      </div>
    </StyleSection>
  );
}

function TokenGroup({
  heading,
  swatches,
}: {
  heading: string;
  swatches: Swatch[];
}) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {heading}
      </h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {swatches.map((s) => (
          <div
            key={s.name}
            className="overflow-hidden rounded-lg border border-border"
          >
            <div
              className={cn(
                "flex h-16 items-end px-3 pb-2 text-[11px] font-medium",
                s.className,
                s.textOn ?? "text-foreground",
              )}
            >
              {s.name}
            </div>
            <div className="flex items-center justify-between gap-2 bg-card px-3 py-2">
              <code className="font-mono text-[11px] text-muted-foreground">
                {s.hex}
              </code>
              <code className="font-mono text-[10px] text-muted-foreground">
                bg-{s.name}
              </code>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Severity tones (the cross-module 5-tone system)
// ──────────────────────────────────────────────────────────────────────

interface Tone {
  key: "good" | "info" | "warn" | "crit" | "neutral";
  label: string;
  meaning: string;
  border: string;
  bg: string;
  text: string;
  Icon: typeof Check;
}

const tones: Tone[] = [
  {
    key: "good",
    label: "good",
    meaning: "On-target / healthy / closed",
    border: "border-l-primary",
    bg: "bg-primary/10",
    text: "text-primary",
    Icon: Check,
  },
  {
    key: "info",
    label: "info",
    meaning: "Neutral / under-utilized / open backlog",
    border: "border-l-info",
    bg: "bg-info/10",
    text: "text-info",
    Icon: Info,
  },
  {
    key: "warn",
    label: "warn",
    meaning: "Caution / hold / mid-aged / over-billed",
    border: "border-l-warning",
    bg: "bg-warning/10",
    text: "text-warning",
    Icon: AlertTriangle,
  },
  {
    key: "crit",
    label: "crit",
    meaning: "Alert / overdue / loss / critical priority",
    border: "border-l-critical",
    bg: "bg-critical/10",
    text: "text-critical",
    Icon: AlertOctagon,
  },
  {
    key: "neutral",
    label: "neutral",
    meaning: "Unknown / no-data / disabled",
    border: "border-l-accent",
    bg: "bg-muted",
    text: "text-muted-foreground",
    Icon: Info,
  },
];

function SectionSeverity() {
  return (
    <StyleSection
      id="severity"
      title="Severity tones"
      description="The 5-tone system shared across Equipment, Jobs, Work Orders, Vendors, and the Recommendations rail. Modules pick from this set; never invent a 6th tone."
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {tones.map((t) => (
          <div
            key={t.key}
            className={cn(
              "flex flex-col gap-1.5 rounded-lg border border-border border-l-4 bg-card px-4 py-3.5",
              t.border,
            )}
          >
            <div
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-md",
                t.bg,
              )}
            >
              <t.Icon className={cn("h-3.5 w-3.5", t.text)} aria-hidden="true" />
            </div>
            <div className="font-mono text-sm font-semibold">{t.label}</div>
            <div className="text-[11px] text-muted-foreground">{t.meaning}</div>
          </div>
        ))}
      </div>
    </StyleSection>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Typography
// ──────────────────────────────────────────────────────────────────────

function SectionTypography() {
  return (
    <StyleSection
      id="typography"
      title="Typography"
      description="Inter for sans, system mono for numbers and IDs. Every module page follows this scale."
    >
      <Card>
        <CardContent className="space-y-3 pt-5">
          <TypeRow label="text-2xl font-semibold" preview="Page title" extra="text-2xl font-semibold tracking-tight" />
          <TypeRow label="text-base font-semibold" preview="Card title" extra="text-base font-semibold tracking-tight" />
          <TypeRow label="text-sm font-semibold" preview="Sub-heading" extra="text-sm font-semibold" />
          <TypeRow label="text-sm" preview="Body copy paragraph" extra="text-sm" />
          <TypeRow label="text-xs" preview="Helper / description" extra="text-xs text-muted-foreground" />
          <TypeRow label="text-[11px]" preview="Footnote / timestamp" extra="text-[11px] text-muted-foreground" />
          <TypeRow label="text-[10px]" preview="Badge label" extra="text-[10px] font-medium" />
          <TypeRow
            label="font-mono tabular-nums"
            preview="$1,234,567 · 42.0d"
            extra="font-mono text-sm font-semibold tabular-nums"
          />
        </CardContent>
      </Card>
    </StyleSection>
  );
}

function TypeRow({
  label,
  preview,
  extra,
}: {
  label: string;
  preview: string;
  extra: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border pb-2 last:border-b-0 last:pb-0">
      <span className={extra}>{preview}</span>
      <code className="font-mono text-[11px] text-muted-foreground">
        {label}
      </code>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Buttons
// ──────────────────────────────────────────────────────────────────────

const buttonVariantList = [
  "default",
  "destructive",
  "outline",
  "secondary",
  "ghost",
  "link",
  "accent",
] as const;

function SectionButtons() {
  return (
    <StyleSection
      id="buttons"
      title="Buttons"
      description="Variants × sizes. Field-mode forces a 44px floor on all of these via the [data-field] selector."
    >
      <Card>
        <CardContent className="space-y-4 pt-5">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Variants
            </h3>
            <div className="flex flex-wrap gap-2">
              {buttonVariantList.map((v) => (
                <Button key={v} variant={v}>
                  {v}
                </Button>
              ))}
            </div>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Sizes
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm">sm</Button>
              <Button size="default">default</Button>
              <Button size="lg">lg</Button>
              <Button size="icon" aria-label="Sparkles demo">
                <Sparkles className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Disabled
            </h3>
            <div className="flex flex-wrap gap-2">
              <Button disabled>disabled default</Button>
              <Button variant="outline" disabled>
                disabled outline
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </StyleSection>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Badges
// ──────────────────────────────────────────────────────────────────────

function SectionBadges() {
  return (
    <StyleSection
      id="badges"
      title="Badges"
      description="Use `mono` for KPI counts and `outline` for severity labels. Inline severity chips compose Badge with the tone classes from above."
    >
      <Card>
        <CardContent className="space-y-3 pt-5">
          <div className="flex flex-wrap gap-2">
            <Badge>default</Badge>
            <Badge variant="secondary">secondary</Badge>
            <Badge variant="outline">outline</Badge>
            <Badge variant="destructive">destructive</Badge>
            <Badge variant="mono">mono · 1,247</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            {tones
              .filter((t) => t.key !== "neutral")
              .map((t) => (
                <span
                  key={t.key}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                    t.bg,
                    t.text,
                  )}
                >
                  <t.Icon className="h-3 w-3" aria-hidden="true" />
                  {t.label}
                </span>
              ))}
          </div>
        </CardContent>
      </Card>
    </StyleSection>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Cards
// ──────────────────────────────────────────────────────────────────────

function SectionCards() {
  return (
    <StyleSection
      id="cards"
      title="Cards"
      description="Card / CardHeader / CardTitle / CardDescription / CardContent. The KPI tile pattern adds a 4px left-border accent in the relevant tone."
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Standard card</CardTitle>
            <CardDescription>Header + description above content.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm">
              Body content. Used for module Overview / List / Insights tabs and
              for static panels.
            </p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-primary">
          <CardHeader>
            <CardTitle>KPI accent card</CardTitle>
            <CardDescription>
              {"Severity tone via `border-l-{tone}`."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="font-mono text-2xl font-semibold tabular-nums">
              42
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Equipment / Jobs / WorkOrders KPI tiles all follow this pattern.
            </p>
          </CardContent>
        </Card>
      </div>
    </StyleSection>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Inputs
// ──────────────────────────────────────────────────────────────────────

function SectionInputs() {
  const [enabled, setEnabled] = useState(true);
  return (
    <StyleSection
      id="inputs"
      title="Inputs"
      description="Input + Switch. In field-mode, every input grows to a 44px min-height to give gloves a target."
    >
      <Card>
        <CardContent className="space-y-3 pt-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium" htmlFor="sg-input">
                Default
              </label>
              <Input id="sg-input" placeholder="Search…" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium" htmlFor="sg-input-2">
                Disabled
              </label>
              <Input id="sg-input-2" placeholder="Read-only" disabled />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Switch
              checked={enabled}
              onCheckedChange={setEnabled}
              aria-label="Demo switch"
              id="sg-switch"
            />
            <label htmlFor="sg-switch" className="text-sm">
              Switch ({enabled ? "on" : "off"})
            </label>
          </div>
        </CardContent>
      </Card>
    </StyleSection>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tabs
// ──────────────────────────────────────────────────────────────────────

function SectionTabsDemo() {
  return (
    <StyleSection
      id="tabs"
      title="Tabs"
      description="Module pages mount Tabs inside a Card. Three tabs is the canonical count: Overview / List / Insights."
    >
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
            <TabsContent value="overview" className="mt-0 text-sm">
              Aggregate panels live here.
            </TabsContent>
            <TabsContent value="list" className="mt-0 text-sm">
              Paginated TanStack table goes here.
            </TabsContent>
            <TabsContent value="insights" className="mt-0 text-sm">
              Charts and drill-downs live here.
            </TabsContent>
          </CardContent>
        </Tabs>
      </Card>
    </StyleSection>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Sheet (the new primitive)
// ──────────────────────────────────────────────────────────────────────

function SectionSheet() {
  return (
    <StyleSection
      id="sheet"
      title="Sheet"
      description="New shadcn primitive (Radix Dialog). Powers the mobile sidebar drawer; reusable for any side-anchored panel. side prop accepts top | right | bottom | left."
    >
      <Card>
        <CardContent className="flex flex-wrap gap-2 pt-5">
          {(["top", "right", "bottom", "left"] as const).map((side) => (
            <Sheet key={side}>
              <SheetTrigger asChild>
                <Button variant="outline">Open {side}</Button>
              </SheetTrigger>
              <SheetContent side={side}>
                <SheetHeader>
                  <SheetTitle>side=&quot;{side}&quot;</SheetTitle>
                  <SheetDescription>
                    Sheet panel anchored to the {side} edge. Esc to close, click
                    overlay to dismiss, focus is trapped while open.
                  </SheetDescription>
                </SheetHeader>
                <div className="px-4 pb-4 text-xs text-muted-foreground">
                  Reduced-motion preference is honored automatically — the
                  slide animation collapses to an instant transition.
                </div>
              </SheetContent>
            </Sheet>
          ))}
        </CardContent>
      </Card>
    </StyleSection>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Recommendations rail — visual preview only (no fetch)
// ──────────────────────────────────────────────────────────────────────

function SectionRecommendationsPreview() {
  return (
    <StyleSection
      id="recommendations"
      title="Recommendations rail"
      description="Static preview of the canonical card pattern. The real <RecommendationsRail/> fetches from /api/<slug>/recommendations and renders the same shape per severity."
    >
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
            <CardTitle>Recommendations</CardTitle>
          </div>
          <CardDescription>
            One example card per severity. Real rail uses roving-tabindex over
            the list (Arrow / Home / End) — see RecommendationsRail.tsx.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <RailPreviewItem
            tone={tones[3]}
            title="Replace hydraulic hose on Excavator-CAT-336"
            rationale="Pressure variance trending high over the last 7 ticket cycles."
            action="Schedule shop visit before Friday's pour."
            assets={["EQ-001234", "EQ-001235"]}
          />
          <RailPreviewItem
            tone={tones[2]}
            title="Vendor invoice stuck in approval"
            rationale="Aging > 30 days on $42K of pending AP."
            action="Route to CFO for sign-off this week."
            assets={["VND-0042"]}
          />
          <RailPreviewItem
            tone={tones[1]}
            title="Coding suggestion available"
            rationale="6 line items match the pattern of 12-7720 from prior jobs."
            action="Apply with one click in the cost-coding queue."
            assets={[]}
          />
        </CardContent>
      </Card>
    </StyleSection>
  );
}

function RailPreviewItem({
  tone,
  title,
  rationale,
  action,
  assets,
}: {
  tone: Tone;
  title: string;
  rationale: string;
  action: string;
  assets: string[];
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        tone.key === "crit" && "border-critical/30 bg-critical/5",
        tone.key === "warn" && "border-amber-300/60 bg-amber-50/60",
        tone.key === "info" && "border-border bg-muted/20",
      )}
    >
      <div className="flex items-start gap-2">
        <tone.Icon
          className={cn("mt-0.5 h-4 w-4 shrink-0", tone.text)}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold leading-tight">{title}</p>
            <Badge variant="outline" className={cn("text-[10px]", tone.text)}>
              {tone.key === "crit"
                ? "critical"
                : tone.key === "warn"
                  ? "warning"
                  : "info"}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">{rationale}</p>
          <p className="text-xs">
            <span className="font-medium">Action: </span>
            {action}
          </p>
          {assets.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {assets.map((a) => (
                <Badge key={a} variant="secondary" className="text-[10px]">
                  {a}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Field mode preview (scoped data-field toggle)
// ──────────────────────────────────────────────────────────────────────

function SectionFieldMode() {
  const [on, setOn] = useState(false);
  return (
    <StyleSection
      id="field-mode"
      title="Field mode"
      description="Data-field=true scopes the high-contrast token re-points and 44px tap-target floor. The Topbar toggle flips it globally; this preview is scoped to the wrapper below so you can A/B compare."
    >
      <Card>
        <CardContent className="space-y-3 pt-5">
          <div className="flex items-center gap-3">
            <Switch
              id="sg-field-mode"
              checked={on}
              onCheckedChange={setOn}
              aria-label="Toggle scoped field mode"
            />
            <label htmlFor="sg-field-mode" className="text-sm">
              Scoped field-mode preview ({on ? "on" : "off"})
            </label>
          </div>
          <div
            data-field={on ? "true" : undefined}
            className="rounded-lg border border-border bg-card p-4"
          >
            <p className="text-sm text-muted-foreground">
              Sample paragraph copy — observe the contrast shift between this
              line and the surrounding chrome when the toggle flips on.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button variant="default">Primary</Button>
              <Button variant="outline">Outline</Button>
              <Badge variant="outline" className="text-critical">
                critical
              </Badge>
              <Input placeholder="Sample input" className="w-48" />
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              In field-mode the borders darken, semantic tokens saturate, and
              every interactive element above grows to a 44×44 floor.
            </p>
          </div>
        </CardContent>
      </Card>
    </StyleSection>
  );
}
