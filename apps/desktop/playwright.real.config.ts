import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'../../tests/e2e',testMatch:'**/vertical-real.spec.ts',testIgnore:[],forbidOnly:true,retries:0,workers:1,timeout:480000,reporter:'list',outputDir:'../../artifacts/playwright-real'});
