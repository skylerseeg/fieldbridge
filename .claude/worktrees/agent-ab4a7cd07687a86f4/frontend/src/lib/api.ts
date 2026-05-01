import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

import { useAuth } from "@/lib/auth";

/**
 * Single axios instance shared by every module's data hooks.
 *
 * Dev:  requests to /api/* are proxied by vite.config.ts to the FastAPI
 *       backend (VITE_API_PROXY_TARGET, default http://localhost:8000).
 *       baseURL can stay empty — the browser resolves /api/* against the
 *       Vite dev-server origin.
 * Prod: set VITE_API_URL to the backend origin (e.g.
 *       https://api.fieldbridge.com). The interceptor attaches the
 *       JWT from localStorage on every request.
 *
 * Commit 3 adds refresh-on-401. Flow:
 *   - Request interceptor attaches current `fb_token`.
 *   - Response interceptor: on 401, call POST /auth/refresh with `fb_refresh`.
 *     If that succeeds, swap in the new tokens and retry the original.
 *     If it fails, clear auth state and bounce to /login.
 *   - Concurrent 401s coalesce into a single refresh call via `refreshPromise`.
 */

// `baseURL=""` means axios leaves the URL alone: "/api/v1/foo" → "/api/v1/foo".
// That's what we want in dev, because Vite's proxy rewrites /api. In prod we
// point VITE_API_URL at the deployed backend.
export const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "",
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

const API_PREFIX = "/api/v1";

// ── request: attach access token ─────────────────────────────────────────
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("fb_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── response: refresh-or-logout on 401 ───────────────────────────────────

interface RetriableRequest extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

/**
 * Single in-flight refresh promise. If two concurrent requests both get 401,
 * the second one awaits the same /auth/refresh call instead of firing a
 * duplicate.
 */
let refreshPromise: Promise<string | null> | null = null;

/**
 * POSTs /auth/refresh with the stored refresh token. On success writes the
 * new access + refresh tokens to localStorage AND synchronizes the Zustand
 * store, and returns the new access token. On failure returns null.
 *
 * Uses a raw axios call (not `api`) to avoid re-triggering this interceptor
 * if the refresh itself 401s.
 */
async function doRefresh(): Promise<string | null> {
  const refreshToken = localStorage.getItem("fb_refresh");
  if (!refreshToken) return null;

  try {
    const { data } = await axios.post(
      (import.meta.env.VITE_API_URL || "") + `${API_PREFIX}/auth/refresh`,
      { refresh_token: refreshToken },
      { headers: { "Content-Type": "application/json" }, timeout: 15_000 },
    );

    // Backend returns the standard TokenResponse shape (see
    // fieldbridge/backend/app/api/v1/endpoints/auth.py).
    const newAccess = data.access_token as string;
    const newRefresh = data.refresh_token as string;

    localStorage.setItem("fb_token", newAccess);
    localStorage.setItem("fb_refresh", newRefresh);

    // Mirror into Zustand so components re-render with the fresh token.
    // `auth.ts` uses raw axios (not this `api` instance), so importing it
    // statically at the top of the file doesn't create a runtime cycle.
    const state = useAuth.getState();
    if (state.user) {
      state.setSession(newAccess, newRefresh, state.user);
    }

    return newAccess;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetriableRequest | undefined;
    const status = error.response?.status;
    const url = original?.url ?? "";

    // Bail out if there's no recoverable context, or if THIS request was
    // already a retry, or if the 401 was on /auth/refresh itself (which
    // means the refresh token is dead).
    const isRefreshCall = url.includes(`${API_PREFIX}/auth/refresh`);
    if (
      !original ||
      status !== 401 ||
      original._retry ||
      isRefreshCall
    ) {
      return Promise.reject(error);
    }

    original._retry = true;

    // Coalesce concurrent refreshes into one call
    if (!refreshPromise) {
      refreshPromise = doRefresh().finally(() => {
        refreshPromise = null;
      });
    }
    const newToken = await refreshPromise;

    if (newToken) {
      // `InternalAxiosRequestConfig.headers` is always an AxiosHeaders
      // instance, so we can mutate it directly.
      original.headers.Authorization = `Bearer ${newToken}`;
      return api(original);
    }

    // Refresh failed — terminate the session.
    useAuth.getState().logout();
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);
