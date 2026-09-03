/**
 * The nonce seam. These tests exist because the bug they cover is invisible: with no nonce
 * installed a dialog still opens, still looks right, and only the page behind it — which
 * keeps scrolling — says anything is wrong.
 *
 * jsdom enforces no CSP, so nothing here can assert that the browser applied the style.
 * That assertion belongs to the Playwright smoke flow run under the production policy
 * (§13.3). What IS asserted here is the contract that flow depends on: the nonce comes out
 * of the shell's meta element, the unsubstituted placeholder is not a nonce, and the value
 * reaches `get-nonce` — which is the exact function `react-style-singleton` calls before it
 * appends a `<style>`.
 */

import { getNonce, setNonce } from "get-nonce";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CSP_NONCE_META_NAME, CSP_NONCE_PLACEHOLDER, installCspNonce, readCspNonce } from "./csp";

/** A standalone document, so a test never mutates the one `@testing-library` cleans up. */
function shell(nonceAttribute: string | null): Document {
  const doc = document.implementation.createHTMLDocument("shell");
  if (nonceAttribute !== null) {
    const meta = doc.createElement("meta");
    meta.setAttribute("name", CSP_NONCE_META_NAME);
    meta.setAttribute("content", nonceAttribute);
    doc.head.append(meta);
  }
  return doc;
}

afterEach(() => {
  // `setNonce` writes a module-level variable; an empty string reads back as absent.
  setNonce("");
});

describe("reading the nonce out of the shell", () => {
  it("reads the value the server substituted", () => {
    expect(readCspNonce(shell("Yeycam3SdcOvMG1lzPXqmg"))).toBe("Yeycam3SdcOvMG1lzPXqmg");
  });

  it("treats the unsubstituted placeholder as no nonce — that is `vite dev`, which sends no CSP", () => {
    expect(readCspNonce(shell(CSP_NONCE_PLACEHOLDER))).toBeNull();
  });

  it("treats an empty content attribute as no nonce", () => {
    expect(readCspNonce(shell(""))).toBeNull();
  });

  it("returns null when the shell carries no meta element at all", () => {
    expect(readCspNonce(shell(null))).toBeNull();
  });
});

describe("installing it", () => {
  it("publishes the nonce to get-nonce, which is what react-style-singleton reads", () => {
    // Arrange - this is the whole mechanism. `react-style-singleton`'s `makeStyleTag()`
    // calls `getNonce()` and sets the attribute only if it returns something.
    expect(getNonce()).toBeUndefined();

    // Act
    const installed = installCspNonce(shell("Yeycam3SdcOvMG1lzPXqmg"));

    // Assert
    expect(installed).toBe("Yeycam3SdcOvMG1lzPXqmg");
    expect(getNonce()).toBe("Yeycam3SdcOvMG1lzPXqmg");
  });

  it("installs nothing when there is no nonce, and stays quiet outside a production build", () => {
    // Arrange - under `vite dev` and in jsdom there is no policy to satisfy, so a warning
    // here would be noise on every test run.
    const error = vi.spyOn(console, "error").mockImplementation(() => {});

    // Act
    const installed = installCspNonce(shell(CSP_NONCE_PLACEHOLDER));

    // Assert
    expect(installed).toBeNull();
    expect(getNonce()).toBeUndefined();
    expect(error).not.toHaveBeenCalled();
  });
});
