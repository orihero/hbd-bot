/**
 * Master Test Runner for Admin Dashboard Multilingual Localization E2E Suite
 * 
 * Executes all 4 tiers:
 * - Tier 1: Feature Coverage (F1 to F18)
 * - Tier 2: Boundary & Corner Cases
 * - Tier 3: Cross-Feature Pairwise Interactions
 * - Tier 4: Real-World Operator Workflows
 * 
 * Generates formatted CLI summary and sets exit codes.
 */

import { runTier1Tests } from "./tier1-features.test.js";
import { runTier2Tests } from "./tier2-boundaries.test.js";
import { runTier3Tests } from "./tier3-pairwise.test.js";
import { runTier4Tests } from "./tier4-scenarios.test.js";
import { type TestCaseResult, type SuiteResult } from "./harness.js";

async function runSuite(name: string, runner: () => Promise<TestCaseResult[]>): Promise<SuiteResult> {
  const start = performance.now();
  const results = await runner();
  const totalDurationMs = Math.round((performance.now() - start) * 100) / 100;

  const passed = results.filter((r) => r.status === "PASS").length;
  const failed = results.filter((r) => r.status === "FAIL").length;
  const pending = results.filter((r) => r.status === "PENDING_IMPLEMENTATION").length;

  return { suiteName: name, results, passed, failed, pending, totalDurationMs };
}

function formatStatus(status: TestCaseResult["status"]): string {
  switch (status) {
    case "PASS":
      return "\x1b[32m✔ PASS\x1b[0m";
    case "FAIL":
      return "\x1b[31m✖ FAIL\x1b[0m";
    case "PENDING_IMPLEMENTATION":
      return "\x1b[33m⏳ PENDING\x1b[0m";
  }
}

export async function runAll(): Promise<void> {
  console.log("\n" + "=".repeat(80));
  console.log("  ADMIN DASHBOARD MULTILINGUAL LOCALIZATION (UZ, RU, EN) E2E SUITE");
  console.log("=".repeat(80) + "\n");

  const suites: SuiteResult[] = [];

  suites.push(await runSuite("Tier 1: Feature Coverage", runTier1Tests));
  suites.push(await runSuite("Tier 2: Boundary & Corner Cases", runTier2Tests));
  suites.push(await runSuite("Tier 3: Cross-Feature Pairwise Coverage", runTier3Tests));
  suites.push(await runSuite("Tier 4: Real-World Operator Workflows", runTier4Tests));

  let totalPassed = 0;
  let totalFailed = 0;
  let totalPending = 0;
  let grandTotalTime = 0;

  for (const s of suites) {
    console.log(`\n\x1b[1m=== ${s.suiteName} (${s.results.length} tests) ===\x1b[0m`);
    for (const r of s.results) {
      const statusStr = formatStatus(r.status);
      const durationStr = `\x1b[90m(${r.durationMs}ms)\x1b[0m`;
      console.log(`  [${r.id}] ${statusStr} ${r.name} ${durationStr}`);
      if (r.status === "FAIL" && r.error) {
        console.log(`       \x1b[31mError: ${r.error.message}\x1b[0m`);
      } else if (r.status === "PENDING_IMPLEMENTATION" && r.error) {
        console.log(`       \x1b[33mPending: ${r.error.message}\x1b[0m`);
      }
    }
    totalPassed += s.passed;
    totalFailed += s.failed;
    totalPending += s.pending;
    grandTotalTime += s.totalDurationMs;
  }

  const grandTotal = totalPassed + totalFailed + totalPending;

  console.log("\n" + "=".repeat(80));
  console.log("  EXECUTION SUMMARY");
  console.log("=".repeat(80));
  console.log(`  Total Tests Run:     ${grandTotal}`);
  console.log(`  \x1b[32mPassed:\x1b[0m              ${totalPassed}`);
  console.log(`  \x1b[31mFailed:\x1b[0m              ${totalFailed}`);
  console.log(`  \x1b[33mPending (M1-M4):\x1b[0m    ${totalPending}`);
  console.log(`  Total Execution Time: ${Math.round(grandTotalTime * 100) / 100}ms`);
  console.log("=".repeat(80) + "\n");

  const isStrict = process.argv.includes("--strict") || process.env.STRICT_TESTS === "true";

  if (totalFailed > 0) {
    console.error(`\x1b[31mE2E Suite Failed with ${totalFailed} defect(s).\x1b[0m\n`);
    process.exit(1);
  } else if (isStrict && totalPending > 0) {
    console.error(`\x1b[33mStrict mode: ${totalPending} test(s) pending implementation.\x1b[0m\n`);
    process.exit(1);
  } else {
    console.log(`\x1b[32mE2E Test Harness executed cleanly.\x1b[0m\n`);
    process.exit(0);
  }
}

// Auto-run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  void runAll();
}
