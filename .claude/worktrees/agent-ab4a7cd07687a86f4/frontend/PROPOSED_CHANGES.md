# PROPOSED_CHANGES — `frontend-test` job activation

**From**: Frontend Polish Worker (Agent #4)
**To**: Tests/CI Worker (Agent #5)
**Date**: 2026-04-28
**Touches Tests/CI-owned**: `fieldbridge/.github/workflows/ci.yml`

## Why

Vitest is now wired in `fieldbridge/frontend/`. The `frontend-test` job
in `ci.yml` (lines 145-173) is currently advisory — it skips the run
when `npm test` doesn't exist. That script now exists and 17/17 tests
pass on `main`. The placeholder is ready to become a hard gate.

This is a turnkey edit: replace the conditional block with the snippet
below. No upstream changes needed in `frontend/` from your side; deps,
scripts, and config are all in place.

## State on the frontend side (already shipped)

- `package.json` adds `"test": "vitest run"` and `"test:watch": "vitest"`
- DevDeps: `vitest@4.1.5`, `@vitest/coverage-v8@4.1.5`,
  `@testing-library/react@16.3.2`, `@testing-library/jest-dom@6.9.1`,
  `@testing-library/user-event@14.6.1`, `happy-dom`
- `vite.config.ts` declares the `test:` block (env: happy-dom, globals on,
  setup file: `./src/test/setup.ts`)
- Test setup at `src/test/setup.ts` shims `matchMedia`, `ResizeObserver`,
  and pointer-capture/scrollIntoView Element prototype methods (Radix
  Dialog needs them)
- 2 test files committed under `src/components/__tests__/`:
  `AppShell.test.tsx` (8 tests) and `RecommendationsRail.test.tsx`
  (9 tests)
- `.gitignore` already excludes `coverage/` and `*-junit.xml`

## Verified locally

```
$ cd fieldbridge/frontend
$ npm test -- --coverage --reporter=default --reporter=junit --outputFile.junit=vitest-junit.xml
Test Files  2 passed (2)
     Tests  17 passed (17)
  Duration  ~8s
JUNIT report written to vitest-junit.xml
Coverage summary:
  Statements   : 67.97% ( 191/281 )
  Branches     : 54.4%  ( 68/125 )
  Functions    : 66.66% ( 56/84 )
  Lines        : 67.88% ( 186/274 )
```

(Coverage % is across files actually loaded by the tests — vitest v8
coverage doesn't auto-include unimported files. If you want full-tree
coverage we can set `coverage.all: true` + an `include` pattern in
`vite.config.ts` later.)

## What to drop into `ci.yml`

Replace the existing `frontend-test` job (lines 145-173) with the block
below. It mirrors `backend-test`'s conventions: a real run + coverage
HTML upload + junit upload, all `if: always()` so artifacts survive a
failed test run. No threshold gate — see "Coverage threshold" below.

```yaml
  frontend-test:
    name: frontend / vitest + coverage
    runs-on: ubuntu-latest
    needs: frontend-lint
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: fieldbridge/frontend/package-lock.json

      - name: Install
        working-directory: fieldbridge/frontend
        run: npm ci

      # Coverage threshold left advisory for now — we're at ~68% on
      # the small slice of files actually loaded by tests, but most
      # of frontend/src/ has zero tests yet. Raise this to a hard
      # gate once module workers backfill their lanes. Ratchet
      # schedule to be set by Tests/CI Worker (mirror backend's
      # quarterly bump pattern in COV_FAIL_UNDER).
      - name: vitest with coverage
        working-directory: fieldbridge/frontend
        run: |
          npm test -- \
            --coverage \
            --reporter=default \
            --reporter=junit \
            --outputFile.junit=vitest-junit.xml

      - name: Upload vitest coverage HTML
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: frontend-coverage-html
          path: fieldbridge/frontend/coverage

      - name: Upload vitest junit
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: frontend-vitest-junit
          path: fieldbridge/frontend/vitest-junit.xml
```

## Notes that might matter to you

1. **`happy-dom`, not `jsdom`.** Tried jsdom@27 first — it requires
   Node ≥20.19 and CI's Node 20 lockstep gives 20.18 unless we pin
   harder. `happy-dom` is the modern lighter default for vitest and
   needs zero system-level browser/Chromium. Pure Node — works in
   `ubuntu-latest` with no extra `apt-get install`.

2. **No env vars.** Tests stub auth state via `useAuth.setState({...})`
   in `beforeEach` and mock `fetchRecommendations` via `vi.mock()` —
   so no `VITE_*` or backend-pointing config is needed in CI. The
   `vite.config.ts` `test:` block sets `css: false` so Tailwind isn't
   compiled during tests (faster + avoids PostCSS surprises in CI).

3. **`npm test` is `vitest run` (one-shot).** No watch mode in CI.
   Will exit cleanly. Total wall-time on my dev box: ~8s with
   coverage, ~5s without. Should be well under the cancel-superseded
   `concurrency.cancel-in-progress` threshold.

4. **`needs: frontend-lint` preserved.** Same dependency the existing
   placeholder has. If `frontend-lint` (eslint + tsc) fails, vitest
   doesn't run — saves CI minutes since lint failures usually mean
   compile errors in the same files the tests would import.

5. **`actions/upload-artifact@v4` matches your backend pattern.**
   Matched naming convention: `frontend-coverage-html` and
   `frontend-vitest-junit` parallel `backend-coverage-html` and
   `backend-pytest-junit`.

## Coverage threshold — recommendation

Don't set one yet. The 68% number is misleading because vitest v8
coverage only counts files actually imported during tests. Two
test files exercise ~12 components; the other ~50 files in
`frontend/src/` aren't even loaded. A real %-of-tree threshold
needs `coverage.all: true` + an `include` glob, and the resulting
real number will be 5-10% — too low to gate on without spreading
panic across module workers.

Suggested phasing (you own the call):

| Phase | Trigger                                  | Action                                      |
|-------|------------------------------------------|---------------------------------------------|
| Now   | This bundle merges                       | Advisory only. No threshold flag.           |
| +1mo  | 3+ module workers have added test files | Add `coverage.all: true` + include glob.    |
| +2mo  | Real-tree coverage stabilizes            | Set `--coverage.thresholds.lines=20` (low). |
| Q3    | More worker buy-in                       | Quarterly ratchet, mirroring backend's 65→70→75→80 pattern. |

I can codify that in `vite.config.ts`'s `test.coverage` block when
you green-light. Until then the snippet above runs coverage for
artifacts but doesn't fail the build on it.

## Gating-issue heads-up (separate from this proposal)

`backend/tests/PROPOSED_CHANGES.md` (commit `db9b6df`) flags that
`fieldbridge/.github/workflows/ci.yml` isn't actually registered with
GitHub Actions — workflows have to live at repo-root
`.github/workflows/`. None of this `frontend-test` work fires until
that relocation happens. Calling it out so this proposal isn't
double-counted as activation. Once the workflow file moves, the
edit above is the activation step.

## Backwards-compat / risk

- Pure Tests/CI lane edit. No frontend code touched.
- Replaces an advisory placeholder with a real gate. Worst-case
  failure mode: a flaky test fails CI on a frontend module worker's
  PR. We have only 17 tests today, all deterministic (no real timers,
  no network), so the flake risk is near-zero on the current suite.
- If a future test does become flaky, `vitest --retry=2` is one
  flag away; flag back to me and I'll harden the suite.
