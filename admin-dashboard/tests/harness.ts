/**
 * Test Harness for Admin Dashboard Multilingual Localization
 * 
 * Provides:
 * - In-memory DOM & Storage isolation (localStorage, document.documentElement.lang, navigator.languages)
 * - Assertions (strict equal, deep equal, throws, includes, regex match)
 * - Lightweight test runner with progress logging and timing
 * - Canonical translation schema & authoritative keys for parity validation
 * - Dynamic module & file inspection helpers
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
export const PROJECT_ROOT = path.resolve(__dirname, "..");

// --- 1. Mock In-Memory Web Storage ---

export class MockStorage implements Storage {
  private store = new Map<string, string>();
  public shouldThrowOnGet = false;
  public shouldThrowOnSet = false;
  public throwErrorType: "SecurityError" | "QuotaExceededError" = "SecurityError";

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    if (this.shouldThrowOnGet) {
      const err = new Error("Simulated storage read permission denied");
      err.name = this.throwErrorType;
      throw err;
    }
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    if (this.shouldThrowOnSet) {
      const err = new Error("Simulated storage write quota or security error");
      err.name = this.throwErrorType;
      throw err;
    }
    this.store.set(key, String(value));
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  key(index: number): string | null {
    const keys = Array.from(this.store.keys());
    return keys[index] ?? null;
  }
}

// --- 2. Mock DOM Environment ---

export interface MockDocumentElement {
  lang: string;
}

export interface MockDocument {
  documentElement: MockDocumentElement;
}

export interface MockNavigator {
  language: string;
  languages: readonly string[];
}

export interface TestEnv {
  storage: MockStorage;
  doc: MockDocument;
  nav: MockNavigator;
}

let activeEnv: TestEnv | null = null;
const originalDescriptors: Record<string, PropertyDescriptor | undefined> = {};

export function setupTestEnv(initialLocale?: string, initialNavLang = "en-US"): TestEnv {
  const storage = new MockStorage();
  if (initialLocale) {
    storage.setItem("hbd.dashboard.locale", initialLocale);
  }

  const doc: MockDocument = {
    documentElement: { lang: initialLocale ?? "en" },
  };

  const nav: MockNavigator = {
    language: initialNavLang,
    languages: [initialNavLang, "en"],
  };

  activeEnv = { storage, doc, nav };

  // Save original descriptors once
  const g = globalThis as Record<string, unknown>;
  if (!("localStorage" in originalDescriptors)) {
    originalDescriptors.localStorage = Object.getOwnPropertyDescriptor(g, "localStorage");
    originalDescriptors.document = Object.getOwnPropertyDescriptor(g, "document");
    originalDescriptors.navigator = Object.getOwnPropertyDescriptor(g, "navigator");
    originalDescriptors.window = Object.getOwnPropertyDescriptor(g, "window");
  }

  // Safely define globals
  Object.defineProperty(g, "localStorage", { value: storage, configurable: true, writable: true });
  Object.defineProperty(g, "document", { value: doc, configurable: true, writable: true });
  Object.defineProperty(g, "navigator", { value: nav, configurable: true, writable: true });
  Object.defineProperty(g, "window", {
    value: { localStorage: storage, document: doc, navigator: nav },
    configurable: true,
    writable: true,
  });

  return activeEnv;
}

export function restoreTestEnv(): void {
  const g = globalThis as Record<string, unknown>;
  for (const [prop, desc] of Object.entries(originalDescriptors)) {
    if (desc) {
      Object.defineProperty(g, prop, desc);
    } else {
      delete g[prop];
    }
  }
  activeEnv = null;
}

export function getActiveEnv(): TestEnv {
  if (!activeEnv) {
    return setupTestEnv();
  }
  return activeEnv;
}

// --- 3. Assertion Library ---

export class AssertionError extends Error {
  constructor(message: string, public actual?: unknown, public expected?: unknown) {
    super(message);
    this.name = "AssertionError";
  }
}

export function assert(condition: boolean, message = "Assertion failed"): void {
  if (!condition) {
    throw new AssertionError(message, condition, true);
  }
}

export function assertEqual<T>(actual: T, expected: T, message?: string): void {
  if (actual !== expected) {
    const msg = message ? `${message} - expected: ${String(expected)}, got: ${String(actual)}` : `Expected ${String(expected)}, got ${String(actual)}`;
    throw new AssertionError(msg, actual, expected);
  }
}

export function assertNotEqual<T>(actual: T, expected: T, message?: string): void {
  if (actual === expected) {
    const msg = message ? `${message} - expected value to NOT equal ${String(expected)}` : `Expected value to NOT equal ${String(expected)}`;
    throw new AssertionError(msg, actual, expected);
  }
}

export function assertDeepEqual(actual: unknown, expected: unknown, message?: string): void {
  const actJson = JSON.stringify(actual);
  const expJson = JSON.stringify(expected);
  if (actJson !== expJson) {
    const msg = message ? `${message} - objects differ` : `Objects differ: expected ${expJson}, got ${actJson}`;
    throw new AssertionError(msg, actual, expected);
  }
}

export function assertIncludes(str: string, substr: string, message?: string): void {
  if (!str.includes(substr)) {
    const msg = message ? `${message} - expected "${str}" to include "${substr}"` : `Expected "${str}" to include "${substr}"`;
    throw new AssertionError(msg, str, substr);
  }
}

export function assertNotIncludes(str: string, substr: string, message?: string): void {
  if (str.includes(substr)) {
    const msg = message ? `${message} - expected "${str}" NOT to include "${substr}"` : `Expected "${str}" NOT to include "${substr}"`;
    throw new AssertionError(msg, str, substr);
  }
}

export function assertMatches(str: string, regex: RegExp, message?: string): void {
  if (!regex.test(str)) {
    const msg = message ? `${message} - expected "${str}" to match ${regex.toString()}` : `Expected "${str}" to match ${regex.toString()}`;
    throw new AssertionError(msg, str, regex);
  }
}

export function assertThrows(fn: () => unknown, expectedNameOrMsg?: string, message?: string): void {
  let threw = false;
  let caught: unknown = null;
  try {
    fn();
  } catch (err) {
    threw = true;
    caught = err;
  }
  if (!threw) {
    throw new AssertionError(message ?? "Expected function to throw, but it succeeded");
  }
  if (expectedNameOrMsg && caught instanceof Error) {
    if (!caught.name.includes(expectedNameOrMsg) && !caught.message.includes(expectedNameOrMsg)) {
      throw new AssertionError(
        `Expected error matching "${expectedNameOrMsg}", got "${caught.name}: ${caught.message}"`,
        caught.message,
        expectedNameOrMsg
      );
    }
  }
}

// --- 4. Lightweight Test Runner ---

export interface TestCaseResult {
  id: string;
  name: string;
  status: "PASS" | "FAIL" | "PENDING_IMPLEMENTATION";
  durationMs: number;
  error?: Error;
}

export interface SuiteResult {
  suiteName: string;
  results: TestCaseResult[];
  passed: number;
  failed: number;
  pending: number;
  totalDurationMs: number;
}

export async function runTest(
  id: string,
  name: string,
  fn: () => Promise<void> | void
): Promise<TestCaseResult> {
  const start = performance.now();
  try {
    await fn();
    const durationMs = Math.round((performance.now() - start) * 100) / 100;
    return { id, name, status: "PASS", durationMs };
  } catch (err: unknown) {
    const durationMs = Math.round((performance.now() - start) * 100) / 100;
    const error = err instanceof Error ? err : new Error(String(err));
    const isPending = error.message.includes("[PENDING_IMPLEMENTATION]") ||
                      error.message.includes("Cannot find module") ||
                      error.message.includes("does not exist yet");
    return {
      id,
      name,
      status: isPending ? "PENDING_IMPLEMENTATION" : "FAIL",
      durationMs,
      error,
    };
  }
}

// --- 5. File System & Module Inspection Helpers ---

export function checkFileExists(relPath: string): boolean {
  const fullPath = path.resolve(PROJECT_ROOT, relPath);
  return fs.existsSync(fullPath);
}

export function readSourceFile(relPath: string): string {
  const fullPath = path.resolve(PROJECT_ROOT, relPath);
  if (!fs.existsSync(fullPath)) {
    throw new Error(`[PENDING_IMPLEMENTATION] File ${relPath} does not exist yet`);
  }
  return fs.readFileSync(fullPath, "utf-8");
}

export async function loadModuleSafely<T = Record<string, unknown>>(relPath: string): Promise<T> {
  const fullPath = path.resolve(PROJECT_ROOT, relPath);
  if (!fs.existsSync(fullPath)) {
    throw new Error(`[PENDING_IMPLEMENTATION] Module ${relPath} does not exist yet`);
  }
  try {
    return (await import(fullPath)) as T;
  } catch (err) {
    throw new Error(`Failed to load module ${relPath}: ${String(err)}`);
  }
}

// --- 6. Flat Key Extraction & Object Traversal ---

export function flattenKeys(obj: Record<string, unknown>, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(out, flattenKeys(v as Record<string, unknown>, fullKey));
    } else {
      out[fullKey] = String(v);
    }
  }
  return out;
}

export function extractParameters(str: string): string[] {
  const matches = str.match(/\{([a-zA-Z0-9_]+)\}/g);
  if (!matches) return [];
  return Array.from(new Set(matches.map((m) => m.slice(1, -1))));
}

// --- 7. Reference Canonical Namespaces ---

export const REQUIRED_NAMESPACES = [
  "common",
  "nav",
  "auth",
  "dashboard",
  "chats",
  "users",
  "generations",
  "audit",
  "admins",
  "reveal",
  "errors",
] as const;

export const SUPPORTED_LOCALES = ["en", "ru", "uz"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];
