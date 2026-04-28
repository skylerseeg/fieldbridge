/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_API_PROXY_TARGET: string;
  readonly VITE_M365_TENANT_ID: string;
  readonly VITE_M365_CLIENT_ID: string;
  readonly VITE_M365_REDIRECT_URI: string;
  readonly VITE_ALLOWED_EMAIL_DOMAINS: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
