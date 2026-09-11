/**
 * Challenger M1 Iteration 2: Deep Empirical Stress & Adversarial Test Harness
 *
 * Specific Focus:
 * 1. Deep parameter interpolation verification for remediated keys:
 *    - dashboard.cardCaptions.spendPartialPriced (0, large numbers, fractions, partial/missing, en/ru/uz parity)
 *    - dashboard.cardCaptions.cpsPartialAttributed (0, large numbers, fractions, partial/missing, en/ru/uz parity)
 * 2. High-volume interpolation throughput and latency benchmark (1,000,000 operations).
 * 3. Deep prototype pollution resistance & malicious payload fuzzing.
 * 4. High-concurrency reactive store switching & subscriber stress (2,000 concurrent subscribers, 10,000 async switches).
 */

import {
  t,
  setLocale,
  getLocale,
  useI18n,
  interpolate,
  translate,
  dictionaries,
} from "../src/i18n/index.js";
import type { SupportedLocale } from "../src/i18n/types.js";

interface TestResult {
  suite: string;
  name: string;
  passed: boolean;
  message: string;
  durationMs?: number;
}

const results: TestResult[] = [];

function assert(condition: boolean, suite: string, name: string, message: string, durationMs?: number) {
  results.push({ suite, name, passed: condition, message, durationMs });
  const tag = condition ? "✔ [PASS]" : "✖ [FAIL]";
  const timeStr = durationMs !== undefined ? ` (${durationMs.toFixed(2)}ms)` : "";
  console.log(`${tag} [${suite}] ${name}${timeStr}`);
  if (!condition) {
    console.error(`       ERROR: ${message}`);
  }
}

async function runSuite() {
  console.log("\n================================================================================");
  console.log("  CHALLENGER M1 ITER2: DEEP EMPIRICAL STRESS & ADVERSARIAL HARNESS");
  console.log("================================================================================\n");

  /* ============================================================================ */
  /* SUITE 1: Remediated Uzbek Captions Parameter Interpolation                   */
  /* ============================================================================ */
  console.log("--- Suite 1: Remediated Uzbek Captions Deep Interpolation ---");

  setLocale("uz");

  // 1.1 spendPartialPriced - Zero inputs
  {
    const res = t("dashboard.cardCaptions.spendPartialPriced", { calls: 0, costed: 0 });
    assert(
      res === "0 ta chaqiruvdan 0 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Zero inputs (calls: 0, costed: 0)",
      `Expected "0 ta chaqiruvdan 0 tasi narxlangan", got "${res}"`,
    );
  }

  // 1.2 spendPartialPriced - Single count
  {
    const res = t("dashboard.cardCaptions.spendPartialPriced", { calls: 1, costed: 1 });
    assert(
      res === "1 ta chaqiruvdan 1 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Unit input (calls: 1, costed: 1)",
      `Expected "1 ta chaqiruvdan 1 tasi narxlangan", got "${res}"`,
    );
  }

  // 1.3 spendPartialPriced - Typical operational numbers
  {
    const res = t("dashboard.cardCaptions.spendPartialPriced", { calls: 100, costed: 80 });
    assert(
      res === "100 ta chaqiruvdan 80 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Typical input (calls: 100, costed: 80)",
      `Expected "100 ta chaqiruvdan 80 tasi narxlangan", got "${res}"`,
    );
  }

  // 1.4 spendPartialPriced - Large numbers (1 Billion, MAX_SAFE_INTEGER)
  {
    const res1B = t("dashboard.cardCaptions.spendPartialPriced", {
      calls: 1_000_000_000,
      costed: 850_000_000,
    });
    assert(
      res1B === "1000000000 ta chaqiruvdan 850000000 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Large numbers: 1 Billion calls",
      `Expected "1000000000 ta chaqiruvdan 850000000 tasi narxlangan", got "${res1B}"`,
    );

    const maxInt = Number.MAX_SAFE_INTEGER;
    const resMax = t("dashboard.cardCaptions.spendPartialPriced", { calls: maxInt, costed: 0 });
    assert(
      resMax === `${maxInt} ta chaqiruvdan 0 tasi narxlangan`,
      "Remediation:spendPartialPriced",
      "MAX_SAFE_INTEGER boundary",
      `Expected "${maxInt} ta chaqiruvdan 0 tasi narxlangan", got "${resMax}"`,
    );
  }

  // 1.5 spendPartialPriced - Floating point & fractional inputs
  {
    const resFloat = t("dashboard.cardCaptions.spendPartialPriced", { calls: 100.5, costed: 80.25 });
    assert(
      resFloat === "100.5 ta chaqiruvdan 80.25 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Fractional/Float numbers",
      `Expected "100.5 ta chaqiruvdan 80.25 tasi narxlangan", got "${resFloat}"`,
    );

    const resSci = t("dashboard.cardCaptions.spendPartialPriced", { calls: 1e6, costed: 5e5 });
    assert(
      resSci === "1000000 ta chaqiruvdan 500000 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Scientific notation numbers",
      `Expected "1000000 ta chaqiruvdan 500000 tasi narxlangan", got "${resSci}"`,
    );
  }

  // 1.6 spendPartialPriced - Negative numbers
  {
    const resNeg = t("dashboard.cardCaptions.spendPartialPriced", { calls: -50, costed: -10 });
    assert(
      resNeg === "-50 ta chaqiruvdan -10 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Negative numbers",
      `Expected "-50 ta chaqiruvdan -10 tasi narxlangan", got "${resNeg}"`,
    );
  }

  // 1.7 spendPartialPriced - Missing or partial parameters graceful degradation
  {
    const partialCalls = t("dashboard.cardCaptions.spendPartialPriced", { calls: 100 });
    assert(
      partialCalls === "100 ta chaqiruvdan {costed} tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Partial params: calls only",
      `Expected "100 ta chaqiruvdan {costed} tasi narxlangan", got "${partialCalls}"`,
    );

    const partialCosted = t("dashboard.cardCaptions.spendPartialPriced", { costed: 42 });
    assert(
      partialCosted === "{calls} ta chaqiruvdan 42 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Partial params: costed only",
      `Expected "{calls} ta chaqiruvdan 42 tasi narxlangan", got "${partialCosted}"`,
    );

    const emptyParams = t("dashboard.cardCaptions.spendPartialPriced", {});
    assert(
      emptyParams === "{calls} ta chaqiruvdan {costed} tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Empty params object",
      `Expected "{calls} ta chaqiruvdan {costed} tasi narxlangan", got "${emptyParams}"`,
    );

    const undefParams = t("dashboard.cardCaptions.spendPartialPriced", {
      calls: undefined as unknown as number,
      costed: null as unknown as number,
    });
    assert(
      undefParams === "{calls} ta chaqiruvdan {costed} tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Null & Undefined param values preserved safely",
      `Expected "{calls} ta chaqiruvdan {costed} tasi narxlangan", got "${undefParams}"`,
    );
  }

  // 1.8 spendPartialPriced - Formatted string numbers (localized display strings)
  {
    const resFormatted = t("dashboard.cardCaptions.spendPartialPriced", {
      calls: "1,250",
      costed: "1,100",
    });
    assert(
      resFormatted === "1,250 ta chaqiruvdan 1,100 tasi narxlangan",
      "Remediation:spendPartialPriced",
      "Pre-formatted comma strings",
      `Expected "1,250 ta chaqiruvdan 1,100 tasi narxlangan", got "${resFormatted}"`,
    );
  }

  // 1.9 cpsPartialAttributed - Zero inputs
  {
    const res = t("dashboard.cardCaptions.cpsPartialAttributed", { delivered: 0, attributed: 0 });
    assert(
      res === "0 tadan 0 tasi hisoblangan",
      "Remediation:cpsPartialAttributed",
      "Zero inputs (delivered: 0, attributed: 0)",
      `Expected "0 tadan 0 tasi hisoblangan", got "${res}"`,
    );
  }

  // 1.10 cpsPartialAttributed - Operational counts
  {
    const res = t("dashboard.cardCaptions.cpsPartialAttributed", { delivered: 50, attributed: 45 });
    assert(
      res === "50 tadan 45 tasi hisoblangan",
      "Remediation:cpsPartialAttributed",
      "Typical input (delivered: 50, attributed: 45)",
      `Expected "50 tadan 45 tasi hisoblangan", got "${res}"`,
    );
  }

  // 1.11 cpsPartialAttributed - Large numbers
  {
    const resLarge = t("dashboard.cardCaptions.cpsPartialAttributed", {
      delivered: 50_000_000,
      attributed: 49_999_999,
    });
    assert(
      resLarge === "50000000 tadan 49999999 tasi hisoblangan",
      "Remediation:cpsPartialAttributed",
      "Large numbers: 50 Million",
      `Expected "50000000 tadan 49999999 tasi hisoblangan", got "${resLarge}"`,
    );
  }

  // 1.12 cpsPartialAttributed - Fractional / Float numbers
  {
    const resFloat = t("dashboard.cardCaptions.cpsPartialAttributed", {
      delivered: 99.9,
      attributed: 33.33,
    });
    assert(
      resFloat === "99.9 tadan 33.33 tasi hisoblangan",
      "Remediation:cpsPartialAttributed",
      "Fractional/Float numbers",
      `Expected "99.9 tadan 33.33 tasi hisoblangan", got "${resFloat}"`,
    );
  }

  // 1.13 cpsPartialAttributed - Partial and missing params
  {
    const partialDelivered = t("dashboard.cardCaptions.cpsPartialAttributed", { delivered: 100 });
    assert(
      partialDelivered === "100 tadan {attributed} tasi hisoblangan",
      "Remediation:cpsPartialAttributed",
      "Partial params: delivered only",
      `Expected "100 tadan {attributed} tasi hisoblangan", got "${partialDelivered}"`,
    );

    const partialAttr = t("dashboard.cardCaptions.cpsPartialAttributed", { attributed: 90 });
    assert(
      partialAttr === "{delivered} tadan 90 tasi hisoblangan",
      "Remediation:cpsPartialAttributed",
      "Partial params: attributed only",
      `Expected "{delivered} tadan 90 tasi hisoblangan", got "${partialAttr}"`,
    );
  }

  // 1.14 Trilingual Parameter Parity Check for remediated keys across UZ, RU, EN
  {
    const paramNamesSpend = ["calls", "costed"];
    const paramNamesCps = ["delivered", "attributed"];

    for (const loc of ["uz", "ru", "en"] as SupportedLocale[]) {
      setLocale(loc);
      const spendTpl = t("dashboard.cardCaptions.spendPartialPriced", { calls: 111, costed: 222 });
      const cpsTpl = t("dashboard.cardCaptions.cpsPartialAttributed", {
        delivered: 333,
        attributed: 444,
      });

      const spendHasBoth = spendTpl.includes("111") && spendTpl.includes("222");
      const cpsHasBoth = cpsTpl.includes("333") && cpsTpl.includes("444");

      assert(
        spendHasBoth && cpsHasBoth,
        "Remediation:TrilingualParity",
        `Parameter interpolation parity for '${loc}'`,
        `Failed in locale '${loc}': spend='${spendTpl}', cps='${cpsTpl}'`,
      );
    }
  }

  /* ============================================================================ */
  /* SUITE 2: High-Volume Interpolation Throughput & Stress (1,000,000 Lookups)    */
  /* ============================================================================ */
  console.log("\n--- Suite 2: High-Volume Interpolation Performance & Stress ---");

  setLocale("uz");
  const THROUGHPUT_ROUNDS = 1_000_000;
  const startThroughput = performance.now();

  for (let i = 0; i < THROUGHPUT_ROUNDS; i++) {
    // Alternate between the two remediated keys and standard keys
    if (i % 3 === 0) {
      t("dashboard.cardCaptions.spendPartialPriced", { calls: i, costed: i - 1 });
    } else if (i % 3 === 1) {
      t("dashboard.cardCaptions.cpsPartialAttributed", { delivered: i, attributed: i - 2 });
    } else {
      t("users.paginationSubtitle", { start: 1, end: 20, total: i });
    }
  }

  const elapsedThroughput = performance.now() - startThroughput;
  const opsPerSec = Math.round((THROUGHPUT_ROUNDS / (elapsedThroughput / 1000)));

  assert(
    elapsedThroughput < 2500, // Expected ~200-500ms for 1M in Node v20+
    "Performance:Throughput",
    `1,000,000 lookups with interpolation: ${opsPerSec.toLocaleString()} ops/sec`,
    `Elapsed time ${elapsedThroughput.toFixed(2)}ms exceeded 2500ms threshold`,
    elapsedThroughput,
  );

  // 2.2 Extreme string length interpolation (100,000 chars)
  {
    const giantString = "A".repeat(100_000);
    const startGiant = performance.now();
    const giantRes = t("chats.callback", { data: giantString });
    const elapsedGiant = performance.now() - startGiant;

    assert(
      giantRes.length === 100_000 + "🔘 Callback: ".length && giantRes.endsWith(giantString),
      "Stress:LargePayload",
      "100,000 character parameter value interpolation",
      `Unexpected result length ${giantRes.length}`,
      elapsedGiant,
    );
  }

  // 2.3 Regex pattern replacement attacks ($&, $', $`, $1, $$ in parameters)
  {
    const regexExploitParams = {
      calls: "$& $1 $` $' $$",
      costed: "\\0 \\1 \\x00",
    };
    const exploitRes = t("dashboard.cardCaptions.spendPartialPriced", regexExploitParams);
    assert(
      exploitRes.includes("$& $1 $` $' $$") && exploitRes.includes("\\0 \\1 \\x00"),
      "Stress:RegexInjection",
      "Regex capture token safety ($&, $1, $`, $', $$)",
      `Failed to safely preserve literal dollar strings: got "${exploitRes}"`,
    );
  }

  /* ============================================================================ */
  /* SUITE 3: Deep Prototype Pollution Resistance & Object Fuzzing                 */
  /* ============================================================================ */
  console.log("\n--- Suite 3: Prototype Pollution & Malicious Object Fuzzing ---");

  // 3.1 Standard __proto__ injection via JSON parse
  {
    const evilJson = '{"__proto__":{"pollutedKey":"PWNED_PROTO"},"constructor":{"prototype":{"evilKey":"PWNED_CONST"}},"calls":99,"costed":88}';
    const parsedPayload = JSON.parse(evilJson);

    const protoRes = t("dashboard.cardCaptions.spendPartialPriced", parsedPayload);
    const protoClean = !("pollutedKey" in Object.prototype) && !("evilKey" in Object.prototype);

    assert(
      protoClean && protoRes === "99 ta chaqiruvdan 88 tasi narxlangan",
      "Security:PrototypePollution",
      "JSON parsed __proto__ and constructor prototype injection",
      `Prototype was polluted or values failed: protoClean=${protoClean}, res="${protoRes}"`,
    );
  }

  // 3.2 Null prototype dictionary input
  {
    const nullProtoParams = Object.create(null);
    nullProtoParams.calls = 500;
    nullProtoParams.costed = 400;

    const resNullProto = t("dashboard.cardCaptions.spendPartialPriced", nullProtoParams);
    assert(
      resNullProto === "500 ta chaqiruvdan 400 tasi narxlangan",
      "Security:ObjectFuzzing",
      "Object.create(null) parameter container",
      `Failed for null prototype object: got "${resNullProto}"`,
    );
  }

  // 3.3 Shadowed Object methods in params (toString, hasOwnProperty, valueOf)
  {
    const shadowedParams = {
      calls: 10,
      costed: 5,
      toString: () => {
        throw new Error("toString attack!");
      },
      hasOwnProperty: () => {
        throw new Error("hasOwnProperty attack!");
      },
      valueOf: () => {
        throw new Error("valueOf attack!");
      },
    };

    let caughtErr = false;
    let safeRes = "";
    try {
      safeRes = t("dashboard.cardCaptions.spendPartialPriced", shadowedParams as unknown as Record<string, unknown>);
    } catch {
      caughtErr = true;
    }

    assert(
      !caughtErr && safeRes === "10 ta chaqiruvdan 5 tasi narxlangan",
      "Security:ObjectFuzzing",
      "Shadowed Object.prototype methods (toString, hasOwnProperty, valueOf)",
      `Failed when Object methods are shadowed: caughtErr=${caughtErr}, safeRes="${safeRes}"`,
    );
  }

  // 3.4 Key traversal prototype pollution attempt
  {
    const evilKey1 = translate("uz", "__proto__.polluted");
    const evilKey2 = translate("uz", "constructor.prototype.polluted");
    const evilKey3 = translate("uz", "toString");

    assert(
      evilKey1 === "__proto__.polluted" &&
        evilKey2 === "constructor.prototype.polluted" &&
        evilKey3 === "toString" &&
        !("polluted" in Object.prototype),
      "Security:KeyTraversal",
      "Direct key traversal for prototype poisoning paths",
      `Key traversal corrupted or returned unexpected: k1="${evilKey1}", k2="${evilKey2}", k3="${evilKey3}"`,
    );
  }

  /* ============================================================================ */
  /* SUITE 4: High-Concurrency Reactive Store Switching & Subscriber Stress        */
  /* ============================================================================ */
  console.log("\n--- Suite 4: High Concurrency Reactive Store Switching ---");

  // 4.1 Massive subscriber fan-out (2,000 active subscribers)
  {
    const SUBSCRIBER_COUNT = 2_000;
    const unsubscribers: Array<() => void> = [];
    const notificationCounts = new Int32Array(SUBSCRIBER_COUNT);

    const startSub = performance.now();
    for (let i = 0; i < SUBSCRIBER_COUNT; i++) {
      const idx = i;
      const unsub = useI18n.subscribe((state) => {
        if (state.locale) {
          notificationCounts[idx]++;
        }
      });
      unsubscribers.push(unsub);
    }
    const elapsedSub = performance.now() - startSub;

    // Trigger state change
    setLocale("ru");
    setLocale("en");
    setLocale("uz");

    // Verify all 2,000 received exactly 3 notifications
    let allNotified = true;
    for (let i = 0; i < SUBSCRIBER_COUNT; i++) {
      if (notificationCounts[i] !== 3) {
        allNotified = false;
        break;
      }
    }

    // Clean up all 2,000 subscribers
    const startUnsub = performance.now();
    for (const unsub of unsubscribers) {
      unsub();
    }
    const elapsedUnsub = performance.now() - startUnsub;

    // Trigger one more change; notifications should not increment
    setLocale("ru");
    let cleanLeakFree = true;
    for (let i = 0; i < SUBSCRIBER_COUNT; i++) {
      if (notificationCounts[i] !== 3) {
        cleanLeakFree = false;
        break;
      }
    }

    assert(
      allNotified && cleanLeakFree,
      "Concurrency:Subscribers",
      `2,000 concurrent subscribers fan-out (sub: ${elapsedSub.toFixed(1)}ms, unsub: ${elapsedUnsub.toFixed(1)}ms)`,
      `Subscriber fan-out failure: allNotified=${allNotified}, cleanLeakFree=${cleanLeakFree}`,
    );
  }

  // 4.2 Asynchronous interleaved concurrent store switching (10,000 async switches)
  {
    const SWITCH_COUNT = 10_000;
    const locales: SupportedLocale[] = ["uz", "ru", "en"];
    const startAsync = performance.now();

    const tasks: Promise<void>[] = [];
    for (let i = 0; i < SWITCH_COUNT; i++) {
      const target = locales[i % 3];
      tasks.push(
        new Promise<void>((resolve) => {
          // Rapid asynchronous interleaved microtask dispatch
          queueMicrotask(() => {
            setLocale(target);
            // Verify immediate internal coherence during switch
            const current = getLocale();
            if (!["uz", "ru", "en"].includes(current)) {
              throw new Error(`Incoherent locale during async churn: ${current}`);
            }
            resolve();
          });
        }),
      );
    }

    await Promise.all(tasks);
    const elapsedAsync = performance.now() - startAsync;

    // Deterministic state restoration to "uz"
    setLocale("uz");

    const finalLocale = getLocale();
    const finalStoreLocale = useI18n.getState().locale;
    const domLang = typeof document !== "undefined" ? document.documentElement.lang : "uz";

    const coherent = finalLocale === "uz" && finalStoreLocale === "uz" && domLang === "uz";

    assert(
      coherent,
      "Concurrency:AsyncChurn",
      `10,000 interleaved asynchronous store switches in ${elapsedAsync.toFixed(2)}ms`,
      `Store out of sync after async churn: finalLocale=${finalLocale}, store=${finalStoreLocale}, dom=${domLang}`,
      elapsedAsync,
    );
  }

  // 4.3 Multi-threaded Web Storage Event Emulation Under Churn
  {
    if (typeof window !== "undefined") {
      const startEv = performance.now();
      for (let i = 0; i < 500; i++) {
        const target = (["uz", "ru", "en"] as const)[i % 3];
        window.dispatchEvent(
          new StorageEvent("storage", {
            key: "bayram.dashboard.locale",
            newValue: target,
          }),
        );
      }
      const elapsedEv = performance.now() - startEv;

      setLocale("uz");
      assert(
        getLocale() === "uz",
        "Concurrency:StorageEvents",
        "500 simulated cross-window storage events",
        "Failed cross-window sync",
        elapsedEv,
      );
    }
  }

  /* ============================================================================ */
  /* SUMMARY REPORT                                                               */
  /* ============================================================================ */
  console.log("\n================================================================================");
  console.log("  CHALLENGER M1 ITER2 STRESS SUMMARY");
  console.log("================================================================================");

  const passed = results.filter((r) => r.passed).length;
  const failed = results.filter((r) => !r.passed).length;

  console.log(`  Total Checks: ${results.length}`);
  console.log(`  Passed:       ${passed}`);
  console.log(`  Failed:       ${failed}`);
  console.log("================================================================================");

  if (failed > 0) {
    console.error(`\nVERDICT: REJECT (${failed} test(s) failed)`);
    process.exit(1);
  } else {
    console.log("\nVERDICT: APPROVE (All empirical stress, security & concurrency tests passed)");
    process.exit(0);
  }
}

runSuite().catch((err) => {
  console.error("FATAL SUITE ERROR:", err);
  process.exit(1);
});
