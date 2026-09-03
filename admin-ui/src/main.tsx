/**
 * The entry point. Five things happen here and nothing else.
 *
 * 1. The stylesheet is imported, so tokens land before the first paint.
 * 2. `installCspNonce()` reads this response's style nonce out of the shell and publishes it
 *    to `get-nonce`. Without it the CSP blocks the `<style>` element `react-remove-scroll`
 *    injects for every Radix modal, and the page keeps scrolling behind an open dialog with
 *    nothing but a console violation to show for it. See `src/lib/csp.ts` — this is the one
 *    seam, and there is deliberately no per-call-site `nonce` prop to forget.
 * 3. `initTheme()` stamps `data-theme` onto `<html>` from the persisted preference. This
 *    runs BEFORE `createRoot`, because `tokens.css` keys the light palette off that
 *    attribute and a theme applied in an effect is a flash of the wrong palette.
 * 4. One `QueryClient` is created — TanStack Query is the only server-state store (§11.1),
 *    and a second client would mean two caches nothing invalidates together.
 * 5. The data router mounts.
 *
 * `StrictMode` is on. Its double-invocation in development is what catches an effect that
 * subscribes without unsubscribing — and this app has an `<audio>` element and a set of
 * pollers that would leak exactly that way.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { installCspNonce } from "@/lib/csp";
import { createQueryClient } from "@/lib/queryClient";
import { initTheme } from "@/lib/stores";
import { createRouter } from "@/routes";
import "@/styles/index.css";

installCspNonce();
initTheme();

const queryClient = createQueryClient();
const router = createRouter();

const container = document.getElementById("root");
if (container === null) {
  // index.html is served from the wheel; if this is missing, the served shell is not ours.
  throw new Error("#root is missing from index.html");
}

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
