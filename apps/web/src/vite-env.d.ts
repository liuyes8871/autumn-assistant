/// <reference types="vite/client" />

declare module "virtual:pwa-register" {
  export function registerSW(options?: Record<string, unknown>): (reloadPage?: boolean) => Promise<void>;
}
