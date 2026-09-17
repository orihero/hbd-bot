/**
 * `/broadcasts/new` — filter the people, compose the message, read it back and send it.
 *
 * A ROUTE and not a dialog, because it carries an audience in the URL: the directory's "Message
 * these users" hands this screen `?segment=<base64url>` — `encodeSegment`'s bytes, unaltered —
 * and the same document is what gets frozen, so a refresh must not lose it and the address bar
 * must stay transposable to a `curl`.
 *
 * ## The two calls behind one button, and why the operator is told about both
 *
 * `POST /api/broadcasts` FREEZES the audience: it counts the segment exactly, refuses a count
 * that has drifted from the one the operator was shown, and materialises a recipient row per
 * account. `POST /{id}/send` authorises the messages and is where the step-up sits. The wizard
 * runs them in that order behind one press, and states the freeze before it happens rather than
 * after — because between the two the audience has stopped moving and nothing has been sent, and
 * that is precisely the state an operator needs to understand if the second call fails.
 *
 * ## Exactly one create per wizard, guaranteed by a ref
 *
 * There is no `requestId` on the create route: two presses are two campaigns with two frozen
 * audiences and no way to tell them apart afterwards. `campaignIdRef` is what stops that — once
 * a campaign exists, every subsequent attempt REVISES it (title and the whole body set) and the
 * create is never made again. That is also what makes the step-up replay honest: re-authorising
 * sends the same campaign, not a second copy of it.
 *
 * ## Going back loses nothing
 *
 * One component holds the draft for all three steps, so Back is a render and not a reload. The
 * audience is mirrored into `?segment=` with `replace`, so a refresh keeps the population without
 * filling the history stack with keystrokes — and the message text is deliberately NOT in the
 * URL, because a campaign body has no business in a browser history or a referrer header.
 *
 * ## A drift is surfaced, never sent through
 *
 * A `409` from the create carries both numbers: what the operator was shown, and what the segment
 * counts now. The panel shows the pair and offers the two honest choices — go back and re-read
 * the audience, or freeze it as it stands — rather than silently sending to a stale number or
 * silently sending to a new one.
 */

import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type JSX, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  audienceDriftOf,
  broadcastStateConflictOf,
  type BroadcastSendRequest,
  type BroadcastTestSendRequest,
  type BroadcastTestSendResultView,
  type BroadcastView,
  type Language,
} from "@/api/broadcasts";
import { CLIENT_ERROR_CODES } from "@/api/client";
import { stepUpTargetOf } from "@/api/reveal";
import { segmentFieldIndex } from "@/api/segments";
import { PATH, broadcastDetailPath } from "@/app/paths";
import { ErrorNote } from "@/components/ErrorNote";
import { Toolbar } from "@/components/Toolbar";
import { isSegmentValid, useSegmentFields, useSegmentPreview } from "@/components/SegmentBuilder";
import {
  BROADCAST_STATE_LABEL_KEY,
  formatCount,
  noteFor,
} from "@/features/broadcasts/broadcastFormat";
import {
  useCreateBroadcast,
  useReviseBroadcast,
  useSendBroadcast,
  useTestSendBroadcast,
} from "@/features/broadcasts/useBroadcasts";
import { StepUpDialog } from "@/features/reveal";
import { Panel } from "@/features/users/detailKit";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import { failureOf, type AdminQueryError } from "@/lib/adminQuery";
import { useCanWriteBroadcasts } from "@/lib/rbac";
import { cn } from "@/lib/cn";
import { EMPTY_SEGMENT, decodeSegment, segmentToken, type Segment } from "@/lib/segmentCodec";
import { useSessionGuard } from "@/state/useSessionGuard";

import { AudienceStep } from "./AudienceStep";
import { MessageStep } from "./MessageStep";
import { ReviewStep } from "./ReviewStep";
import { TestSendDialog } from "./TestSendDialog";
import {
  WIZARD_STEPS,
  audienceLanguagesOf,
  audienceRefusal,
  compositionSignature,
  createRequestOf,
  messageRefusal,
  nextStep,
  previousStep,
  reviseRequestOf,
  stepIndex,
  type WizardDraft,
  type WizardStep,
} from "./wizardState";

const STEP_NAME_KEY: Readonly<Record<WizardStep, TranslationPath>> = {
  audience: "broadcasts.wizard.steps.audience",
  message: "broadcasts.wizard.steps.message",
  review: "broadcasts.wizard.steps.review",
};

/** What is in flight, held so a step-up can replay it byte for byte. */
type PendingAction =
  | { readonly kind: "send"; readonly body: BroadcastSendRequest }
  | { readonly kind: "test"; readonly body: BroadcastTestSendRequest };

export function BroadcastWizardScreen(): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const canWrite = useCanWriteBroadcasts();

  const [step, setStep] = useState<WizardStep>("audience");
  const [draft, setDraft] = useState<WizardDraft>(() => ({
    // A hand-edited or truncated token is `null` — "start from nothing" — and never a throw.
    segment: decodeSegment(searchParams.get("segment")) ?? EMPTY_SEGMENT,
    title: "",
    kind: "service",
    bodies: {},
  }));
  const [language, setLanguage] = useState<Language | null>(null);
  const [isTestOpen, setIsTestOpen] = useState(false);

  /**
   * The campaign this wizard has already created, if any.
   *
   * A ref and not only state, because `ensureCampaign` reads it inside an async flow that started
   * before the render that would have updated it — and the whole point of it is that a second
   * create can never happen.
   */
  const campaignIdRef = useRef<string | null>(null);
  const [campaign, setCampaign] = useState<BroadcastView | null>(null);
  const [frozenLanguages, setFrozenLanguages] = useState<readonly Language[] | null>(null);
  const syncedRef = useRef<string | null>(null);
  const pendingRef = useRef<PendingAction | null>(null);
  /** Set when the operator answers a drift with "freeze it as it stands now". */
  const insistRef = useRef(false);
  const [testResult, setTestResult] = useState<BroadcastTestSendResultView | null>(null);

  const registry = useSegmentFields({ enabled: canWrite });
  const preview = useSegmentPreview(draft.segment, { enabled: canWrite });
  const create = useCreateBroadcast();
  const revise = useReviseBroadcast();
  const send = useSendBroadcast();
  const testSend = useTestSendBroadcast();

  const registryError = errorOf(registry.error);
  const previewError = errorOf(preview.error);
  useSessionGuard([registryError, previewError, send.error, create.error]);

  const registryView = registry.data ?? null;
  const previewView = preview.data ?? null;
  const fieldIndex = useMemo(
    () => (registryView === null ? new Map() : segmentFieldIndex(registryView)),
    [registryView],
  );

  const isDocumentValid =
    registryView !== null &&
    isSegmentValid(draft.segment, {
      fields: fieldIndex,
      limits: registryView.limits,
      version: registryView.version,
    });

  /*
   * The languages freeze with the audience: the bodies were written for the split the preview
   * published at creation, and a revise sends the WHOLE set — a language that appeared afterwards
   * would delete the bodies it did not include.
   */
  const languages = frozenLanguages ?? audienceLanguagesOf(previewView);
  const isFrozen = campaign !== null;

  const audienceBlock = audienceRefusal({
    isSegmentValid: isDocumentValid,
    isRegistryReadable: registryView !== null,
    preview: previewView,
  });
  const messageBlock = messageRefusal(draft, languages);

  /* The audience mirrors into the URL so a refresh keeps the population. `replace`, because a
     keystroke in a rule row is not a place to go Back to. */
  const token = segmentToken(draft.segment);
  useEffect(() => {
    // Guarded rather than unconditional: writing the same value back would be a navigation per
    // render, and a `replace` loop is invisible until the profiler is open.
    if (token === searchParams.get("segment")) return;
    const next = new URLSearchParams(searchParams);
    if (token === null) next.delete("segment");
    else next.set("segment", token);
    setSearchParams(next, { replace: true });
  }, [token, searchParams, setSearchParams]);

  /* The editor opens on the biggest language in the audience — `byLanguage` is the server's own
     order — and follows the list if the audience changes underneath it. */
  useEffect(() => {
    setLanguage((current) =>
      current !== null && languages.includes(current) ? current : (languages[0] ?? null),
    );
  }, [languages]);

  const expectedAudienceSize = previewView?.matched ?? null;
  /* What a send will actually attempt: the reachable complement before the freeze, and the rows
     the expansion wrote after it. Never a sum of the overlapping skips. */
  const audienceCount = campaign?.progress.recipientCount ?? previewView?.reachable ?? 0;

  const drift = audienceDriftOf(failureOf(create.error));
  const conflictState = broadcastStateConflictOf(failureOf(send.error));
  const stepUpTarget =
    stepUpTargetOf(failureOf(send.error)) ?? stepUpTargetOf(failureOf(testSend.error));

  /* ---------------------------------------------------------------------- */
  /* The two calls                                                           */
  /* ---------------------------------------------------------------------- */

  /**
   * The campaign this wizard is composing — created once, revised thereafter.
   *
   * Returns `null` when the call was refused; the refusal is already on `create.error` or
   * `revise.error` and is rendered where the operator pressed.
   */
  async function ensureCampaign(): Promise<string | null> {
    const signature = compositionSignature(draft, languages);
    const existing = campaignIdRef.current;
    try {
      if (existing === null) {
        const detail = await create.mutateAsync(
          createRequestOf(draft, languages, insistRef.current ? null : expectedAudienceSize),
        );
        campaignIdRef.current = detail.broadcast.id;
        setCampaign(detail.broadcast);
        setFrozenLanguages(languages);
        syncedRef.current = signature;
        insistRef.current = false;
        return detail.broadcast.id;
      }
      if (syncedRef.current !== signature) {
        const detail = await revise.mutateAsync({
          broadcastId: existing,
          body: reviseRequestOf(draft, languages),
        });
        setCampaign(detail.broadcast);
        syncedRef.current = signature;
      }
      return existing;
    } catch {
      // Every failure here is already an `AdminQueryError` on the mutation that produced it.
      return null;
    }
  }

  async function runSend(body: BroadcastSendRequest): Promise<void> {
    const broadcastId = await ensureCampaign();
    if (broadcastId === null) return;
    pendingRef.current = { kind: "send", body };
    try {
      await send.mutateAsync({ broadcastId, body });
      navigate(broadcastDetailPath(broadcastId));
    } catch {
      // A step-up refusal is not an error to report: the dialog below picks it up and the same
      // body is replayed on the grant.
    }
  }

  async function runTestSend(body: BroadcastTestSendRequest): Promise<void> {
    const broadcastId = await ensureCampaign();
    if (broadcastId === null) return;
    pendingRef.current = { kind: "test", body };
    try {
      const result = await testSend.mutateAsync({ broadcastId, body });
      setTestResult(result);
    } catch {
      // As above.
    }
  }

  function replay(): void {
    const held = pendingRef.current;
    if (held === null) return;
    if (held.kind === "send") void runSend(held.body);
    else void runTestSend(held.body);
  }

  /* ---------------------------------------------------------------------- */
  /* The frame                                                               */
  /* ---------------------------------------------------------------------- */

  if (!canWrite) {
    return (
      <WizardFrame>
        <Panel title={t("broadcasts.wizard.readOnlyTitle")}>
          <p className="m-0 text-[13px] text-ink-500">{t("broadcasts.wizard.readOnlyMessage")}</p>
        </Panel>
      </WizardFrame>
    );
  }

  const canLeaveAudience = audienceBlock === null;
  const canLeaveMessage = canLeaveAudience && messageBlock === null;
  const canEnter: Readonly<Record<WizardStep, boolean>> = {
    audience: true,
    message: canLeaveAudience,
    review: canLeaveMessage,
  };
  const forward = nextStep(step);
  const backward = previousStep(step);
  const canGoForward =
    forward !== null && (step === "audience" ? canLeaveAudience : canLeaveMessage);

  return (
    <WizardFrame>
      <Toolbar
        title={t("broadcasts.wizard.title")}
        subtitle={t("broadcasts.wizard.subtitle")}
        titleAs="h1"
      />

      <ol
        aria-label={t("broadcasts.wizard.stepsAria")}
        className="m-0 flex list-none flex-wrap gap-2 p-0"
      >
        {WIZARD_STEPS.map((entry) => {
          const isCurrent = entry === step;
          const isReachable = canEnter[entry];
          return (
            <li key={entry}>
              <button
                type="button"
                onClick={() => {
                  setStep(entry);
                }}
                disabled={!isReachable}
                aria-current={isCurrent ? "step" : undefined}
                className={cn(
                  "rounded-field border px-3 py-2 text-[13px] font-semibold outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50",
                  isCurrent
                    ? "border-accent-deep bg-accent-12 text-ink-900"
                    : "border-stroke bg-card text-ink-500",
                )}
              >
                {t("broadcasts.wizard.stepOf", {
                  index: stepIndex(entry) + 1,
                  total: WIZARD_STEPS.length,
                  name: t(STEP_NAME_KEY[entry]),
                })}
              </button>
            </li>
          );
        })}
      </ol>

      {campaign === null ? null : (
        <p role="status" className="m-0 rounded-field bg-accent/10 p-3 text-[13px] text-ink-800">
          {t("broadcasts.wizard.createdNote", {
            count: formatCount(campaign.progress.recipientCount),
          })}{" "}
          <Link to={broadcastDetailPath(campaign.id)} className="font-semibold underline">
            {t("broadcasts.wizard.createdLink")}
          </Link>
        </p>
      )}

      {step === "audience" ? (
        <AudienceStep
          value={draft.segment}
          onChange={(segment: Segment) => {
            setDraft((current) => ({ ...current, segment }));
          }}
          registry={registryView}
          isRegistryPending={registry.isPending}
          registryError={registryError}
          preview={previewView}
          isPreviewPending={preview.isFetching}
          previewError={previewError}
          isFrozen={isFrozen}
          refusal={audienceBlock}
        />
      ) : null}

      {step === "message" ? (
        <MessageStep
          draft={draft}
          onChange={setDraft}
          languages={languages}
          language={language}
          onLanguageChange={setLanguage}
          preview={previewView}
          refusal={messageBlock}
          onTestSend={
            messageBlock === null
              ? () => {
                  setTestResult(null);
                  setIsTestOpen(true);
                }
              : null
          }
          isTestSendPending={testSend.isPending}
        />
      ) : null}

      {step === "review" ? (
        <ReviewStep
          draft={draft}
          languages={languages}
          fieldIndex={fieldIndex}
          audienceCount={audienceCount}
          isAudienceFrozen={isFrozen}
          frozenAt={campaign?.audienceEvaluatedAt ?? null}
          onSubmit={(body) => {
            void runSend(body);
          }}
          isPending={create.isPending || revise.isPending || send.isPending}
          notice={
            <SubmitNotice
              drift={
                drift === null
                  ? null
                  : {
                      ...drift,
                      onReview: () => {
                        create.reset();
                        setStep("audience");
                      },
                      onInsist: () => {
                        insistRef.current = true;
                        create.reset();
                      },
                    }
              }
              conflictLabel={
                conflictState === null ? null : t(BROADCAST_STATE_LABEL_KEY[conflictState])
              }
              error={
                stepUpTarget !== null || drift !== null || conflictState !== null
                  ? null
                  : (errorOf(create.error) ?? errorOf(revise.error) ?? errorOf(send.error))
              }
            />
          }
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {backward === null ? null : (
          <button
            type="button"
            onClick={() => {
              setStep(backward);
            }}
            className="rounded-field border border-stroke bg-card px-4 py-2.5 text-[13px] font-semibold text-ink-800 outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {t("broadcasts.wizard.back")}
          </button>
        )}
        {forward === null ? null : (
          <button
            type="button"
            onClick={() => {
              setStep(forward);
            }}
            disabled={!canGoForward}
            className="rounded-button bg-accent px-4 py-2.5 text-[13px] font-semibold text-on-accent outline-none transition-[filter] hover:brightness-95 focus-visible:ring-2 focus-visible:ring-accent-deep disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("broadcasts.wizard.next", { name: t(STEP_NAME_KEY[forward]) })}
          </button>
        )}
      </div>

      <TestSendDialog
        isOpen={isTestOpen && stepUpTarget === null}
        onClose={() => {
          setIsTestOpen(false);
          testSend.reset();
        }}
        willFreezeAudience={!isFrozen}
        isPending={create.isPending || revise.isPending || testSend.isPending}
        result={testResult}
        error={
          stepUpTarget !== null ? undefined : (
            <TestSendFailure
              error={errorOf(testSend.error) ?? errorOf(create.error) ?? errorOf(revise.error)}
            />
          )
        }
        onConfirm={(body) => {
          void runTestSend(body);
        }}
      />

      <StepUpDialog
        isOpen={stepUpTarget !== null}
        /* Cancelling returns to the form with the instant, the reason and the message intact. */
        onClose={() => {
          send.reset();
          testSend.reset();
        }}
        action={stepUpTarget?.action ?? "broadcast.send"}
        /* VERBATIM from the refusal: the campaign UUID as the handler compared it. */
        subjectId={stepUpTarget?.subjectId ?? campaignIdRef.current ?? ""}
        subjectLabel={draft.title}
        note={t("broadcasts.wizard.review.stepUpNote")}
        onGranted={replay}
      />
    </WizardFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Frame                                                                       */
/* -------------------------------------------------------------------------- */

function WizardFrame({ children }: { readonly children: ReactNode }): JSX.Element {
  const { t } = useI18n();
  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-4">
        <Link
          to={PATH.broadcasts}
          className={cn(
            "inline-flex w-fit items-center gap-1 rounded text-[12px] font-semibold text-ink-500",
            "outline-none hover:text-ink-800 focus-visible:ring-2 focus-visible:ring-accent",
          )}
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          {t("broadcasts.detail.backToList")}
        </Link>
        {children}
      </div>
    </main>
  );
}

/* -------------------------------------------------------------------------- */
/* Failures                                                                    */
/* -------------------------------------------------------------------------- */

/** An aborted read is not a refusal; it is this screen having asked a newer question. */
function errorOf(error: AdminQueryError | null): AdminQueryError | null {
  return error !== null && error.code !== CLIENT_ERROR_CODES.aborted ? error : null;
}

interface DriftCopy {
  readonly expectedAudienceSize: number;
  readonly audienceSize: number;
  readonly onReview: () => void;
  readonly onInsist: () => void;
}

function SubmitNotice({
  drift,
  conflictLabel,
  error,
}: {
  readonly drift: DriftCopy | null;
  readonly conflictLabel: string | null;
  readonly error: AdminQueryError | null;
}): JSX.Element | null {
  const { t } = useI18n();

  if (drift !== null) {
    return (
      <div className="flex flex-col gap-2 rounded-field border border-stroke bg-warn-18 p-3">
        <p className="m-0 text-[13px] font-semibold text-warn-deep">
          {t("broadcasts.wizard.review.driftTitle")}
        </p>
        <p className="m-0 text-[13px] text-ink-800">
          {t("broadcasts.wizard.review.driftMessage", {
            expected: formatCount(drift.expectedAudienceSize),
            actual: formatCount(drift.audienceSize),
          })}
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={drift.onReview}
            className="rounded-field border border-stroke bg-card px-3 py-2 text-[13px] font-semibold text-ink-800 outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {t("broadcasts.wizard.review.driftReview")}
          </button>
          <button
            type="button"
            onClick={drift.onInsist}
            className="rounded-field border border-stroke bg-card px-3 py-2 text-[13px] font-semibold text-ink-800 outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {t("broadcasts.wizard.review.driftInsist", {
              count: formatCount(drift.audienceSize),
            })}
          </button>
        </div>
      </div>
    );
  }

  if (conflictLabel !== null) {
    return (
      <ErrorNote
        tone="error"
        title={t("broadcasts.conflict.title")}
        message={t("broadcasts.conflict.message", { state: conflictLabel })}
        retryable={false}
      />
    );
  }

  if (error === null) return null;
  return <Failure error={error} subjectKey="broadcasts.wizard.subject" />;
}

function TestSendFailure({ error }: { readonly error: AdminQueryError | null }): JSX.Element | null {
  const { t } = useI18n();
  if (error === null) return null;
  if (error.code === "FORBIDDEN") {
    return (
      <ErrorNote
        tone="denied"
        title={t("broadcasts.wizard.message.testSend.refusedTitle")}
        message={t("broadcasts.wizard.message.testSend.refusedMessage")}
        retryable={false}
      />
    );
  }
  return <Failure error={error} subjectKey="broadcasts.wizard.message.testSend.subject" />;
}

function Failure({
  error,
  subjectKey,
}: {
  readonly error: AdminQueryError;
  readonly subjectKey: TranslationPath;
}): JSX.Element {
  const { t } = useI18n();
  const note = noteFor(error, false, t, t(subjectKey));
  return (
    <ErrorNote
      tone={note.tone}
      title={note.title}
      message={note.message}
      hint={`${error.endpoint} · ${error.correlationId ?? t("errors.query.noCorrelationId")}`}
      retryable={false}
    />
  );
}
