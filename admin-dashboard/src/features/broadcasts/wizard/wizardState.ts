/**
 * What the wizard is holding, and what it is not allowed to advance past.
 *
 * DOM-free on purpose: every gate below is a predicate over the draft, so the screen decides
 * only when to ask and the catalogue decides only how to say it. Three properties are worth
 * stating before the types.
 *
 * **The audience is a document until it is frozen, and then it is history.** `POST /api/broadcasts`
 * materialises the recipient rows, so the moment a campaign id exists the segment in this draft
 * is no longer a filter that can be edited — it is what a fixed population WAS selected by. The
 * screen renders the builder `disabled` from that point, and this module's gates stop asking
 * about it.
 *
 * **The body set is per language, and the languages are the AUDIENCE's.** `GET /api/segments/
 * preview` publishes `byLanguage`, and one body per language present is exactly what the server
 * accepts (`MAX_BODIES = len(Language)`, one per language, at least one). Writing a body for a
 * language nobody in the audience reads is work that reaches nobody; omitting one that somebody
 * does read is a person who gets nothing, so both are refused here rather than discovered.
 *
 * **Every refusal is the server's, restated where a form can apply it.** `bodyIssues` walks the
 * same rules `BroadcastBodyInput` validates in the same order — the markup allowlist, the two
 * length ceilings measured on both strings, the button pair, the URL, the storage key — so an
 * operator meets them beside the field that caused them instead of as a 422 naming `bodies.0`.
 */

import { MAX_BROADCAST_TITLE_CHARS } from "@/api/constants";
import {
  broadcastBodyLimit,
  isButtonPair,
  isTelegramButtonUrl,
  type BroadcastBodyInput,
  type BroadcastCreateRequest,
  type BroadcastKind,
  type BroadcastReviseRequest,
  type Language,
} from "@/api/broadcasts";
import type { SegmentPreviewView } from "@/api/segments";
import type { Segment } from "@/lib/segmentCodec";

import {
  codePointLength,
  isMediaStorageKey,
  scanBody,
  type BodyIssueCode,
  type BodyScan,
} from "./bodyMarkup";

/* -------------------------------------------------------------------------- */
/* The three steps                                                             */
/* -------------------------------------------------------------------------- */

/** Filter the people, compose the message, read it back and send. The operator's own order. */
export const WIZARD_STEPS = ["audience", "message", "review"] as const;
export type WizardStep = (typeof WIZARD_STEPS)[number];

export function stepIndex(step: WizardStep): number {
  return WIZARD_STEPS.indexOf(step);
}

export function nextStep(step: WizardStep): WizardStep | null {
  return WIZARD_STEPS[stepIndex(step) + 1] ?? null;
}

export function previousStep(step: WizardStep): WizardStep | null {
  const index = stepIndex(step);
  return index <= 0 ? null : (WIZARD_STEPS[index - 1] ?? null);
}

/* -------------------------------------------------------------------------- */
/* The draft                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One language's message as it is being TYPED — four strings, never nulls.
 *
 * A form field holds `""` and the wire holds `null`; {@link bodyInputOf} is the one place the
 * two meet, so an empty box is never sent as an empty string the server would measure.
 */
export interface BodyDraft {
  readonly text: string;
  readonly mediaStorageKey: string;
  readonly buttonLabel: string;
  readonly buttonUrl: string;
}

export const EMPTY_BODY: BodyDraft = {
  text: "",
  mediaStorageKey: "",
  buttonLabel: "",
  buttonUrl: "",
};

export interface WizardDraft {
  /** The audience, while it is still a filter. Frozen by the create and never edited after. */
  readonly segment: Segment;
  readonly title: string;
  readonly kind: BroadcastKind;
  /** Sparse: a language the audience does not read has no entry and needs none. */
  readonly bodies: Readonly<Partial<Record<Language, BodyDraft>>>;
}

export function bodyAt(draft: WizardDraft, language: Language): BodyDraft {
  return draft.bodies[language] ?? EMPTY_BODY;
}

export function withBody(draft: WizardDraft, language: Language, body: BodyDraft): WizardDraft {
  return { ...draft, bodies: { ...draft.bodies, [language]: body } };
}

/* -------------------------------------------------------------------------- */
/* The refusals                                                                */
/* -------------------------------------------------------------------------- */

export interface BodyIssue {
  readonly code: BodyIssueCode;
  /** The ceiling this body was measured against — 4 096, or 1 024 once an image is attached. */
  readonly limit?: number | undefined;
  /** The larger of the raw and rendered lengths, which is the one that will be refused. */
  readonly actual?: number | undefined;
}

/**
 * Every rule `BroadcastBodyInput` applies, in the order it applies them.
 *
 * The length check is the one worth reading twice: it measures the RAW text and the RENDERED
 * text against the same ceiling and reports the larger, because that is what the server does and
 * because the two differ by however much markup and however many ampersands the operator typed.
 */
export function bodyIssues(body: BodyDraft): readonly BodyIssue[] {
  const issues: BodyIssue[] = [];
  const hasMedia = body.mediaStorageKey.trim() !== "";
  const limit = broadcastBodyLimit(hasMedia);

  if (body.text === "") {
    issues.push({ code: "empty" });
  } else {
    const scan = scanBody(body.text);
    if (!scan.ok) {
      issues.push({ code: scan.code });
    } else if (scan.literal.trim() === "") {
      issues.push({ code: "blankText" });
    }
    const rawLength = codePointLength(body.text);
    const renderedLength = scan.ok ? scan.renderedLength : rawLength;
    const actual = Math.max(rawLength, renderedLength);
    if (actual > limit) issues.push({ code: "tooLong", limit, actual });
  }

  if (hasMedia && !isMediaStorageKey(body.mediaStorageKey.trim())) {
    issues.push({ code: "badStorageKey" });
  }

  const label = body.buttonLabel.trim() === "" ? null : body.buttonLabel;
  const url = body.buttonUrl.trim() === "" ? null : body.buttonUrl;
  if (!isButtonPair(label, url)) issues.push({ code: "buttonPair" });
  if (url !== null && !isTelegramButtonUrl(url.trim())) issues.push({ code: "badUrl" });

  return issues;
}

/** The scan a message editor renders its counter and its preview from. */
export function bodyScan(body: BodyDraft): BodyScan {
  return scanBody(body.text);
}

/** 4 096, or 1 024 the moment an image is attached — a caption is a quarter of a message. */
export function bodyLimitOf(body: BodyDraft): number {
  return broadcastBodyLimit(body.mediaStorageKey.trim() !== "");
}

/* -------------------------------------------------------------------------- */
/* The gates                                                                   */
/* -------------------------------------------------------------------------- */

/** Why the audience step will not let go. `null` is "it will". */
export type AudienceRefusal = "counting" | "invalid" | "nobody" | "unreadable";

/**
 * Whether this audience may be committed to.
 *
 * **`reachable`, never a sum.** `matched`, `skippedBlocked` and `skippedBotBlocked` overlap —
 * ours and the customer's bars can both be on one account — so only `reachable` is the
 * complement, and it is the number a send would actually attempt. An audience of forty thousand
 * matched and nobody reachable is an audience of nobody.
 */
export function audienceRefusal(options: {
  readonly isSegmentValid: boolean;
  readonly isRegistryReadable: boolean;
  readonly preview: SegmentPreviewView | null;
}): AudienceRefusal | null {
  if (!options.isRegistryReadable) return "unreadable";
  if (!options.isSegmentValid) return "invalid";
  if (options.preview === null) return "counting";
  return options.preview.reachable > 0 ? null : "nobody";
}

/** The languages a body must be written for: the ones the audience actually reads. */
export function audienceLanguagesOf(preview: SegmentPreviewView | null): readonly Language[] {
  return preview === null ? [] : preview.byLanguage.map((entry) => entry.language);
}

/** Why the message step will not let go. `null` is "it will". */
export interface MessageRefusal {
  readonly isTitleMissing: boolean;
  readonly isTitleTooLong: boolean;
  /** Keyed by language: every language the audience reads that is not composed yet. */
  readonly blocking: readonly Language[];
}

export function messageRefusal(
  draft: WizardDraft,
  languages: readonly Language[],
): MessageRefusal | null {
  const isTitleMissing = draft.title.trim() === "";
  const isTitleTooLong = codePointLength(draft.title) > MAX_BROADCAST_TITLE_CHARS;
  const blocking = languages.filter((language) => bodyIssues(bodyAt(draft, language)).length > 0);
  if (!isTitleMissing && !isTitleTooLong && blocking.length === 0 && languages.length > 0) {
    return null;
  }
  return { isTitleMissing, isTitleTooLong, blocking };
}

/* -------------------------------------------------------------------------- */
/* The requests                                                                */
/* -------------------------------------------------------------------------- */

export function bodyInputOf(language: Language, body: BodyDraft): BroadcastBodyInput {
  const key = body.mediaStorageKey.trim();
  const label = body.buttonLabel.trim();
  const url = body.buttonUrl.trim();
  return {
    language,
    // VERBATIM. Every check reads the operator's text and none of them rewrites it; the trim
    // above is for the three fields that are identifiers, not for the message.
    text: body.text,
    mediaStorageKey: key === "" ? null : key,
    buttonLabel: label === "" ? null : label,
    buttonUrl: url === "" ? null : url,
  };
}

export function bodyInputsOf(
  draft: WizardDraft,
  languages: readonly Language[],
): readonly BroadcastBodyInput[] {
  return languages.map((language) => bodyInputOf(language, bodyAt(draft, language)));
}

/**
 * The call that decides WHO, and the only one that carries the drift catch.
 *
 * `expectedAudienceSize` is the number the operator was shown. The server compares it with what
 * the segment counts now and refuses when the world has moved too far — which is the whole
 * reason the review step restates a count rather than trusting the one from three minutes ago.
 */
export function createRequestOf(
  draft: WizardDraft,
  languages: readonly Language[],
  expectedAudienceSize: number | null,
): BroadcastCreateRequest {
  return {
    title: draft.title,
    kind: draft.kind,
    segment: draft.segment,
    bodies: [...bodyInputsOf(draft, languages)],
    expectedAudienceSize,
  };
}

/**
 * The title and the WHOLE body set, replaced together.
 *
 * A partial set deletes the languages it omits, so this is always built from the same language
 * list the create used. There is no segment and no kind here: changing who hears a message is a
 * different campaign, not an edit.
 */
export function reviseRequestOf(
  draft: WizardDraft,
  languages: readonly Language[],
): BroadcastReviseRequest {
  return { title: draft.title, bodies: [...bodyInputsOf(draft, languages)] };
}

/**
 * What was last sent to the server, as one comparable string.
 *
 * The wizard revises a frozen campaign only when the composition actually changed — a test send
 * pressed twice on the same text must not write a second revision, and an operator who went back
 * to fix a typo must not send a test of the old one.
 */
export function compositionSignature(
  draft: WizardDraft,
  languages: readonly Language[],
): string {
  return JSON.stringify([draft.title, bodyInputsOf(draft, languages)]);
}
