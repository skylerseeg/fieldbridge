import {
  PublicClientApplication,
  type Configuration,
  type RedirectRequest,
} from "@azure/msal-browser";

/**
 * MSAL (Microsoft Authentication Library) configuration.
 *
 * How the SSO flow works for FieldBridge:
 *   1. User clicks "Sign in with Microsoft" → MSAL opens a popup against
 *      login.microsoftonline.com/{AZURE_TENANT_ID}.
 *   2. Azure AD authenticates and redirects back with an ID token whose
 *      audience is our SPA app registration (AZURE_CLIENT_ID).
 *   3. The SPA POSTs that raw id_token to /api/v1/auth/azure/callback.
 *   4. The backend verifies signature + iss + aud + tid against JWKS,
 *      looks up the FieldBridge user by email, and returns
 *      {access_token, refresh_token}.
 *   5. We hand both to useAuth().setSession() and navigate to /dashboard.
 *
 * Required env vars (Vite-prefixed so they ship to the browser):
 *   VITE_AZURE_CLIENT_ID   SPA app registration client ID (Azure portal →
 *                          App registrations → Overview → Application (client) ID)
 *   VITE_AZURE_TENANT_ID   Customer directory tenant ID (same page →
 *                          Directory (tenant) ID). Scopes login to that
 *                          specific tenant so an arbitrary Microsoft user
 *                          cannot sign in.
 *   VITE_AZURE_REDIRECT_URI  optional; defaults to window.location.origin.
 *                          Must match a "Single-page application" redirect
 *                          URI registered on the Azure app.
 *
 * The matching backend env vars live in fieldbridge/.env:
 *   AZURE_TENANT_ID, AZURE_CLIENT_ID (see backend/app/core/config.py).
 * Keep client-id and tenant-id identical on both sides.
 */

const clientId = import.meta.env.VITE_AZURE_CLIENT_ID as string | undefined;
const tenantId = import.meta.env.VITE_AZURE_TENANT_ID as string | undefined;
const redirectUri =
  (import.meta.env.VITE_AZURE_REDIRECT_URI as string | undefined) ??
  (typeof window !== "undefined" ? window.location.origin : undefined);

/**
 * True when both client-id and tenant-id are configured. When false, the
 * LoginPage hides the "Sign in with Microsoft" button and falls back to the
 * dev stub (DEV builds only) or email/password (Commit 4).
 *
 * This lets a developer run the SPA locally without needing Azure creds —
 * they just click "Continue as dev user" on the login page.
 */
export const isMsalConfigured = Boolean(clientId && tenantId);

export const msalConfig: Configuration = {
  auth: {
    clientId: clientId ?? "00000000-0000-0000-0000-000000000000",
    authority: tenantId
      ? `https://login.microsoftonline.com/${tenantId}`
      : "https://login.microsoftonline.com/common",
    redirectUri: redirectUri ?? "/",
    postLogoutRedirectUri: "/login",
    // Important: do NOT use navigateToLoginRequestUrl. Our router handles
    // the post-login hop; MSAL's redirect-navigation logic conflicts with
    // React Router state.
    navigateToLoginRequestUrl: false,
  },
  cache: {
    // localStorage persists across tabs + reloads. Fine for a desktop-only
    // dashboard; revisit if we ship a mobile PWA (sessionStorage is safer
    // on shared devices).
    cacheLocation: "localStorage",
    storeAuthStateInCookie: false,
  },
};

/**
 * Lazily constructed so a missing env config doesn't crash the whole SPA
 * on import. Consumers must guard with `isMsalConfigured` first.
 */
let _msalInstance: PublicClientApplication | null = null;
export function getMsalInstance(): PublicClientApplication {
  if (!_msalInstance) {
    _msalInstance = new PublicClientApplication(msalConfig);
  }
  return _msalInstance;
}

/**
 * Scopes requested at interactive login. `openid profile email` are all we
 * need for ID-token-based auth; we don't call Microsoft Graph directly from
 * the SPA (any Graph calls happen server-side via the per-tenant service
 * principal — see backend/app/services/email_bridge/).
 */
export const loginRequest: RedirectRequest = {
  scopes: ["openid", "profile", "email"],
};
