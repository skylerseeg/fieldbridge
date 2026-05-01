import { ChevronDown, Tags } from "lucide-react";

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
 * Multi-select dropdown for CSI scope codes.
 *
 * Mirrors `StateMultiSelect` from slice 1 but tuned for the scope-code
 * shape: codes are longer strings (e.g. "32 11 23"), so the trigger
 * label says "All scopes" / "{count} scopes" instead of echoing a
 * single code, and the option width is slightly wider.
 *
 * Selection is parent-owned (controlled input). Empty selection is
 * allowed and renders as "All scopes" — but the parent treats `[]`
 * differently from `options.length` selections in this tab: empty
 * filters out every row (intentional — user explicitly turned off
 * everything), full set means "no filter".
 */

export interface ScopeMultiSelectProps {
  /** CSI scope codes the menu offers. */
  options: string[];
  /** Currently selected codes. */
  value: string[];
  /** Called with the next selection. */
  onChange: (next: string[]) => void;
  /** Optional id for label htmlFor. */
  id?: string;
}

export function ScopeMultiSelect({
  options,
  value,
  onChange,
  id,
}: ScopeMultiSelectProps) {
  const selectedSet = new Set(value);
  const count = value.length;
  const allSelected = count === options.length && count > 0;
  const triggerLabel =
    count === 0
      ? "No scopes"
      : count === options.length
        ? "All scopes"
        : count === 1
          ? value[0]
          : `${count} scopes`;

  function toggle(code: string, checked: boolean) {
    if (checked) {
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
          aria-label={`Filter by scope code — ${
            count === 0
              ? "no scopes selected"
              : count === options.length
                ? "all scopes"
                : `${count} of ${options.length} scopes selected`
          }`}
        >
          <Tags className="h-3.5 w-3.5" aria-hidden />
          <span className="font-medium">{triggerLabel}</span>
          <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56 max-h-80 overflow-auto">
        <div className="flex items-center justify-between px-2 py-1.5">
          <DropdownMenuLabel className="px-0 py-0 text-xs uppercase tracking-wide text-muted-foreground">
            Scope codes
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
        {options.length === 0 ? (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            No scope codes in the current dataset.
          </div>
        ) : (
          options.map((code) => (
            <DropdownMenuCheckboxItem
              key={code}
              checked={selectedSet.has(code)}
              onCheckedChange={(checked) => toggle(code, Boolean(checked))}
              onSelect={(e) => e.preventDefault()}
            >
              <span className="font-mono text-xs">{code}</span>
            </DropdownMenuCheckboxItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
