import axios from "axios";
import { create } from "zustand";

/**
 * Auth store.
 *
 * Three login paths land on the same `setSession(accessToken, refreshToken, user)`:
 *   - devLogin()           hardcoded VanCon admin, DEV builds only.
 *   - loginWithAzure()     exchanges an Azure AD ID token for FieldBridge tokens
 *                          via POST /api/v1/auth/azure/callback.
 *   - loginWithPassword()  email/password → POST /api/v1/auth/login.
 *
 * The shape stays stable across those paths so consuming components
 * (Topbar user chip, Sidebar tenant chip, RequireAuth gate) never need
 * to branch on how the session was created.
 */

export interface AuthUser {
  id: string;
  email: string;
  role: string;
  tenant: {
    id: string;
    name: string;
    slug: string;
  };
  department?: string; // populated once User.department lands on the backend
}

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: AuthUser | null;

  /** Call on any successful login path. */
  setSession: (
    accessToken: string,
    refreshToken: string | null,
    user: AuthUser,
  ) => void;

  /** Clear everything. Caller is responsible for navigating to /login. */
  logout: () => void;

  /** Dev-only: log in as the seeded VanCon admin without hitting the API. */
  devLogin: () => void;

  /**
   * Azure SSO path: POST the MSAL-issued id_token to the backend and store
   * whatever FieldBridge session it mints. Throws on 401/403 — callers
   * (LoginPage) surface the message to the user.
   */
  loginWithAzure: (idToken: string) => Promise<void>;

  /**
   * Email/password path: POST to /auth/login and store the returned
   * FieldBridge session. Throws on 401/403 — callers (LoginPage) surface
   * `response.data.detail` to the user.
   */
  loginWithPassword: (email: string, password: string) => Promise<void>;
}

const DEV_USER: AuthUser = {
  id: "dev-user",
  email: "sseegmiller@wedigutah.com",
  role: "Admin",
  tenant: {
    id: "dev-tenant",
    name: "VanCon Inc.",
    slug: "vancon",
  },
  department: "Ops",
};

const loadInitial = (): Pick<AuthState, "token" | "refreshToken" | "user"> => {
  try {
    const token = localStorage.getItem("fb_token");
    const refreshToken = localStorage.getItem("fb_refresh");
    const userRaw = localStorage.getItem("fb_user");
    const user = userRaw ? (JSON.parse(userRaw) as AuthUser) : null;
    return { token, refreshToken, user };
  } catch {
    return { token: null, refreshToken: null, user: null };
  }
};

const API_PREFIX = "/api/v1";

/**
 * Shape returned by /auth/login, /auth/refresh, and /auth/azure/callback.
 * See backend/app/api/v1/endpoints/auth.py :: TokenResponse.
 */
interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  tenant_id: string;
  tenant_slug: string;
  user_id: string;
  role: string;
}

/**
 * Shared tail for every non-dev login path: persist the TokenResponse, mint
 * a sparse AuthUser so the UI can render immediately, then fetch /auth/me
 * for company_name + email and overwrite the sparse user. A /me failure
 * isn't fatal — we keep the sparse session so the user still gets in.
 *
 * `set` is the zustand setter threaded through from create().
 */
async function finalizeLogin(
  data: TokenResponse,
  set: (partial: Partial<AuthState>) => void,
): Promise<void> {
  const sparseUser: AuthUser = {
    id: data.user_id,
    email: "", // overwritten below
    role: data.role,
    tenant: {
      id: data.tenant_id,
      name: "", // overwritten below
      slug: data.tenant_slug,
    },
  };

  localStorage.setItem("fb_token", data.access_token);
  localStorage.setItem("fb_refresh", data.refresh_token);
  localStorage.setItem("fb_user", JSON.stringify(sparseUser));
  set({
    token: data.access_token,
    refreshToken: data.refresh_token,
    user: sparseUser,
  });

  try {
    const me = await axios.get(
      (import.meta.env.VITE_API_URL || "") + `${API_PREFIX}/auth/me`,
      {
        headers: {
          Authorization: `Bearer ${data.access_token}`,
          "Content-Type": "application/json",
        },
        timeout: 10_000,
      },
    );
    const hydrated: AuthUser = {
      id: me.data.user_id,
      email: me.data.email,
      role: me.data.role,
      tenant: {
        id: me.data.tenant_id,
        name: me.data.company_name,
        slug: me.data.tenant_slug,
      },
    };
    localStorage.setItem("fb_user", JSON.stringify(hydrated));
    set({ user: hydrated });
  } catch {
    // Leave the sparse user in place.
  }
}

export const useAuth = create<AuthState>((set) => ({
  ...loadInitial(),

  setSession: (accessToken, refreshToken, user) => {
    localStorage.setItem("fb_token", accessToken);
    if (refreshToken) {
      localStorage.setItem("fb_refresh", refreshToken);
    } else {
      localStorage.removeItem("fb_refresh");
    }
    localStorage.setItem("fb_user", JSON.stringify(user));
    set({ token: accessToken, refreshToken, user });
  },

  logout: () => {
    localStorage.removeItem("fb_token");
    localStorage.removeItem("fb_refresh");
    localStorage.removeItem("fb_user");
    set({ token: null, refreshToken: null, user: null });
  },

  devLogin: () => {
    const token = "dev-token-" + Math.random().toString(36).slice(2);
    localStorage.setItem("fb_token", token);
    localStorage.setItem("fb_user", JSON.stringify(DEV_USER));
    set({ token, refreshToken: null, user: DEV_USER });
  },

  loginWithAzure: async (idToken: string) => {
    // Raw axios — NOT the shared `api` instance — because `api` has a
    // response interceptor that would try to refresh on 401. There's
    // nothing to refresh here; a 401 means the token is invalid.
    const { data } = await axios.post<TokenResponse>(
      (import.meta.env.VITE_API_URL || "") + `${API_PREFIX}/auth/azure/callback`,
      { id_token: idToken },
      { headers: { "Content-Type": "application/json" }, timeout: 20_000 },
    );
    await finalizeLogin(data, set);
  },

  loginWithPassword: async (email: string, password: string) => {
    // Same reasoning as loginWithAzure: raw axios so a 401 here surfaces
    // "Invalid email or password" to the form instead of kicking off a
    // refresh loop.
    const { data } = await axios.post<TokenResponse>(
      (import.meta.env.VITE_API_URL || "") + `${API_PREFIX}/auth/login`,
      { email, password },
      { headers: { "Content-Type": "application/json" }, timeout: 15_000 },
    );
    await finalizeLogin(data, set);
  },
}));
