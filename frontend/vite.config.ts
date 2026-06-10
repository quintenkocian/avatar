import { defineConfig } from "vite";
import { resolve } from "node:path";

// Multi-page Vite build: the visitor page (index.html, served at /) and the
// admin page (admin.html, served at /admin). In dev, /api and /admin requests
// are proxied to the FastAPI backend on :8000 so there is no CORS to manage.
// The production build is emitted to dist/, which the backend serves as STATIC_DIR.
export default defineConfig({
  root: ".",
  publicDir: "public",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        admin: resolve(__dirname, "admin.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/admin": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // /admin (the page) is served by Vite in dev, but /admin/* data routes
        // (login, conversations, message, resolve, me, logout) must hit the API.
        bypass(req) {
          if (req.url === "/admin" || req.url === "/admin/") {
            return "/admin.html";
          }
          return undefined;
        },
      },
    },
  },
});
