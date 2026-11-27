import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  // The full text walk starts its own servers; run it with `npm run test:e2e:full-text`.
  testIgnore: "**/full-text.spec.js",
  use: {
    baseURL: "http://localhost:3000",
  },
});
