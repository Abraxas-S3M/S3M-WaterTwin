/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_KEYCLOAK_URL?: string;
  readonly VITE_KEYCLOAK_REALM?: string;
  readonly VITE_KEYCLOAK_CLIENT_ID?: string;
  // Customer-branding overrides (white-label). All optional; defaults apply.
  readonly VITE_BRAND_NAME?: string;
  readonly VITE_BRAND_SUBTITLE?: string;
  readonly VITE_BRAND_LOGO_URL?: string;
  readonly VITE_BRAND_ACCENT?: string;
  readonly VITE_BRAND_ACCENT_STRONG?: string;
  readonly VITE_BRAND_ACCENT_CONTRAST?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
