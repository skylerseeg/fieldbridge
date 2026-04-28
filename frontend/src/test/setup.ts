import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

/**
 * Global test setup.
 *
 *   - jest-dom matchers (toBeInTheDocument, toHaveAttribute, etc.) are
 *     bolted onto Vitest's expect via the import above.
 *   - Auto-cleanup between tests so each renderResult starts fresh.
 *   - matchMedia + ResizeObserver shims — Radix primitives (Dialog,
 *     ScrollArea) reach for them on mount, and jsdom doesn't ship them.
 */

afterEach(() => {
  cleanup();
});

// matchMedia shim — defaults to "doesn't match" so tests render the
// mobile-first branch unless they explicitly override per-test.
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// ResizeObserver shim — Radix ScrollArea instantiates one. No-op is fine
// because we don't actually exercise scroll behavior in unit tests.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverShim {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverShim as unknown as typeof ResizeObserver;
}

// pointer-event shim — Radix Dialog's overlay uses pointer events, jsdom
// stubs hasPointerCapture as undefined which breaks @testing-library
// click forwarding. Stub it as a no-op.
if (typeof Element !== "undefined" && !Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
}
