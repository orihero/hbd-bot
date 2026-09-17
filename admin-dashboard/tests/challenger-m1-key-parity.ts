/**
 * Adversarial Key Parity and Dynamic Token Consistency Test Harness
 * 
 * Challenger 1 (Milestone M1 Iteration 2)
 * Focus:
 * 1. 100% key parity across all 526 keys (en, ru, uz)
 * 2. Exact dynamic parameter token consistency across all 3 languages
 * 3. Specific validation of {calls}, {costed}, {delivered}, {attributed}
 * 4. Exhaustive interpolation oracle across all parameter-bearing keys
 * 5. Stress testing interpolation engine with boundary, injection, and prototype pollution inputs
 */

import { en } from "../src/i18n/locales/en.js";
import { ru } from "../src/i18n/locales/ru.js";
import { uz } from "../src/i18n/locales/uz.js";
import { t, setLocale, getLocale, interpolate } from "../src/i18n/index.js";

interface TestResult {
  name: string;
  passed: boolean;
  details?: string;
  error?: string;
}

const results: TestResult[] = [];

function record(name: string, passed: boolean, details?: string, error?: string) {
  results.push({ name, passed, details, error });
  const symbol = passed ? "\x1b[32m✔ PASS\x1b[0m" : "\x1b[31m✖ FAIL\x1b[0m";
  console.log(`  ${symbol} ${name}`);
  if (details) {
    console.log(`       \x1b[90m${details}\x1b[0m`);
  }
  if (error) {
    console.log(`       \x1b[31m${error}\x1b[0m`);
  }
}

// Helper: Flatten nested object into dot-notation map of leaf paths -> string values
function flattenKeys(obj: Record<string, any>, prefix = ""): Map<string, string> {
  const map = new Map<string, string>();
  for (const [k, v] of Object.entries(obj)) {
    const fullPath = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "object" && v !== null && !Array.isArray(v)) {
      const nested = flattenKeys(v, fullPath);
      for (const [nk, nv] of nested.entries()) {
        map.set(nk, nv);
      }
    } else if (typeof v === "string") {
      map.set(fullPath, v);
    } else {
      throw new Error(`Unexpected non-string leaf at ${fullPath}: ${typeof v}`);
    }
  }
  return map;
}

// Helper: Extract parameter tokens from a template string
function extractTokens(template: string): Set<string> {
  const matches = template.match(/\{([a-zA-Z0-9_]+)\}/g) || [];
  return new Set(matches.map((m) => m.slice(1, -1)));
}

// Helper: Detect malformed token patterns (e.g. unclosed '{', empty '{}', whitespace inside '{ }')
function detectMalformedTokens(template: string): string[] {
  const issues: string[] = [];
  const emptyBraces = template.match(/\{\s*\}/g);
  if (emptyBraces) issues.push(`Empty braces: ${emptyBraces.join(", ")}`);
  
  // Braces with unexpected whitespace
  const spaceTokens = template.match(/\{ +[a-zA-Z0-9_]+ *\}|\{ *[a-zA-Z0-9_]+ +\}/g);
  if (spaceTokens) issues.push(`Whitespace in tokens: ${spaceTokens.join(", ")}`);

  // Unbalanced braces
  const openCount = (template.match(/\{/g) || []).length;
  const closeCount = (template.match(/\}/g) || []).length;
  if (openCount !== closeCount) {
    issues.push(`Mismatched brace counts: ${openCount} '{' vs ${closeCount} '}'`);
  }

  return issues;
}

export function runKeyParityAdversarialTests(): boolean {
  console.log("\n" + "=".repeat(80));
  console.log("  CHALLENGER 1: ADVERSARIAL KEY PARITY & DYNAMIC TOKEN VERIFICATION");
  console.log("=".repeat(80) + "\n");

  const enMap = flattenKeys(en);
  const ruMap = flattenKeys(ru);
  const uzMap = flattenKeys(uz);

  console.log(`  Discovered Leaf Keys: EN=${enMap.size}, RU=${ruMap.size}, UZ=${uzMap.size}\n`);

  // ---------------------------------------------------------------------------
  // TEST 1: The three catalogues hold the SAME number of keys
  // ---------------------------------------------------------------------------
  //
  // This asserted a literal 526 — the count on the day M1 landed. A catalogue grows every
  // time a screen is wired, so a frozen total makes the suite fail for the one reason that is
  // not a defect, and the only fix anybody would reach for is editing the number. What has to
  // hold is that the three move TOGETHER, and that neither of them is empty.
  const counts = { en: enMap.size, ru: ruMap.size, uz: uzMap.size };
  const countMatches =
    enMap.size > 0 && enMap.size === ruMap.size && enMap.size === uzMap.size;
  record(
    "All 3 languages hold the same number of keys",
    countMatches,
    `EN: ${counts.en}, RU: ${counts.ru}, UZ: ${counts.uz}`,
    countMatches ? undefined : "The three catalogues have drifted apart."
  );

  // ---------------------------------------------------------------------------
  // TEST 2: Bidirectional Key Parity & Symmetry (EN vs RU)
  // ---------------------------------------------------------------------------
  const missingInRu = [...enMap.keys()].filter((k) => !ruMap.has(k));
  const extraInRu = [...ruMap.keys()].filter((k) => !enMap.has(k));
  const ruParity = missingInRu.length === 0 && extraInRu.length === 0;
  record(
    "100% bidirectional key symmetry between EN and RU",
    ruParity,
    `Missing in RU: ${missingInRu.length}, Extra in RU: ${extraInRu.length}`,
    ruParity ? undefined : `Missing: ${missingInRu.join(", ")}; Extra: ${extraInRu.join(", ")}`
  );

  // ---------------------------------------------------------------------------
  // TEST 3: Bidirectional Key Parity & Symmetry (EN vs UZ)
  // ---------------------------------------------------------------------------
  const missingInUz = [...enMap.keys()].filter((k) => !uzMap.has(k));
  const extraInUz = [...uzMap.keys()].filter((k) => !enMap.has(k));
  const uzParity = missingInUz.length === 0 && extraInUz.length === 0;
  record(
    "100% bidirectional key symmetry between EN and UZ",
    uzParity,
    `Missing in UZ: ${missingInUz.length}, Extra in UZ: ${extraInUz.length}`,
    uzParity ? undefined : `Missing: ${missingInUz.join(", ")}; Extra: ${extraInUz.join(", ")}`
  );

  // ---------------------------------------------------------------------------
  // TEST 4: Non-Empty Value and Type Safety Across All Keys
  // ---------------------------------------------------------------------------
  const emptyKeys: string[] = [];
  for (const [k, v] of enMap.entries()) {
    if (!v || v.trim().length === 0) emptyKeys.push(`EN:${k}`);
  }
  for (const [k, v] of ruMap.entries()) {
    if (!v || v.trim().length === 0) emptyKeys.push(`RU:${k}`);
  }
  for (const [k, v] of uzMap.entries()) {
    if (!v || v.trim().length === 0) emptyKeys.push(`UZ:${k}`);
  }
  record(
    "Every key in all 3 locales holds a non-empty string",
    emptyKeys.length === 0,
    `Scanned 3 × ${counts.en} = ${3 * counts.en} total leaf strings`,
    emptyKeys.length === 0 ? undefined : `Empty keys found: ${emptyKeys.join(", ")}`
  );

  // ---------------------------------------------------------------------------
  // TEST 5: Malformed Token Syntax Check
  // ---------------------------------------------------------------------------
  const malformed: Array<{ locale: string; key: string; issue: string }> = [];
  for (const [k, v] of enMap.entries()) {
    for (const issue of detectMalformedTokens(v)) malformed.push({ locale: "EN", key: k, issue });
  }
  for (const [k, v] of ruMap.entries()) {
    for (const issue of detectMalformedTokens(v)) malformed.push({ locale: "RU", key: k, issue });
  }
  for (const [k, v] of uzMap.entries()) {
    for (const issue of detectMalformedTokens(v)) malformed.push({ locale: "UZ", key: k, issue });
  }
  record(
    "No malformed tokens, unclosed braces, or brace syntax errors across any locale",
    malformed.length === 0,
    `Inspected all tokens across EN, RU, UZ`,
    malformed.length === 0 ? undefined : `Issues: ${JSON.stringify(malformed)}`
  );

  // ---------------------------------------------------------------------------
  // TEST 6: Dynamic Token Consistency Across All 526 Keys
  // ---------------------------------------------------------------------------
  const tokenMismatches: Array<{
    key: string;
    enTokens: string[];
    ruTokens: string[];
    uzTokens: string[];
    discrepancy: string;
  }> = [];

  let dynamicKeyCount = 0;

  for (const key of enMap.keys()) {
    const enTokens = extractTokens(enMap.get(key)!);
    const ruTokens = extractTokens(ruMap.get(key) || "");
    const uzTokens = extractTokens(uzMap.get(key) || "");

    if (enTokens.size > 0 || ruTokens.size > 0 || uzTokens.size > 0) {
      dynamicKeyCount++;
      const enArr = [...enTokens].sort();
      const ruArr = [...ruTokens].sort();
      const uzArr = [...uzTokens].sort();

      const enStr = enArr.join(",");
      const ruStr = ruArr.join(",");
      const uzStr = uzArr.join(",");

      if (enStr !== ruStr || enStr !== uzStr) {
        tokenMismatches.push({
          key,
          enTokens: enArr,
          ruTokens: ruArr,
          uzTokens: uzArr,
          discrepancy: `EN=[${enStr}], RU=[${ruStr}], UZ=[${uzStr}]`,
        });
      }
    }
  }

  record(
    `Dynamic token consistency is strictly 100% across all ${dynamicKeyCount} parameterized keys`,
    tokenMismatches.length === 0,
    `Verified token set equality (Set(EN) === Set(RU) === Set(UZ)) for all ${dynamicKeyCount} keys`,
    tokenMismatches.length === 0
      ? undefined
      : `Mismatched tokens: ${tokenMismatches.map((m) => `${m.key} (${m.discrepancy})`).join("; ")}`
  );

  // ---------------------------------------------------------------------------
  // TEST 7: Deep Verification of Remediated Card Caption Keys & Tokens
  // ---------------------------------------------------------------------------
  const spendKey = "dashboard.cardCaptions.spendPartialPriced";
  const cpsKey = "dashboard.cardCaptions.cpsPartialAttributed";

  const spendEn = enMap.get(spendKey);
  const spendRu = ruMap.get(spendKey);
  const spendUz = uzMap.get(spendKey);

  const cpsEn = enMap.get(cpsKey);
  const cpsRu = ruMap.get(cpsKey);
  const cpsUz = uzMap.get(cpsKey);

  const spendTokensValid =
    spendEn?.includes("{calls}") && spendEn?.includes("{costed}") &&
    spendRu?.includes("{calls}") && spendRu?.includes("{costed}") &&
    spendUz?.includes("{calls}") && spendUz?.includes("{costed}");

  const cpsTokensValid =
    cpsEn?.includes("{delivered}") && cpsEn?.includes("{attributed}") &&
    cpsRu?.includes("{delivered}") && cpsRu?.includes("{attributed}") &&
    cpsUz?.includes("{delivered}") && cpsUz?.includes("{attributed}");

  record(
    "Target key `dashboard.cardCaptions.spendPartialPriced` preserves {calls} and {costed} across EN, RU, UZ",
    Boolean(spendTokensValid),
    `EN: "${spendEn}" | RU: "${spendRu}" | UZ: "${spendUz}"`
  );

  record(
    "Target key `dashboard.cardCaptions.cpsPartialAttributed` preserves {delivered} and {attributed} across EN, RU, UZ",
    Boolean(cpsTokensValid),
    `EN: "${cpsEn}" | RU: "${cpsRu}" | UZ: "${cpsUz}"`
  );

  // ---------------------------------------------------------------------------
  // TEST 8: Empirical Interpolation Oracles for Target Keys
  // ---------------------------------------------------------------------------
  setLocale("en");
  const interpSpendEn = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: 1000, costed: 850 });
  const interpCpsEn = t("dashboard.cardCaptions.cpsPartialAttributed" as any, { delivered: 500, attributed: 480 });

  setLocale("ru");
  const interpSpendRu = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: 1000, costed: 850 });
  const interpCpsRu = t("dashboard.cardCaptions.cpsPartialAttributed" as any, { delivered: 500, attributed: 480 });

  setLocale("uz");
  const interpSpendUz = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: 1000, costed: 850 });
  const interpCpsUz = t("dashboard.cardCaptions.cpsPartialAttributed" as any, { delivered: 500, attributed: 480 });

  const spendOraclePassed =
    interpSpendEn === "850 of 1000 calls priced" &&
    interpSpendRu === "850 из 1000 вызовов тарифицированы" &&
    interpSpendUz === "1000 ta chaqiruvdan 850 tasi narxlangan";

  const cpsOraclePassed =
    interpCpsEn === "480 of 500 attributed" &&
    interpCpsRu === "480 из 500 учтены" &&
    interpCpsUz === "500 tadan 480 tasi hisoblangan";

  record(
    "Target key spendPartialPriced interpolates accurately into authentic idioms",
    spendOraclePassed,
    `EN: "${interpSpendEn}"\n       RU: "${interpSpendRu}"\n       UZ: "${interpSpendUz}"`,
    spendOraclePassed ? undefined : "Output did not match expected interpolated idiom"
  );

  record(
    "Target key cpsPartialAttributed interpolates accurately into authentic idioms",
    cpsOraclePassed,
    `EN: "${interpCpsEn}"\n       RU: "${interpCpsRu}"\n       UZ: "${interpCpsUz}"`,
    cpsOraclePassed ? undefined : "Output did not match expected interpolated idiom"
  );

  // ---------------------------------------------------------------------------
  // TEST 9: Exhaustive Interpolation Oracle across ALL Parameterized Keys
  // ---------------------------------------------------------------------------
  let totalExhaustiveTested = 0;
  const exhaustiveFailures: string[] = [];

  for (const key of enMap.keys()) {
    const tokens = extractTokens(enMap.get(key)!);
    if (tokens.size === 0) continue;

    const mockParams: Record<string, any> = {};
    for (const tok of tokens) {
      if (tok === "count" || tok === "total" || tok === "calls" || tok === "costed" || tok === "delivered" || tok === "attributed" || tok === "failed" || tok === "active" || tok === "days") {
        mockParams[tok] = 42;
      } else if (tok === "span" || tok === "period") {
        mockParams[tok] = "30d";
      } else if (tok === "name" || tok === "username") {
        mockParams[tok] = "Dilshod";
      } else if (tok === "email") {
        mockParams[tok] = "test@example.com";
      } else if (tok === "id") {
        mockParams[tok] = "usr_12345";
      } else {
        mockParams[tok] = `VAL_${tok}`;
      }
    }

    for (const loc of ["en", "ru", "uz"] as const) {
      setLocale(loc);
      const out = t(key as any, mockParams);
      totalExhaustiveTested++;
      // Check if any un-interpolated bracket tokens remain
      const remainingTokens = out.match(/\{([a-zA-Z0-9_]+)\}/g);
      if (remainingTokens) {
        exhaustiveFailures.push(`[${loc}] ${key}: remaining ${remainingTokens.join(", ")} in "${out}"`);
      }
    }
  }

  record(
    `Exhaustive parameter interpolation across all ${totalExhaustiveTested / 3} keys in all 3 languages (${totalExhaustiveTested} invocations)`,
    exhaustiveFailures.length === 0,
    `100% of dynamic tokens cleanly replaced without residual braces`,
    exhaustiveFailures.length === 0 ? undefined : `Failures: ${exhaustiveFailures.join("; ")}`
  );

  // ---------------------------------------------------------------------------
  // TEST 10: Adversarial Stress Testing — Numeric Boundaries
  // ---------------------------------------------------------------------------
  setLocale("uz");
  const zeroTest = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: 0, costed: 0 });
  const negTest = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: -10, costed: -5 });
  const floatTest = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: 12.5, costed: 8.25 });
  const bigTest = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: 1_000_000_000, costed: 999_999_999 });

  const numericStressPassed =
    zeroTest === "0 ta chaqiruvdan 0 tasi narxlangan" &&
    negTest === "-10 ta chaqiruvdan -5 tasi narxlangan" &&
    floatTest === "12.5 ta chaqiruvdan 8.25 tasi narxlangan" &&
    bigTest === "1000000000 ta chaqiruvdan 999999999 tasi narxlangan";

  record(
    "Interpolation stress: boundary numbers (0, negative, floating point, 1 billion)",
    numericStressPassed,
    `Zero: "${zeroTest}" | Neg: "${negTest}" | Float: "${floatTest}" | Big: "${bigTest}"`
  );

  // ---------------------------------------------------------------------------
  // TEST 11: Adversarial Stress Testing — Regex & Special Characters Injection
  // ---------------------------------------------------------------------------
  const regexParams = { calls: "$& $1 $` $' $", costed: "\\w+ [A-Z]* (.*)" };
  const regexOut = t("dashboard.cardCaptions.spendPartialPriced" as any, regexParams);
  const regexPassed =
    regexOut.includes("$& $1 $` $' $") &&
    regexOut.includes("\\w+ [A-Z]* (.*)") &&
    !regexOut.includes("undefined");

  record(
    "Interpolation stress: regex metacharacters ($&, $1, $`, $', $, \\w+) treated as raw text",
    regexPassed,
    `Output: "${regexOut}"`
  );

  // ---------------------------------------------------------------------------
  // TEST 12: Adversarial Stress Testing — HTML & Script Injection
  // ---------------------------------------------------------------------------
  const xssParams = { calls: "<script>alert('xss')</script>", costed: "<b>bold</b>" };
  const xssOut = t("dashboard.cardCaptions.spendPartialPriced" as any, xssParams);
  const xssPassed =
    xssOut.includes("<script>alert('xss')</script>") &&
    xssOut.includes("<b>bold</b>");

  record(
    "Interpolation stress: HTML & script payloads interpolated verbatim without evaluation",
    xssPassed,
    `Output: "${xssOut}"`
  );

  // ---------------------------------------------------------------------------
  // TEST 13: Adversarial Stress Testing — Prototype Pollution Resistance
  // ---------------------------------------------------------------------------
  const dirtyParams = JSON.parse('{"__proto__":{"polluted":"yes"},"constructor":{"prototype":{"polluted":"yes"}},"calls":100,"costed":90}');
  const protoOut = t("dashboard.cardCaptions.spendPartialPriced" as any, dirtyParams);
  const protoPassed = ({} as any).polluted === undefined && protoOut === "100 ta chaqiruvdan 90 tasi narxlangan";

  record(
    "Interpolation stress: prototype pollution resistance (__proto__, constructor)",
    protoPassed,
    `Object prototype clean: ${({} as any).polluted === undefined}`
  );

  // ---------------------------------------------------------------------------
  // TEST 14: Adversarial Stress Testing — Missing Parameters Graceful Preservation
  // ---------------------------------------------------------------------------
  const partialMissing = t("dashboard.cardCaptions.spendPartialPriced" as any, { calls: 100 } as any);
  const missingPreserved = partialMissing === "100 ta chaqiruvdan {costed} tasi narxlangan";
  record(
    "Interpolation stress: missing parameters safely preserved without throwing or printing undefined",
    missingPreserved,
    `Output: "${partialMissing}"`
  );

  // ---------------------------------------------------------------------------
  // TEST 15: Adversarial Stress Testing — Excess Unreferenced Parameters
  // ---------------------------------------------------------------------------
  const excessParams = { calls: 200, costed: 180, excessField1: "attack", excessField2: 99999 };
  const excessOut = t("dashboard.cardCaptions.spendPartialPriced" as any, excessParams);
  const excessPassed = excessOut === "200 ta chaqiruvdan 180 tasi narxlangan";
  record(
    "Interpolation stress: excess unreferenced parameters safely ignored",
    excessPassed,
    `Output: "${excessOut}"`
  );

  // ---------------------------------------------------------------------------
  // TEST 16: Linguistic Purity & Untranslated English Detector in uz.ts
  // ---------------------------------------------------------------------------
  // Verify that known English substrings from card captions or typical untranslated patterns don't exist
  const forbiddenEnglishSubstrings = [
    "vendor calls, all priced",
    "calls priced",
    "fake, excluded",
    "delivered, all attributed",
    "attributed of",
    "revenue − cost",
    "net × 365",
  ];
  const detectedSubstrings: string[] = [];
  for (const [k, v] of uzMap.entries()) {
    for (const forbidden of forbiddenEnglishSubstrings) {
      if (v.toLowerCase().includes(forbidden.toLowerCase())) {
        detectedSubstrings.push(`${k}: contains "${forbidden}" in "${v}"`);
      }
    }
  }

  record(
    "Untranslated English detection: zero residual English idioms in uz.ts card captions and related keys",
    detectedSubstrings.length === 0,
    `Checked against forbidden English strings`,
    detectedSubstrings.length === 0 ? undefined : `Detected: ${detectedSubstrings.join("; ")}`
  );

  // ---------------------------------------------------------------------------
  // Final Verdict
  // ---------------------------------------------------------------------------
  const totalChecks = results.length;
  const passedChecks = results.filter((r) => r.passed).length;
  const failedChecks = results.filter((r) => !r.passed).length;

  console.log("\n" + "=".repeat(80));
  console.log("  CHALLENGER 1 ADVERSARIAL VERIFICATION SUMMARY");
  console.log("=".repeat(80));
  console.log(`  Total Checks: ${totalChecks}`);
  console.log(`  Passed:       \x1b[32m${passedChecks}\x1b[0m`);
  console.log(`  Failed:       \x1b[31m${failedChecks}\x1b[0m`);
  console.log("=".repeat(80) + "\n");

  const verdict = failedChecks === 0 ? "APPROVE" : "REJECT";
  console.log(`  FINAL VERDICT: \x1b[1m${verdict === "APPROVE" ? "\x1b[32mAPPROVE" : "\x1b[31mREJECT"}\x1b[0m\n`);

  return failedChecks === 0;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const success = runKeyParityAdversarialTests();
  process.exit(success ? 0 : 1);
}
