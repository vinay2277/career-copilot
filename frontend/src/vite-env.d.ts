/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin. Empty in dev — vite proxies /api to :8000. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
