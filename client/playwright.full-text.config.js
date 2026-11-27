import path from "node:path";

import { defineConfig } from "@playwright/test";

/**
 * The whole product in text, in a real browser, against a real server with scripted vendors.
 *
 * It starts two servers of its own on spare ports, so it never touches a server you already have running:
 *   - the API on 8010, through server/scripts/run_e2e_server.py (throwaway database resolve_e2e, throwaway keys,
 *     RESOLVE_FAKE_VENDORS=1, no vendor key), and
 *   - the web app on 3010 (a Next.js dev server that writes to .next-e2e).
 * Run it with `npm run test:e2e:full-text`. It needs the Postgres container `resolve-db` (port 5434) and the server's
 * virtual environment (see ../server/README.md). Set E2E_PYTHON to use another Python for the API.
 */
const API_PORT = Number(process.env.E2E_API_PORT || 8010);
const WEB_PORT = Number(process.env.E2E_WEB_PORT || 3010);
const API = `http://127.0.0.1:${API_PORT}`;
const WEB = `http://localhost:${WEB_PORT}`;

const python =
  process.env.E2E_PYTHON ||
  (process.platform === "win32"
    ? path.resolve("..", "server", ".venv", "Scripts", "python.exe")
    : path.resolve("..", "server", ".venv", "bin", "python"));

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "full-text.spec.js",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `"${python}" "${path.resolve("..", "server", "scripts", "run_e2e_server.py")}" --port ${API_PORT} `,
      url: `${API}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { E2E_CORS_ORIGINS: `${WEB},http://127.0.0.1:${WEB_PORT}` },
    },
    {
      command: `npx next dev --port ${WEB_PORT}`,
      url: WEB,
      timeout: 180_000,
      reuseExistingServer: false,
      env: { NEXT_PUBLIC_API_URL: API, NEXT_DIST_DIR: ".next-e2e", NEXT_TELEMETRY_DISABLED: "1" },
    },
  ],
});
