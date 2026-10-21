// Full-page results screenshots for every persona: Welcome -> Prefill as persona -> Jump to results.
// Needs the engine on :8000 and the web app on :3000, and a local Chrome (no browser download).
//   npm run screenshots              # all personas into ../docs/screenshots/
//   npm run screenshots -- maya      # just one

import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const BASE = process.env.WEB_URL ?? "http://localhost:3000";
const OUT = fileURLToPath(new URL("../../docs/screenshots/", import.meta.url));
const PERSONAS = [
  "maya",
  "novice_recomp",
  "marathon_fatloss",
  "wedding_8wk",
  "hybrid",
  "glp1_t2d_strength",
  "vegan_muscle",
  "under18",
  "pregnant",
  "goal_bmi_low",
];

const only = process.argv.slice(2);
await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 480, height: 900 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

for (const name of only.length ? only : PERSONAS) {
  await page.goto(`${BASE}/onboarding/welcome`);
  await page.getByText("Prefill as persona…").click();
  const row = page.locator("li", { hasText: name.replaceAll("_", " ") }).first();
  await row.getByRole("button", { name: "Jump to results" }).click();
  await page.waitForURL("**/results", { timeout: 15_000 });
  await page.getByText("Developer drawer").waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}${name}.png`, fullPage: true });
  console.log(`${name}: ${await page.locator("h1:visible").innerText()}`);
}

await browser.close();
if (errors.length) {
  console.error("console errors:\n" + errors.join("\n"));
  process.exitCode = 1;
}
