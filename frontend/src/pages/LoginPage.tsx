import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import { AlertCircle, ChevronDown, ChevronUp, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/lib/auth";
import { isMsalConfigured, loginRequest } from "@/lib/msal";

/**
 * Login page.
 *
 * Three paths, each landing on the same `setSession(...)` in `useAuth`:
 *
 *   1. Microsoft SSO         → MSAL popup → POST /auth/azure/callback
 *      (primary when VITE_AZURE_CLIENT_ID + _TENANT_ID are set)
 *   2. Email / password      → POST /auth/login
 *      (shown collapsed by default; for accounts without SSO, and for
 *       admin/service accounts that predate MSAL setup)
 *   3. Dev stub              → devLogin()
 *      (DEV builds only, hardcoded VanCon admin, no network)
 *
 * The page intentionally doesn't auto-focus the password form — SSO is
 * the paved path, the form is the escape hatch.
 */
export function LoginPage() {
  const devLogin = useAuth((s) => s.devLogin);
  const loginWithAzure = useAuth((s) => s.loginWithAzure);
  const loginWithPassword = useAuth((s) => s.loginWithPassword);
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname?: string } } | null)?.from
    ?.pathname;

  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const goHome = () => navigate(from ?? "/dashboard", { replace: true });

  const handleDevLogin = () => {
    devLogin();
    goHome();
  };

  const handlePasswordSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!email || !password) {
      setError("Email and password are required.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await loginWithPassword(email, password);
      goHome();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      const msg = detail ?? (e as Error)?.message ?? "Sign-in failed.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  // `useMsal` throws if no MsalProvider is in the tree. main.tsx only wraps
  // us with one when isMsalConfigured === true, so gate the hook call
  // behind the same flag. We can't call useMsal conditionally, so we
  // render a separate component for that branch.
  return (
    <main className="min-h-screen flex items-center justify-center bg-background p-6">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-8 shadow-sm">
        <div className="text-xl font-semibold tracking-tight">
          FieldBridge<span className="text-warning">.</span>
        </div>

        <h1 className="mt-6 text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {isMsalConfigured
            ? "Use your Microsoft account, or sign in with your FieldBridge credentials."
            : "Sign in with your FieldBridge credentials."}
        </p>

        {error && (
          <div className="mt-5 flex gap-2 rounded-md border border-critical/40 bg-critical/5 p-3 text-xs text-critical">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span className="leading-relaxed">{error}</span>
          </div>
        )}

        {isMsalConfigured && (
          <MicrosoftSignIn
            onError={setError}
            onBusy={setSubmitting}
            busy={submitting}
            onSuccess={async (idToken) => {
              try {
                await loginWithAzure(idToken);
                goHome();
              } catch (e: unknown) {
                const msg =
                  (e as { response?: { data?: { detail?: string } } })
                    ?.response?.data?.detail ??
                  (e as Error)?.message ??
                  "Sign-in failed.";
                setError(msg);
              } finally {
                setSubmitting(false);
              }
            }}
          />
        )}

        {/* Email / password — collapsed by default when SSO is available,
            expanded by default when SSO isn't configured. */}
        <div className={isMsalConfigured ? "mt-6" : "mt-4"}>
          {isMsalConfigured && (
            <div className="my-4 flex items-center gap-3">
              <Separator className="flex-1" />
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                or
              </span>
              <Separator className="flex-1" />
            </div>
          )}

          {isMsalConfigured && !showPasswordForm && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-full gap-1 text-muted-foreground hover:text-foreground"
              onClick={() => setShowPasswordForm(true)}
            >
              <ChevronDown className="h-4 w-4" />
              Use email & password
            </Button>
          )}

          {(showPasswordForm || !isMsalConfigured) && (
            <form onSubmit={handlePasswordSubmit} className="space-y-3">
              <div className="space-y-1.5">
                <label
                  htmlFor="email"
                  className="text-xs font-medium text-muted-foreground"
                >
                  Email
                </label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={submitting}
                  placeholder="you@company.com"
                />
              </div>
              <div className="space-y-1.5">
                <label
                  htmlFor="password"
                  className="text-xs font-medium text-muted-foreground"
                >
                  Password
                </label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                />
              </div>
              <Button
                type="submit"
                size="lg"
                className="w-full"
                disabled={submitting}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Sign in"
                )}
              </Button>
              {isMsalConfigured && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full gap-1 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setShowPasswordForm(false);
                    setError(null);
                  }}
                  disabled={submitting}
                >
                  <ChevronUp className="h-4 w-4" />
                  Hide
                </Button>
              )}
            </form>
          )}
        </div>

        {import.meta.env.DEV && (
          <>
            <div className="my-6 flex items-center gap-3">
              <Separator className="flex-1" />
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Dev only
              </span>
              <Separator className="flex-1" />
            </div>
            <Button
              type="button"
              variant="accent"
              size="lg"
              className="w-full"
              onClick={handleDevLogin}
              disabled={submitting}
            >
              Continue as dev user (sseegmiller@wedigutah.com)
            </Button>
            <p className="mt-3 text-xs text-muted-foreground">
              Dev stub only. No credentials transmitted. Clears on logout.
            </p>
          </>
        )}
      </div>
    </main>
  );
}

/**
 * Extracted so `useMsal()` is only called when an MsalProvider exists in
 * the tree. Same reason the parent gates rendering on `isMsalConfigured`.
 */
function MicrosoftSignIn({
  onSuccess,
  onError,
  onBusy,
  busy,
}: {
  onSuccess: (idToken: string) => Promise<void> | void;
  onError: (msg: string) => void;
  onBusy: (busy: boolean) => void;
  busy: boolean;
}) {
  const { instance, inProgress } = useMsal();
  const disabled = busy || inProgress !== InteractionStatus.None;

  const handleClick = async () => {
    onError("");
    onBusy(true);
    try {
      const result = await instance.loginPopup(loginRequest);
      if (!result.idToken) {
        throw new Error("Microsoft returned no id_token.");
      }
      await onSuccess(result.idToken);
    } catch (e: unknown) {
      const msg = (e as Error)?.message ?? "Microsoft sign-in was cancelled.";
      onError(msg);
      onBusy(false);
    }
  };

  return (
    <Button
      type="button"
      variant="outline"
      size="lg"
      className="mt-6 w-full gap-2"
      onClick={handleClick}
      disabled={disabled}
    >
      {disabled ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <MicrosoftLogo className="h-4 w-4" />
      )}
      Sign in with Microsoft
    </Button>
  );
}

/** Official four-square Microsoft logo as inline SVG. No extra deps. */
function MicrosoftLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="1" y="1" width="10" height="10" fill="#F25022" />
      <rect x="13" y="1" width="10" height="10" fill="#7FBA00" />
      <rect x="1" y="13" width="10" height="10" fill="#00A4EF" />
      <rect x="13" y="13" width="10" height="10" fill="#FFB900" />
    </svg>
  );
}
