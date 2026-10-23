import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

import apiBoundary from "./eslint/api-boundary-plugin.mjs";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // shadcn CLI output is never edited to satisfy lint: scope the one failing rule narrowly.
  {
    files: ["hooks/use-mobile.ts"],
    rules: { "react-hooks/set-state-in-effect": "off" },
  },
  // Every call to the Python API goes through lib/api/.
  {
    files: ["**/*.{ts,tsx,mts,mjs,js}"],
    ignores: ["lib/api/**", "lib/env.ts", "tests/**", "eslint/**", "scripts/**"],
    plugins: { "api-boundary": apiBoundary },
    rules: { "api-boundary/no-direct-api-base-url": "error" },
  },
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "api-boundary": apiBoundary },
    rules: { "api-boundary/no-client-server-api-import": "error" },
  },
  globalIgnores([
    ".next/**",
    "node_modules/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "playwright-report/**",
    "test-results/**",
    "coverage/**",
  ]),
]);

export default eslintConfig;
