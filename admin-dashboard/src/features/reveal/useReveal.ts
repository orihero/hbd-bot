/**
 * The reveal flow, as a hook: ask → maybe re-authenticate → hold the plaintext in memory →
 * forget it.
 *
 * ## Why the plaintext is NOT in the react-query cache
 *
 * Everything else this app reads goes through react-query, and this deliberately does not.
 * A cache is a thing that OUTLIVES the screen that asked: it is keyed, shared, garbage
 * collected on its own schedule, refetched on window focus, and readable by any component
 * that can guess the key — every one of those properties is exactly wrong for a disclosure
 * that was paid for with a step-up, a budget unit and an audit row naming one operator, one
 * subject and one reason. A cached reveal would let a second screen render a customer's phone
 * number that nobody on that screen asked for, minutes after the dialog that asked was
 * closed, with no audit row saying so. The devtools would show it, a persister would write it
 * to disk, and a refetch would re-charge the budget with no reason attached.
 *
 * So the result lives in this hook's own state and dies with the component that mounted it.
 * It is never keyed, never persisted, never put in the URL and never logged. `forget()` drops
 * it on demand; unmount and sign-out drop it without being asked.
 *
 * ## The four steps, and the two refusals that are not errors
 *
 * `POST /api/reveal` validates, enforces a step-up ON THE SUBJECT, charges the budget, then
 * audits-then-reads. Two of its refusals have remedies and must not be rendered as errors:
 *
 *  - `STEP_UP_REQUIRED` **with** `details` is the handler asking for a grant. It happens
 *    BEFORE the budget is charged, so **nothing was spent** — `phase.kind === "stepUp"`
 *    exists as its own state partly to be able to say that. The same `STEP_UP_REQUIRED`
 *    WITHOUT details is the router refusing on role alone; re-authenticating cannot change
 *    it, so it lands in `refused` with `isRoleRefusal`, and the dialog shows no password box.
 *  - `REVEAL_BUDGET_EXHAUSTED` is a spent ceiling, carrying which of the two refused and the
 *    seconds until that window resets. It is not `SERVICE_UNAVAILABLE`, which is the counter
 *    store failing to answer — conflating them has an operator opening an incident against
 *    the wrong system.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiFailure } from "@/api/client";
import {
  isStepUpRequired,
  reveal,
  revealBudgetRefusalOf,
  stepUp,
  stepUpTargetOf,
  type RevealBudgetRefusal,
  type RevealBudgetView,
  type RevealRequest,
  type RevealResponse,
  type StepUpRequest,
  type StepUpResponse,
  type StepUpTarget,
} from "@/api/reveal";
import type { TranslationPath } from "@/i18n/types";
import { useAuthStore } from "@/state/auth";

/* -------------------------------------------------------------------------- */
/* Copy that belongs to the flow rather than to one dialog                      */
/* -------------------------------------------------------------------------- */

/**
 * Said wherever a step-up is asked for BEFORE A REVEAL, because the alternative reading is
 * expensive. Only the reveal route has a budget: `enforce_reveal_budget` is called from
 * `routers/reveal.py` and nowhere else, so this sentence is a lie on any other action.
 */
export const STEP_UP_COSTS_NO_BUDGET_NOTE =
  "Nothing has been charged and nothing disclosed: the password check runs before the budget, so a refused or abandoned re-authentication costs you no records.";

/**
 * The same reassurance for the §9.2 WRITES — block, unblock, grant — which have no records
 * ceiling at all. Saying "costs you no records" there teaches an operator that these routes
 * are metered against the reveal budget, and misdirects them the first time a 429 lands.
 */
export const STEP_UP_CHANGES_NOTHING_NOTE =
  "Nothing has happened yet: the password check runs before the write, so a refused or abandoned re-authentication changes nothing on this account and writes only the refusal to the audit log.";

/** §12.3, said once, where the operator is deciding — not in a tooltip. */
export const REVEAL_IS_AUDITED_NOTE =
  "Every reveal writes an audit row naming you, the subject, the columns and this reason, and it is written before the read — so the disclosure is attributable even if the read then fails. The row records WHICH columns were revealed, never what they said.";

/** Said when the router, not a grant check, refused. There is no password box for this. */
export const ROLE_REFUSAL_NOTE =
  "This refusal came from the route's own guard rather than from a grant check, so re-authenticating cannot change it: your role holds no cell in this row.";

/* -------------------------------------------------------------------------- */
/* The phases                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Where one reveal has got to. A discriminated union rather than a bag of booleans, because
 * "stepped up but also budget-refused" is not a state the server can produce and a screen
 * that can represent it will eventually render it.
 */
export type RevealPhase =
  | { readonly kind: "idle" }
  | { readonly kind: "pending" }
  /** The handler wants a grant for exactly this action on exactly this subject. Free so far. */
  | { readonly kind: "stepUp"; readonly target: StepUpTarget; readonly failure: ApiFailure }
  /** A ceiling refused. Its own state, carrying the window's reset. */
  | {
      readonly kind: "budget";
      readonly refusal: RevealBudgetRefusal;
      readonly failure: ApiFailure;
    }
  /** Everything a retry cannot fix: 403 on role, 404, 422, 503, drift, transport. */
  | {
      readonly kind: "refused";
      readonly failure: ApiFailure;
      /** True when asking again with the same credentials cannot change the answer. */
      readonly isRoleRefusal: boolean;
    }
  /** Plaintext, in memory, belonging to this hook and nothing else. */
  | { readonly kind: "revealed"; readonly result: RevealResponse };

const IDLE: RevealPhase = { kind: "idle" };

export interface RevealFlow {
  readonly phase: RevealPhase;
  readonly isPending: boolean;
  /** The plaintext, or `null`. Read it here; do not copy it anywhere that outlives the view. */
  readonly result: RevealResponse | null;
  /**
   * The last budget the SERVER reported, from a 200. `null` until one has been measured —
   * and `null` on a counter the server did not touch, which is not the same as `0`.
   */
  readonly budget: RevealBudgetView | null;
  /** Send a reveal. The body is remembered so a grant can replay it unchanged. */
  readonly request: (body: RevealRequest) => void;
  /** Send the remembered body again — what a granted step-up does. No-op with nothing to send. */
  readonly retry: () => void;
  /** Drop the plaintext, the remembered body and any refusal. Idempotent. */
  readonly forget: () => void;
}

export function useReveal(): RevealFlow {
  const [phase, setPhase] = useState<RevealPhase>(IDLE);
  const [budget, setBudget] = useState<RevealBudgetView | null>(null);

  /**
   * The body to replay after a grant. A ref rather than state: a grant authorises an ACTION
   * on a SUBJECT, not a request — the server has no memory of what was being attempted — so
   * the same bytes must go again, and re-rendering when they are stored buys nothing.
   */
  const pendingRef = useRef<RevealRequest | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);

  const forget = useCallback((): void => {
    // Abort first: a response still in flight carries plaintext, and `forget()` must mean
    // that no plaintext lands after it, not that it lands a moment later.
    abortRef.current?.abort();
    abortRef.current = null;
    pendingRef.current = null;
    setPhase(IDLE);
  }, []);

  const send = useCallback((body: RevealRequest): void => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    pendingRef.current = body;
    setPhase({ kind: "pending" });

    void (async () => {
      // `reveal()` returns, never throws, so there is no catch here by design.
      const outcome = await reveal(body, controller.signal);
      // An aborted request renders as nothing at all — and drops whatever it was carrying.
      if (!isMountedRef.current || controller.signal.aborted) return;
      abortRef.current = null;

      if (outcome.ok) {
        setBudget(outcome.data.budget);
        setPhase({ kind: "revealed", result: outcome.data });
        return;
      }

      const budgetRefusal = revealBudgetRefusalOf(outcome);
      if (budgetRefusal !== null) {
        setPhase({ kind: "budget", refusal: budgetRefusal, failure: outcome });
        return;
      }

      const target = stepUpTargetOf(outcome);
      if (target !== null) {
        setPhase({ kind: "stepUp", target, failure: outcome });
        return;
      }

      setPhase({
        kind: "refused",
        failure: outcome,
        // A `STEP_UP_REQUIRED` with no details is `check_role`, which holds no subject and
        // consults no grant. Offering a password box for it is a loop nobody can win.
        isRoleRefusal: outcome.code === "FORBIDDEN" || isStepUpRequired(outcome),
      });
    })();
  }, []);

  const retry = useCallback((): void => {
    const body = pendingRef.current;
    if (body !== null) send(body);
  }, [send]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      // Unmount is a forget. The state goes with the component either way; the abort is what
      // stops a reply that is already on the wire from being decoded into a dead tree, and
      // clearing the ref is what stops a closure still holding this body from replaying it.
      isMountedRef.current = false;
      abortRef.current?.abort();
      abortRef.current = null;
      pendingRef.current = null;
    };
  }, []);

  const status = useAuthStore((state) => state.status);
  useEffect(() => {
    // Sign-out is a forget too, and it has to be: the session that authorised this disclosure
    // is over, and a panel still showing the phone number it bought is a disclosure with no
    // live authorisation behind it. `status` also leaves "authed" when the server expires the
    // session out from under a tab.
    if (status !== "authed") forget();
  }, [status, forget]);

  return {
    phase,
    isPending: phase.kind === "pending",
    result: phase.kind === "revealed" ? phase.result : null,
    budget,
    request: send,
    retry,
    forget,
  };
}

/* -------------------------------------------------------------------------- */
/* The re-authentication                                                        */
/* -------------------------------------------------------------------------- */

export interface StepUpFlow {
  readonly isPending: boolean;
  readonly failure: ApiFailure | null;
  /** The grant, once one lands. `expiresAt` is the expiry the guard will actually honour. */
  readonly grant: StepUpResponse | null;
  /**
   * Re-authenticate. The password is passed in and never held here: it goes into one request
   * body and is gone. `onGranted` is handed the GRANT, never the credential.
   */
  readonly submit: (body: StepUpRequest, onGranted: (grant: StepUpResponse) => void) => void;
  readonly reset: () => void;
}

/**
 * `POST /api/auth/step-up` — the app's one re-authentication, so that four later phases reuse
 * it rather than growing a second form that spells a scope differently.
 *
 * A wrong password is `FORBIDDEN` and is metered like a login; a burst is
 * `REAUTH_RATE_LIMITED`, whose counter is scoped to the SESSION — which is why its remedy is
 * signing in again rather than waiting on this screen.
 */
export function useStepUp(): StepUpFlow {
  const [isPending, setIsPending] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [grant, setGrant] = useState<StepUpResponse | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const reset = useCallback((): void => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsPending(false);
    setFailure(null);
    setGrant(null);
  }, []);

  const submit = useCallback(
    (body: StepUpRequest, onGranted: (granted: StepUpResponse) => void): void => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setIsPending(true);
      setFailure(null);

      void (async () => {
        const outcome = await stepUp(body, controller.signal);
        if (!isMountedRef.current || controller.signal.aborted) return;
        abortRef.current = null;
        setIsPending(false);
        if (!outcome.ok) {
          setFailure(outcome);
          return;
        }
        setGrant(outcome.data);
        onGranted(outcome.data);
      })();
    },
    [],
  );

  return { isPending, failure, grant, submit, reset };
}

/* -------------------------------------------------------------------------- */
/* Reading a refusal                                                            */
/* -------------------------------------------------------------------------- */

/**
 * What an operator should DO about a failure, in one sentence, keyed on the code rather than
 * on the status — the codes exist precisely so an SPA does not have to read 403 three ways.
 *
 * Returns `null` when the server's own message is the whole story; the dialog prints that
 * verbatim, because it is already redacted and capped and it is what gets pasted into a
 * ticket.
 */
export function revealFailureAdvice(failure: ApiFailure): string | null {
  switch (failure.code) {
    case "UNAUTHENTICATED":
    case "CSRF_REJECTED":
      // Both mean the session is effectively over. The CSRF cookie and the session cookie are
      // set and cleared together, so a rejected token is a missing session, not a retryable
      // glitch — and re-trying it just writes another rejection.
      return "Your session has ended. Sign in again; nothing was disclosed.";
    case "ORIGIN_REJECTED":
      return "The panel is being served from an origin the API does not recognise. That is a deployment setting (HBD_ADMIN_PUBLIC_ORIGIN), not anything you did — trying again will not help.";
    case "FORBIDDEN":
      return ROLE_REFUSAL_NOTE;
    case "REAUTH_RATE_LIMITED":
      return "Too many re-authentication attempts on this session. The counter is scoped to the session, so signing in again starts a fresh window.";
    case "NOT_FOUND":
      return "There is no such subject. For a customer, that can be the erasure record itself: /forget deletes the profile row outright, so an erased customer is a 404 here rather than a row with a purge stamp on it.";
    case "SERVICE_UNAVAILABLE":
      return "The budget counter could not answer. This is NOT your budget being spent — it is the store behind it not responding. Worth trying again shortly.";
    case "INVALID_INPUT":
      return "The server refused this request body. Nothing was charged, and — because the body never reached the audit step — nothing was logged either.";
    case "SCHEMA_DRIFT":
      return "This build and the server disagree about the reveal contract. Nothing was rendered from the response. Report it with the correlation id.";
    case "NETWORK_ERROR":
      return "The request never reached the server. Nothing was charged and nothing was disclosed.";
    default:
      return null;
  }
}

/** Which of the two ceilings refused, in words. `null` when the server did not name one. */
export function budgetScopeKey(refusal: RevealBudgetRefusal): TranslationPath {
  switch (refusal.scope) {
    case "records":
      return "reveal.dialog.scopeRecords";
    case "conversations":
      return "reveal.dialog.scopeConversations";
    default:
      // The server refused but did not say which counter. Say that, rather than picking one:
      // the two have different windows and telling an operator to come back at the wrong one
      // is worse than telling them nothing.
      return "reveal.dialog.scopeUnknown";
  }
}

/** `Retry-After` as something to read. `null` when the envelope carried no countdown. */
export function describeRetryAfter(
  retryAfterS: number | null,
  t: (path: TranslationPath, params?: Record<string, string | number>) => string,
): string | null {
  if (retryAfterS === null) return null;
  if (retryAfterS < 90) {
    return t("reveal.dialog.retrySeconds", { count: Math.max(1, Math.round(retryAfterS)) });
  }
  return t("reveal.dialog.retryMinutes", { count: Math.round(retryAfterS / 60) });
}
