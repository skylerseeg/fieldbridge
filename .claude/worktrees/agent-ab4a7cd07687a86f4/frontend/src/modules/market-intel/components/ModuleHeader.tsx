import { StateMultiSelect } from "./StateMultiSelect";

/**
 * Page-level header for the Market Intel module.
 *
 * Holds the H1, the subtitle copy, and the right-aligned filter bar
 * (state multi-select + months-back select). Filter state itself
 * lives one level up in `MarketIntelPage` and is passed in here.
 *
 * The brief locks:
 *   - Title `Bid intelligence` (sentence case, ~28 px, weight 500).
 *   - Subtitle copy (verbatim).
 *   - Default state list UT/ID/NV/WY/CO/AZ.
 *   - Months-back default 36, options 12/24/36.
 */

export const STATE_OPTIONS = ["UT", "ID", "NV", "WY", "CO", "AZ"] as const;
export const MONTHS_BACK_OPTIONS = [12, 24, 36] as const;

export type MonthsBack = (typeof MONTHS_BACK_OPTIONS)[number];

export interface ModuleHeaderProps {
  states: string[];
  onStatesChange: (next: string[]) => void;
  monthsBack: MonthsBack;
  onMonthsBackChange: (next: MonthsBack) => void;
}

export function ModuleHeader({
  states,
  onStatesChange,
  monthsBack,
  onMonthsBackChange,
}: ModuleHeaderProps) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <h1 className="text-[28px] font-medium tracking-tight text-foreground">
          Bid intelligence
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Public bid intelligence across the western network. Pricing curves,
          missed opportunities, and self-calibration against the low bid.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StateMultiSelect
          options={[...STATE_OPTIONS]}
          value={states}
          onChange={onStatesChange}
          id="market-intel-states"
        />
        <label
          htmlFor="market-intel-months-back"
          className="flex items-center gap-2 text-xs text-muted-foreground"
        >
          <span className="sr-only sm:not-sr-only">Months back</span>
          <select
            id="market-intel-months-back"
            value={monthsBack}
            onChange={(e) =>
              onMonthsBackChange(Number(e.target.value) as MonthsBack)
            }
            className="h-9 rounded-md border border-input bg-card px-3 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {MONTHS_BACK_OPTIONS.map((m) => (
              <option key={m} value={m}>
                Last {m} months
              </option>
            ))}
          </select>
        </label>
      </div>
    </header>
  );
}
