import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

const proxyTarget = process.env.PANEL_PROXY || "http://127.0.0.1:3000";
const proxied = ["/api", "/oauth", "/ws", "/uploads", "/logs", "/audit"];

export default defineConfig({
  plugins: [preact()],
  base: "/",
  build: {
    outDir: "../app/core/webpanel/dist",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      proxied.map((p) => [p, { target: proxyTarget, changeOrigin: true, ws: true }]),
    ),
  },
});
