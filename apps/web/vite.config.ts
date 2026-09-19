import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";
import { viteSingleFile } from "vite-plugin-singlefile";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  // Use relative asset URLs for local production builds. This keeps
  // `dist/index.html` usable when someone opens it directly from Explorer,
  // while GitHub Pages can still provide an explicit `/repo/` BASE_URL.
  const base = env.BASE_URL || "./";

  return {
    base,
    plugins: [
      react(),
      tailwindcss(),
      // Keep the production artifact usable from a local file:// URL. The
      // normal GitHub Pages deployment still serves the same app over HTTPS.
      viteSingleFile(),
      VitePWA({
        registerType: "autoUpdate",
        includeAssets: ["icon-64.png", "icon-192.png", "icon-512.png", "icon-maskable-192.png", "icon-maskable-512.png", "robots.txt"],
        manifest: {
          name: "秋招助手｜本地优先校招岗位库",
          short_name: "秋招助手",
          description: "收集官方校招岗位，记录自己的投递进度与面试日程。",
          lang: "zh-CN",
          theme_color: "#fafaf8",
          background_color: "#fafaf8",
          display: "standalone",
          start_url: ".",
          scope: ".",
          icons: [
            { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
            { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
            { src: "icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
            { src: "icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" }
          ]
        },
        workbox: {
          navigateFallback: `${base}index.html`,
          // Public job data can grow to thousands of records. Cache it on
          // demand instead of downloading every detail shard during install.
          globPatterns: ["**/*.{js,css,html,svg,png,webp,webmanifest}"],
          // Keep the user-provided source plates available in public/assets
          // for provenance, but do not precache multi-megabyte originals.
          globIgnores: ["**/*-source.png"],
          runtimeCaching: [
            {
              urlPattern: /\/data\//,
              handler: "StaleWhileRevalidate",
              options: {
                cacheName: "autumn-assistant-data",
                expiration: { maxEntries: 100, maxAgeSeconds: 60 * 60 * 24 * 30 },
                cacheableResponse: { statuses: [0, 200] }
              }
            }
          ]
        }
      })
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src")
      }
    },
    server: { host: "0.0.0.0", port: 5173 }
  };
});
