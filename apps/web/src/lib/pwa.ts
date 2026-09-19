import { registerSW } from "virtual:pwa-register";

// Service workers are only available from a secure/http origin. The bundled
// app can still be viewed from a local file, so skip registration there rather
// than producing an avoidable console error.
export const updateSW =
  typeof window !== "undefined" && window.location.protocol !== "file:"
    ? registerSW({
        immediate: true,
        onOfflineReady() {
          window.dispatchEvent(new CustomEvent("autumn-offline-ready"));
        },
        onNeedRefresh() {
          window.dispatchEvent(new CustomEvent("autumn-update-ready"));
        }
      })
    : undefined;
