import { ChevronDown, MapPin } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Multi-select dropdown for two-letter state codes.
 *
 * Built on the existing shadcn `dropdown-menu` primitive — no new
 * primitive needed. Selection is owned by the parent (controlled
 * input). Empty selection is allowed and rendered as "All states";
 * the parent decides whether that translates to "all" or "none" on
 * the wire.
 *
 * a11y:
 *   - Trigger button announces the active count via aria-label.
 *   - Each option is a checkbox role (Radix CheckboxItem).
 *   - "All" / "None" header buttons let keyboard users bulk-toggle.
 */

export interface StateMultiSelectProps {
  /** Two-letter state codes the menu offers. Order is preserved. */
  options: string[];
  /** Currently selected codes. */
  value: string[];
  /** Called with the next selection. */
  onChange: (next: string[]) => void;
  /** Optional override for the trigger label. Defaults to a count. */
  label?: string;
  /** Optional id passthrough so a parent <label htmlFor> can target it. */
  id?: string;
}

export function StateMultiSelect({
  options,
  value,
  onChange,
  label,
  id,
}: StateMultiSelectProps) {
  const selectedSet = new Set(value);
  const count = value.length;
  const allSelected = count === options.length;
  const triggerLabel =
    label ??
    (count === 0
      ? "All states"
      : count === 1
        ? value[0]
        : `${count} states`);

  function toggle(code: string, checked: boolean) {
    if (checked) {
      // Preserve options-order on insert so the comma-joined wire
      // string is deterministic regardless of click order.
      const nextSet = new Set(selectedSet);
      nextSet.add(code);
      onChange(options.filter((o) => nextSet.has(o)));
    } else {
      onChange(value.filter((v) => v !== code));
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          id={id}
          variant="outline"
          size="sm"
          className="h-9 gap-2"
          aria-label={`Filter by state — ${count === 0 ? "all states" : `${count} selected`}`}
        >
          <MapPin className="h-3.5 w-3.5" aria-hidden />
          <span className="font-medium">{triggerLabel}</span>
          <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <div className="flex items-center justify-between px-2 py-1.5">
          <DropdownMenuLabel className="px-0 py-0 text-xs uppercase tracking-wide text-muted-foreground">
            States
          </DropdownMenuLabel>
          <div className="flex items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => onChange([...options])}
              disabled={allSelected}
              className="text-info hover:underline disabled:cursor-not-allowed disabled:opacity-40"
            >
              All
            </button>
            <span aria-hidden className="text-muted-foreground">·</span>
            <button
              type="button"
              onClick={() => onChange([])}
              disabled={count === 0}
              className="text-muted-foreground hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-40"
            >
              None
            </button>
          </div>
        </div>
        <DropdownMenuSeparator />
        {options.map((code) => (
          <DropdownMenuCheckboxItem
            key={code}
            checked={selectedSet.has(code)}
            onCheckedChange={(checked) => toggle(code, Boolean(checked))}
            // Don't auto-close on each pick; multi-select needs to stay open.
            onSelect={(e) => e.preventDefault()}
          >
            <span className="font-mono text-xs">{code}</span>
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
