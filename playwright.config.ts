import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testIgnore: ["**/*-real.spec.ts", "**/*.real.spec.ts", "**/real_provider/**"],
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 45000,
  workers: 1,
  reporter: "list",
  outputDir: "artifacts/playwright",
});
