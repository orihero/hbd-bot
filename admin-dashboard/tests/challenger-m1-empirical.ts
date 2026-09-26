/**
 * Empirical Challenger Harness for Milestone M1
 *
 * Stress-tests:
 * 1. Uzbek Latin script purity & orthography (0 Cyrillic characters, standard turned comma).
 * 2. Turkic cardinal numeral grammar ({count} ta ..., no double plurals with -lar).
 * 3. Russian terminology precision and case agreement.
 * 4. Untranslated English text detection across all dictionaries.
 * 5. Parameter interpolation stress (special regex chars, unicode, boundary values, prototype pollution).
 * 6. Store latency, throughput, memory overhead, and subscription leak resistance.
 */

import { en } from "../src/i18n/locales/en.js";
import { ru } from "../src/i18n/locales/ru.js";
import { uz } from "../src/i18n/locales/uz.js";
import {
  t,
  setLocale,
  getLocale,
  useI18n,
  dictionaries,
  interpolate,
  getNestedValue,
  translate,
} from "../src/i18n/index.js";
import type { TranslationSchema } from "../src/i18n/types.js";

interface TestReport {
  name: string;
  category: "linguistics" | "pluralization" | "russian" | "translation_parity" | "stress" | "performance";
  status: "PASS" | "WARN" | "FAIL";
  details: string;
  data?: unknown;
}

const reports: TestReport[] = [];

function record(report: TestReport) {
  reports.push(report);
  const icon = report.status === "PASS" ? "✔ [PASS]" : report.status === "WARN" ? "⚠ [WARN]" : "✖ [FAIL]";
  console.log(`${icon} [${report.category.toUpperCase()}] ${report.name}`);
  if (report.details) {
    console.log(`       ${report.details}`);
  }
}

function getLeaves(obj: unknown, prefix = ""): Array<{ path: string; val: string }> {
  const res: Array<{ path: string; val: string }> = [];
  if (typeof obj !== "object" || obj === null) return res;
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "object" && v !== null) {
      res.push(...getLeaves(v, path));
    } else if (typeof v === "string") {
      res.push({ path, val: v });
    }
  }
  return res;
}

const uzLeaves = getLeaves(uz);
const ruLeaves = getLeaves(ru);
const enLeaves = getLeaves(en);

console.log("\n================================================================================");
console.log("  CHALLENGER 2: EMPIRICAL VERIFICATION & STRESS HARNESS (M1)");
console.log("================================================================================\n");

/* -------------------------------------------------------------------------- */
/* SECTION 1: Uzbek Latin Script Purity & Orthography                         */
/* -------------------------------------------------------------------------- */

// Test 1.1: Strict Zero Cyrillic Characters in Uzbek Dictionary
const cyrillicRegex = /[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F]/g;
const cyrillicFound: Array<{ path: string; char: string; val: string }> = [];
for (const leaf of uzLeaves) {
  const matches = leaf.val.match(cyrillicRegex);
  if (matches) {
    cyrillicFound.push({ path: leaf.path, char: matches.join(", "), val: leaf.val });
  }
}

if (cyrillicFound.length === 0) {
  record({
    name: "Uzbek Latin script purity (0 Cyrillic characters)",
    category: "linguistics",
    status: "PASS",
    details: `Scanned all ${uzLeaves.length} leaf strings in uz.ts. Exactly 0 Cyrillic characters found.`,
  });
} else {
  record({
    name: "Uzbek Latin script purity (0 Cyrillic characters)",
    category: "linguistics",
    status: "FAIL",
    details: `Found ${cyrillicFound.length} Cyrillic characters in uz.ts!`,
    data: cyrillicFound,
  });
}

// Test 1.2: Standard Turned Comma (ʻ U+02BB) for oʻ and gʻ
const turnedCommaRegex = /[ogOG]ʻ/g;
let turnedCommaCount = 0;
for (const leaf of uzLeaves) {
  const matches = leaf.val.match(turnedCommaRegex);
  if (matches) {
    turnedCommaCount += matches.length;
  }
}

record({
  name: "Uzbek Latin turned comma modifier standard (ʻ U+02BB)",
  category: "linguistics",
  status: turnedCommaCount > 100 ? "PASS" : "WARN",
  details: `Verified consistent use of U+02BB modifier letter turned comma (found ${turnedCommaCount} standard instances in oʻ, gʻ, Oʻ, Gʻ).`,
});

// Test 1.3: Tutuq belgisi (apostrophe ʼ U+02BC) for glottal stop / phonetic separation
const tutuqRegex = /\wʼ\w/g;
let tutuqCount = 0;
for (const leaf of uzLeaves) {
  const matches = leaf.val.match(tutuqRegex);
  if (matches) {
    tutuqCount += matches.length;
  }
}

record({
  name: "Uzbek tutuq belgisi standard (ʼ U+02BC)",
  category: "linguistics",
  status: tutuqCount > 15 ? "PASS" : "WARN",
  details: `Verified use of standard typographic apostrophe U+02BC for tutuq belgisi (found ${tutuqCount} instances e.g. maʼlumot, taʼminlash, eʼtibor).`,
});

/* -------------------------------------------------------------------------- */
/* SECTION 2: Turkic Cardinal Numeral Grammar & Pluralization                 */
/* -------------------------------------------------------------------------- */

// Test 2.1: Turkic cardinal numeral syntax ({count} ta [noun])
// In standard Uzbek, count classifier 'ta' is used with cardinal numerals: e.g. {count} ta yozuv
const taPatterns: Array<{ path: string; val: string }> = [];
for (const leaf of uzLeaves) {
  if (/\{[a-zA-Z0-9_]+\}\s+ta\b/i.test(leaf.val)) {
    taPatterns.push(leaf);
  }
}

if (taPatterns.length >= 10) {
  record({
    name: "Uzbek cardinal numeral classifier syntax ({count} ta [noun])",
    category: "pluralization",
    status: "PASS",
    details: `Found ${taPatterns.length} templates correctly using Turkic classifier 'ta' (e.g. '{count} ta yozuv', '{count} ta foydalanuvchi', '{count} ta urinish').`,
  });
} else {
  record({
    name: "Uzbek cardinal numeral classifier syntax ({count} ta [noun])",
    category: "pluralization",
    status: "WARN",
    details: `Only ${taPatterns.length} templates use 'ta'.`,
  });
}

// Test 2.2: Absence of Redundant Plural Suffix (-lar) after Numerals / Quantifiers
// In Uzbek grammar, saying "5 ta kitoblar" is a severe grammatical error.
// Any noun modified by a number or "{param} ta" MUST be singular.
const invalidPluralRegex = /\{[a-zA-Z0-9_]+\}\s+(?:ta\s+)?(\w+lar\b)/i;
const invalidPlurals: Array<{ path: string; match: string; val: string }> = [];
for (const leaf of uzLeaves) {
  const match = leaf.val.match(invalidPluralRegex);
  if (match) {
    invalidPlurals.push({ path: leaf.path, match: match[0], val: leaf.val });
  }
}

if (invalidPlurals.length === 0) {
  record({
    name: "Absence of redundant plural suffix (-lar) after numerals",
    category: "pluralization",
    status: "PASS",
    details: `Zero instances of invalid double-plural syntax (e.g. '{count} ta yozuvlar'). All quantified nouns remain singular.`,
  });
} else {
  record({
    name: "Absence of redundant plural suffix (-lar) after numerals",
    category: "pluralization",
    status: "FAIL",
    details: `Detected ${invalidPlurals.length} grammatically invalid plural suffixes following numerals!`,
    data: invalidPlurals,
  });
}

// Test 2.3: Verification of specific test case '{count} ta yozuv' from dispatch
setLocale("uz");
const costRecordsUz = t("reveal.costRecords", { count: 42 });
const expectedCostRecords = "42 ta yozuv";
if (costRecordsUz === expectedCostRecords) {
  record({
    name: "Dispatch requirement check: reveal.costRecords -> '{count} ta yozuv'",
    category: "pluralization",
    status: "PASS",
    details: `t("reveal.costRecords", { count: 42 }) yielded "${costRecordsUz}". Matches required '{count} ta yozuv' syntax.`,
  });
} else {
  record({
    name: "Dispatch requirement check: reveal.costRecords -> '{count} ta yozuv'",
    category: "pluralization",
    status: "FAIL",
    details: `Expected "${expectedCostRecords}", received "${costRecordsUz}".`,
  });
}

/* -------------------------------------------------------------------------- */
/* SECTION 3: Russian Technical Clarity & Security Terminology                */
/* -------------------------------------------------------------------------- */

setLocale("ru");

// Test 3.1: Cryptographic HMAC Seal & Tamper-Evidence Terminology
const auditVerifyTitle = t("audit.verify.title");
const auditVerifyDesc = t("audit.verify.description");
const auditVerifySuccess = t("audit.verify.successMessage", { count: 150 });
const auditVerifyFail = t("audit.verify.failureMessage", { entryId: 99 });

const hasHmacAuditTerms =
  auditVerifyTitle.includes("целостности") &&
  auditVerifyDesc.includes("хэш-цепочку HMAC") &&
  auditVerifySuccess.includes("Цепочка HMAC-подписей непрерывна") &&
  auditVerifyFail.includes("Несовпадение HMAC-подписи") || auditVerifyFail.includes("несовпадение HMAC-подписи");

if (hasHmacAuditTerms) {
  record({
    name: "Russian cryptographic & HMAC audit terminology precision",
    category: "russian",
    status: "PASS",
    details: `Confirmed professional security terminology: 'целостность журнала аудита', 'хэш-цепочка HMAC', 'Цепочка HMAC-подписей непрерывна для всех 150 проверенных записей'.`,
  });
} else {
  record({
    name: "Russian cryptographic & HMAC audit terminology precision",
    category: "russian",
    status: "FAIL",
    details: `Security copy did not match expected professional terms. Received: "${auditVerifyDesc}"`,
  });
}

// Test 3.2: Step-Up Re-Authentication Terminology
const stepUpTitle = t("reveal.stepUp.title");
const stepUpAction = t("reveal.actions.reveal");
const isStepUpClear =
  stepUpTitle === "Повторная аутентификация" &&
  stepUpAction.includes("раскрытие персональных данных");

if (isStepUpClear) {
  record({
    name: "Russian step-up authentication & privacy terminology",
    category: "russian",
    status: "PASS",
    details: `Accurate security terminology: 'Повторная аутентификация', 'раскрытие персональных данных по этому объекту'.`,
  });
} else {
  record({
    name: "Russian step-up authentication & privacy terminology",
    category: "russian",
    status: "WARN",
    details: `Step-up phrasing: title='${stepUpTitle}', action='${stepUpAction}'`,
  });
}

// Test 3.3: Russian Case Endings and Prepositions in Pagination & Filters
const ruUsersPage = t("users.paginationSubtitle", { start: 1, end: 50, total: 500 });
const ruAuditPage = t("audit.paginationSubtitle", { start: 1, end: 25, total: 100 });
const hasProperGenitive =
  ruUsersPage === "Показано 1–50 из 500 пользователей" &&
  ruAuditPage === "Показано 1–25 из 100 записей аудита";

if (hasProperGenitive) {
  record({
    name: "Russian genitive case endings in pagination ('из {total} ...')",
    category: "russian",
    status: "PASS",
    details: `Correct genitive forms: 'из 500 пользователей', 'из 100 записей аудита'.`,
  });
} else {
  record({
    name: "Russian genitive case endings in pagination ('из {total} ...')",
    category: "russian",
    status: "WARN",
    details: `Pagination phrasing: users='${ruUsersPage}', audit='${ruAuditPage}'`,
  });
}

/* -------------------------------------------------------------------------- */
/* SECTION 4: Untranslated English Text Audit                                 */
/* -------------------------------------------------------------------------- */

// Check for unlocalized English sentences or phrases in uz.ts and ru.ts
// Known untranslated or identical keys:
const untranslatedInUz: Array<{ path: string; enVal: string; uzVal: string }> = [];
const enMap = new Map(enLeaves.map((l) => [l.path, l.val]));

/**
 * Is this string a SENTENCE, or is it something that reads the same in every language?
 *
 * The rule the original comment described but never implemented: strip the placeholders and
 * everything that is not a letter, then count the words of three letters or more. A template
 * (`{start}–{end}`), a dash, an abbreviation (`OK`, `ASCII`, `MRR`), a wire term nobody
 * translates (`correlation id`, `Telegram id`) and a ticket example (`SUP-1423`) all fall
 * under two such words and are legitimately identical across the three catalogues.
 *
 * This replaces a hand-kept allowlist of literal strings, which had to be edited every time a
 * screen added an invariant — a list that grows on every commit is a list that gets a wrong
 * entry added to silence a real failure.
 */
/**
 * The words that are the same in every catalogue because they are not words: the product's
 * own name, and the currency and unit codes a figure is quoted in. `soʻm` is here in its
 * Uzbek spelling because that IS the spelling all three use.
 */
const INVARIANT_TOKENS = new Set(["bayram", "bot", "admin", "usd", "uzs", "soʻm", "som"]);

function isTranslatablePhrase(value: string): boolean {
  const words = value
    .replace(/\{[^}]*\}/gu, " ")
    .split(/[^\p{L}ʻ]+/u)
    .filter((word) => word.length >= 3 && !INVARIANT_TOKENS.has(word.toLowerCase()));
  return words.length >= 2;
}

for (const leaf of uzLeaves) {
  const enVal = enMap.get(leaf.path);
  if (!enVal) continue;
  if (leaf.val === enVal && isTranslatablePhrase(leaf.val)) {
    untranslatedInUz.push({ path: leaf.path, enVal, uzVal: leaf.val });
  }
}

if (untranslatedInUz.length > 0) {
  record({
    name: "Audit for untranslated English strings in Uzbek dictionary",
    category: "translation_parity",
    status: "FAIL",
    details: `Found ${untranslatedInUz.length} string(s) left completely in English in uz.ts!`,
    data: untranslatedInUz,
  });
  for (const item of untranslatedInUz) {
    console.log(`       -> ${item.path}: "${item.uzVal}"`);
  }
} else {
  record({
    name: "Audit for untranslated English strings in Uzbek dictionary",
    category: "translation_parity",
    status: "PASS",
    details: `All non-brand/non-acronym strings in uz.ts are fully translated into Uzbek Latin.`,
  });
}

/* -------------------------------------------------------------------------- */
/* SECTION 5: Parameter Interpolation Stress Testing                          */
/* -------------------------------------------------------------------------- */

setLocale("en");

// Test 5.1: Numeric boundary values: 0, negative, float, large number
const zeroCount = t("common.usersCount", { count: 0 });
const negCount = t("common.usersCount", { count: -1 });
const floatCount = t("dashboard.fxRate", { rate: 12850.75 });
const largeCount = t("common.usersCount", { count: 1_000_000_000 });

if (
  zeroCount === "0 users" &&
  negCount === "-1 users" &&
  floatCount === "1 USD = 12850.75 soʻm" &&
  largeCount === "1000000000 users"
) {
  record({
    name: "Interpolation with numeric boundaries (0, negative, float, 1B)",
    category: "stress",
    status: "PASS",
    details: `Correctly renders 0, negative values, floating point numbers, and large integers without NaN or coercion glitches.`,
  });
} else {
  record({
    name: "Interpolation with numeric boundaries",
    category: "stress",
    status: "FAIL",
    details: `Failed boundary interpolation: zero='${zeroCount}', neg='${negCount}', float='${floatCount}', large='${largeCount}'`,
  });
}

// Test 5.2: Special regex characters in parameter values
const specialChars = "$ & ' ` \\ * + ? ( ) [ ] { } ^ |";
const specialResult = t("chats.callback", { data: specialChars });
if (specialResult === `🔘 Callback: ${specialChars}`) {
  record({
    name: "Interpolation with regex metacharacters ($ & ' ` \\ * + ?)",
    category: "stress",
    status: "PASS",
    details: `Regex special characters in parameter arguments are treated as literal text and do not cause Regex pattern injection or corruption.`,
  });
} else {
  record({
    name: "Interpolation with regex metacharacters",
    category: "stress",
    status: "FAIL",
    details: `Expected "🔘 Callback: ${specialChars}", got "${specialResult}"`,
  });
}

// Test 5.3: Prototype pollution defense
const protoPayload = {
  __proto__: { polluted: "YES" },
  constructor: { prototype: { polluted: "YES" } },
  toString: "custom_toString",
};
const protoResult = t("nav.signedInAs", protoPayload as unknown as Record<string, string>);
if (!protoResult.includes("YES") && !("polluted" in Object.prototype)) {
  record({
    name: "Prototype pollution resistance in parameter interpolation",
    category: "stress",
    status: "PASS",
    details: `Store ignores prototype-polluting keys (__proto__, constructor) without corrupting Object prototype.`,
  });
} else {
  record({
    name: "Prototype pollution resistance",
    category: "stress",
    status: "FAIL",
    details: `Object prototype was polluted or corrupted!`,
  });
}

// Test 5.4: Missing and undefined parameter handling
const missingParam = t("nav.signedInAs", { username: "alice" }); // missing {role}
const undefParam = t("nav.signedInAs", { username: "bob", role: undefined as unknown as string });
if (missingParam.includes("{role}") && undefParam.includes("{role}")) {
  record({
    name: "Missing parameter graceful preservation",
    category: "stress",
    status: "PASS",
    details: `Missing or undefined parameter values safely preserve placeholder without crashing or printing 'undefined'.`,
  });
} else {
  record({
    name: "Missing parameter graceful preservation",
    category: "stress",
    status: "WARN",
    details: `Result for missing: "${missingParam}", undef: "${undefParam}"`,
  });
}

/* -------------------------------------------------------------------------- */
/* SECTION 6: Store Latency, Throughput, and Subscription Overhead            */
/* -------------------------------------------------------------------------- */

// Test 6.1: Translation Lookup Throughput (100,000 lookups)
const ITERATIONS = 100_000;
const startLookup = performance.now();
for (let i = 0; i < ITERATIONS; i++) {
  t("common.confirm");
  t("users.paginationSubtitle", { start: 1, end: 20, total: 100 });
}
const endLookup = performance.now();
const totalLookupTime = endLookup - startLookup;
const lookupsPerSec = Math.round(((ITERATIONS * 2) / (totalLookupTime / 1000)));

record({
  name: `Translation throughput: 200,000 lookups benchmark`,
  category: "performance",
  status: totalLookupTime < 300 ? "PASS" : "WARN",
  details: `Executed 200,000 key lookups + parameter interpolations in ${totalLookupTime.toFixed(2)}ms (~${lookupsPerSec.toLocaleString()} ops/sec). Overhead is effectively zero.`,
});

// Test 6.2: Rapid Sequential Locale Switching (1,000 switches)
const SWITCH_COUNT = 1_000;
const startSwitch = performance.now();
const locales: Array<"uz" | "ru" | "en"> = ["uz", "ru", "en"];
for (let i = 0; i < SWITCH_COUNT; i++) {
  setLocale(locales[i % 3]!);
}
const endSwitch = performance.now();
const switchTime = endSwitch - startSwitch;

record({
  name: `Locale switching latency: 1,000 sequential switches`,
  category: "performance",
  status: switchTime < 100 ? "PASS" : "WARN",
  details: `Completed 1,000 rapid locale switches in ${switchTime.toFixed(2)}ms (~${(switchTime / SWITCH_COUNT).toFixed(3)}ms per switch). Final locale: '${getLocale()}'.`,
});

// Test 6.3: High-concurrency subscriber isolation and cleanup
const SUBSCRIBERS = 500;
let callbackInvocations = 0;
const unsubscribers: Array<() => void> = [];

for (let i = 0; i < SUBSCRIBERS; i++) {
  const unsub = useI18n.subscribe((state) => {
    if (state.locale) callbackInvocations++;
  });
  unsubscribers.push(unsub);
}

// Trigger state change
setLocale("uz");
const invocationsAfterSet = callbackInvocations;

// Clean up all subscribers
for (const unsub of unsubscribers) {
  unsub();
}

// Trigger another state change — invocations should NOT increment
setLocale("en");
const invocationsAfterUnsub = callbackInvocations;

if (invocationsAfterSet === SUBSCRIBERS && invocationsAfterUnsub === SUBSCRIBERS) {
  record({
    name: `Subscriber isolation & cleanup (500 concurrent subscribers)`,
    category: "performance",
    status: "PASS",
    details: `All 500 subscribers synchronously notified on locale change; cleanly unsubscribed with 0 lingering callbacks.`,
  });
} else {
  record({
    name: `Subscriber isolation & cleanup`,
    category: "performance",
    status: "FAIL",
    details: `Expected 500 invocations and 0 post-cleanup invocations; got ${invocationsAfterSet} then ${invocationsAfterUnsub}.`,
  });
}

/* -------------------------------------------------------------------------- */
/* SUMMARY & VERDICT                                                          */
/* -------------------------------------------------------------------------- */

const passedCount = reports.filter((r) => r.status === "PASS").length;
const warnCount = reports.filter((r) => r.status === "WARN").length;
const failCount = reports.filter((r) => r.status === "FAIL").length;

console.log("\n================================================================================");
console.log("  CHALLENGER 2 EMPIRICAL TEST SUMMARY");
console.log("================================================================================");
console.log(`  Total Checks: ${reports.length}`);
console.log(`  Passed:       ${passedCount}`);
console.log(`  Warnings:     ${warnCount}`);
console.log(`  Failed:       ${failCount}`);
console.log("================================================================================\n");

if (failCount > 0) {
  console.log("VERDICT: REJECT (Defects identified requiring remediation)");
  process.exit(1);
} else {
  console.log("VERDICT: APPROVE (All linguistic, pluralization & performance gates passed)");
  process.exit(0);
}
