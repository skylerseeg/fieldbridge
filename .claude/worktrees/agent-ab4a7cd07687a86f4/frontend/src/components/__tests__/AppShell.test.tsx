import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { AppShell } from "@/layouts/AppShell";
import { useAuth, type AuthUser } from "@/lib/auth";

/**
 * Locks in the AppShell's published contracts:
 *   - Breakpoint contract from layouts/AppShell.tsx (< md drawer, md+ persistent).
 *   - Field-mode toggle wiring (Topbar → AppShell root data-field attribute).
 *   - Mobile sidebar drawer open/close via the hamburger button.
 *
 * Pure jsdom tests — we don't actually evaluate CSS media queries here
 * (jsdom has no layout engine). What we CAN assert is that the
 * Tailwind responsive utility classes (`hidden md:flex`, `md:hidden`)
 * are present on the right elements, which is the contract Tailwind
 * actually enforces at runtime.
 */

const TEST_USER: AuthUser = {
  id: "user-test-1",
  email: "[email protected]",
  role: "owner",
  tenant: { id: "tenant-1", name: "Test Tenant", slug: "test" },
  department: "Operations",
};

function renderAppShell(initialPath = "/dashboard") {
  const router = createMemoryRouter(
    [
      {
        element: <AppShell />,
        children: [
          {
            index: true,
            element: <div>redirect</div>,
          },
          {
            path: "dashboard",
            element: <div data-testid="route-content">dashboard content</div>,
          },
          {
            path: "equipment",
            element: <div data-testid="route-content">equipment content</div>,
          },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  );
  return render(<RouterProvider router={router} />);
}

describe("AppShell — breakpoint contract", () => {
  beforeEach(() => {
    useAuth.setState({
      token: "fake-token",
      refreshToken: null,
      user: TEST_USER,
    });
  });

  it("renders the desktop sidebar with the responsive hide class", () => {
    renderAppShell();

    const aside = screen.getByRole("complementary", { hidden: true });
    // Desktop sidebar must be visually hidden below md and re-show as a
    // flex container at md+. Both classes together = the contract.
    expect(aside.className).toContain("hidden");
    expect(aside.className).toContain("md:flex");
  });

  it("renders a hamburger button with md:hidden", () => {
    renderAppShell();

    const hamburger = screen.getByRole("button", { name: /open navigation/i });
    expect(hamburger).toBeInTheDocument();
    expect(hamburger.className).toContain("md:hidden");
  });

  it("uses a flex column on mobile and grid on md+", () => {
    const { container } = renderAppShell();

    // The AppShell root is the first child of the rendered tree. Per
    // the breakpoint contract, it must be `flex flex-col` by default
    // and switch to `md:grid md:grid-cols-[240px_1fr]` at md+.
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain("flex");
    expect(root.className).toContain("flex-col");
    expect(root.className).toContain("md:grid");
    expect(root.className).toMatch(/md:grid-cols-\[240px_1fr\]/);
  });
});

describe("AppShell — mobile sidebar drawer", () => {
  beforeEach(() => {
    useAuth.setState({
      token: "fake-token",
      refreshToken: null,
      user: TEST_USER,
    });
  });

  it("opens a dialog when the hamburger is clicked", async () => {
    const user = userEvent.setup();
    renderAppShell();

    // No dialog present initially.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const hamburger = screen.getByRole("button", { name: /open navigation/i });
    await user.click(hamburger);

    // Sheet portal renders the dialog into document.body.
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    // Mobile sidebar marker for our field-mode CSS selector.
    expect(dialog.getAttribute("data-mobile-sidebar")).toBe("");
  });

  it("dialog announces sr-only title and description for screen readers", async () => {
    const user = userEvent.setup();
    renderAppShell();

    await user.click(
      screen.getByRole("button", { name: /open navigation/i }),
    );
    const dialog = await screen.findByRole("dialog");

    // Radix Dialog requires labelled-by + described-by. We provide both
    // as sr-only nodes inside the Sheet content.
    expect(dialog).toHaveAttribute("aria-labelledby");
    expect(dialog).toHaveAttribute("aria-describedby");

    const title = within(dialog).getByText("Navigation");
    expect(title.className).toContain("sr-only");
  });
});

describe("AppShell — field mode", () => {
  beforeEach(() => {
    useAuth.setState({
      token: "fake-token",
      refreshToken: null,
      user: TEST_USER,
    });
  });

  it("does not set data-field by default", () => {
    const { container } = renderAppShell();
    const root = container.firstChild as HTMLElement;
    expect(root.hasAttribute("data-field")).toBe(false);
  });

  it("sets data-field=\"true\" on the root when the toggle is pressed", async () => {
    const user = userEvent.setup();
    const { container } = renderAppShell();
    const root = container.firstChild as HTMLElement;

    const toggle = screen.getByRole("button", {
      name: /enable field mode/i,
    });
    expect(toggle).toHaveAttribute("aria-pressed", "false");

    await user.click(toggle);

    expect(root.getAttribute("data-field")).toBe("true");
    // The same button now flips its label and aria-pressed for SR.
    const offToggle = screen.getByRole("button", {
      name: /disable field mode/i,
    });
    expect(offToggle).toHaveAttribute("aria-pressed", "true");
  });

  it("removes data-field when the toggle is pressed twice", async () => {
    const user = userEvent.setup();
    const { container } = renderAppShell();
    const root = container.firstChild as HTMLElement;

    await user.click(
      screen.getByRole("button", { name: /enable field mode/i }),
    );
    expect(root.getAttribute("data-field")).toBe("true");

    await user.click(
      screen.getByRole("button", { name: /disable field mode/i }),
    );
    expect(root.hasAttribute("data-field")).toBe(false);
  });
});
