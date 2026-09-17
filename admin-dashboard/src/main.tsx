import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { createQueryClient } from "@/lib/queryClient";
import { router } from "@/routes";
import { useAuthStore } from "@/state/auth";
import { applyStoredTheme } from "@/state/theme";
import "@/styles/index.css";
import "@/i18n";

const container = document.getElementById("root");
if (container === null) {
  // index.html and this file disagree; rendering into a detached node would hide that.
  throw new Error("#root is missing from index.html — nothing to mount into.");
}

/*
 * Started before the first paint rather than from an effect: the guards render the neutral
 * shell while `status` is "unknown", and kicking the request off here means that shell is
 * already waiting on a request in flight instead of on a second render. Deliberately not
 * awaited — the shell IS the loading state.
 */
void useAuthStore.getState().bootstrap();

/*
 * Before `createRoot`, not from an effect: an effect runs after the first paint, so a
 * dark-palette operator would get one frame of the light ground on every page load. Not an
 * inline script in `index.html` either — this app serves a CSP nonce, and one frame is not
 * worth widening that.
 */
applyStoredTheme();

/*
 * One client for the app's lifetime. Built here rather than in a component so a re-render
 * cannot swap the cache out from under the polls and blank the page it was drawn from.
 */
const queryClient = createQueryClient();

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
