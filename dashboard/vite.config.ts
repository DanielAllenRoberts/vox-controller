import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Dashboard dev server. The FastAPI bridge (CONTRACT.md) serves the built
// app in production at `/`; in dev we proxy `/api` (REST + WS) to the bridge.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
