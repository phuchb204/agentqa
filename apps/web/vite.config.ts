import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const apiTarget = process.env.AGENTQA_API_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": {
    target: apiTarget,
    changeOrigin: false,
    ws: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.tsx"],
    environmentOptions: {
      jsdom: { url: "http://localhost:5173/" },
    },
  },
});
