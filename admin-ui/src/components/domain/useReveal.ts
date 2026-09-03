/**
 * The reveal's data wiring: the budget cache, the two ceilings, and the two mutations.
 *
 * These are hooks rather than components so `RevealDialog`, `RevealBudgetMeter` and whatever
 * Phase 3 builds on top of them all read one budget and one config, and so the rule that a
 * reveal is charged is expressed once: **every answer the server gives about the budget —
 * success or 429 — is folded into the cache**, because a 429 is the only measurement an
 * operator at their ceiling will ever get.
 *
 * The budget entry has no `queryFn` that calls the API on purpose. See `queryKeys.reveal`.
 */

import { useMutation, useQuery, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  failureOf,
  getConfig,
  postReveal,
  postStepUp,
  unwrapAsync,
  type ConfigView,
  type RevealRequest,
  type RevealResponse,
  type StepUpRequest,
  type StepUpResponse,
} from "@/api";
import { queryKeys } from "@/lib";

import {
  applyBudgetRefusal,
  applyRevealBudget,
  currentSnapshot,
  UNMEASURED_REVEAL_BUDGET,
  type RevealBudgetSnapshot,
} from "./revealBudget";

/** The two §12.3 ceilings, as this deployment configured them. `null` while unknown. */
export interface RevealCeilings {
  readonly records: number | null;
  readonly conversations: number | null;
  /** `adminStepUpGraceSeconds` — how long a fresh grant lasts for a non-zero-grace action. */
  readonly stepUpGraceS: number | null;
  readonly isPending: boolean;
}

const UNKNOWN_CEILINGS: RevealCeilings = {
  records: null,
  conversations: null,
  stepUpGraceS: null,
  isPending: false,
};

/**
 * `GET /api/config`, shared with the top bar and the config screen through one key.
 *
 * `enabled` exists so a closed dialog costs no request: the ceilings are only ever drawn
 * inside one, and `config.read` is a cell every role holds, so fetching it eagerly from every
 * screen carrying a reveal button would be a request per screen for a number nobody is
 * looking at.
 */
export function useRevealCeilings(isEnabled = true): RevealCeilings {
  const query = useQuery<ConfigView>({
    queryKey: queryKeys.config.detail(),
    queryFn: ({ signal }) => unwrapAsync(getConfig({ signal })),
    enabled: isEnabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const config = query.data;
  if (config === undefined) return { ...UNKNOWN_CEILINGS, isPending: query.isPending };
  return {
    records: config.adminRevealRecordsPerHour,
    conversations: config.adminRevealConversationsPerDay,
    stepUpGraceS: config.adminStepUpGraceSeconds,
    isPending: false,
  };
}

/**
 * The last budget figures the server gave this tab, aged into the current window.
 *
 * Aged, not extrapolated: a reading whose fixed window has rolled is dropped to "not
 * measured" rather than shown, because the counter behind it has been reset to zero and
 * "3 left" from 10:59 would talk an operator out of work they are entitled to do at 11:01.
 */
export function useRevealBudget(nowMs: number = Date.now()): RevealBudgetSnapshot {
  const query = useQuery<RevealBudgetSnapshot>({
    queryKey: queryKeys.reveal.budget(),
    queryFn: () => UNMEASURED_REVEAL_BUDGET,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });
  return currentSnapshot(query.data ?? UNMEASURED_REVEAL_BUDGET, nowMs);
}

/** Fold a server answer into the cached budget. Exposed for a screen that reveals by itself. */
export function useRecordRevealBudget(): (
  update: (previous: RevealBudgetSnapshot, nowMs: number) => RevealBudgetSnapshot,
) => void {
  const queryClient = useQueryClient();
  return useCallback(
    (update) => {
      const nowMs = Date.now();
      queryClient.setQueryData<RevealBudgetSnapshot>(queryKeys.reveal.budget(), (previous) =>
        update(previous ?? UNMEASURED_REVEAL_BUDGET, nowMs),
      );
    },
    [queryClient],
  );
}

/**
 * `POST /api/reveal`.
 *
 * Both outcomes teach the budget something and both are recorded:
 *
 *  - a 200 carries `budget`, with `null` on any counter it did not touch;
 *  - a 429 carries `details.recordsRemaining` / `details.conversationsRemaining`, computed
 *    with this request's own (released) charge added back.
 *
 * Nothing else in the cache is invalidated. A reveal changes no masked view — the masking is
 * server-side at the response boundary and the plaintext lives only in this mutation's
 * result, deliberately not in a query the rest of the app could read.
 */
export function useReveal(): UseMutationResult<RevealResponse, unknown, RevealRequest> {
  const record = useRecordRevealBudget();
  return useMutation<RevealResponse, unknown, RevealRequest>({
    mutationFn: (body: RevealRequest) => unwrapAsync(postReveal(body)),
    onSuccess: (response: RevealResponse) => {
      record((previous, nowMs) => applyRevealBudget(previous, response.budget, nowMs));
    },
    onError: (error: unknown) => {
      const failure = failureOf(error);
      if (failure === null || failure.code !== "REVEAL_BUDGET_EXHAUSTED") return;
      record((previous, nowMs) => applyBudgetRefusal(previous, failure, nowMs));
    },
  });
}

/**
 * `POST /api/auth/step-up` — the re-authentication behind every `A+S` cell.
 *
 * Deliberately invalidates nothing. The grant lands on `admin_sessions`, not on anything
 * `/auth/me` returns, so refetching the session after a grant would be a request that could
 * not observe the thing it was asked about. The caller's remedy is to send the ORIGINAL
 * request again; that is the only way to find out whether the grant was the one it needed.
 */
export function useStepUp(): UseMutationResult<StepUpResponse, unknown, StepUpRequest> {
  return useMutation<StepUpResponse, unknown, StepUpRequest>({
    mutationFn: (body: StepUpRequest) => unwrapAsync(postStepUp(body)),
  });
}
