import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The app is built straight into ../web, which is the directory the FastAPI
 * server already mounts as static files. That keeps deployment to one command:
 * `npm run build` produces a served SPA, and the built assets are committed so
 * a Kaggle notebook can clone + run without needing a node toolchain.
 */
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../web",
    emptyOutDir: false,
    sourcemap: false,
    target: "es2020",
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/app.[ext]",
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/ws": { target: "ws://127.0.0.1:8000", ws: true } },
  },
});
