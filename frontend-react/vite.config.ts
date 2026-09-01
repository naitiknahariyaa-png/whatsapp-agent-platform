import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/auth": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/alerts": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/weekly_report": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/reengagement": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
  },
});