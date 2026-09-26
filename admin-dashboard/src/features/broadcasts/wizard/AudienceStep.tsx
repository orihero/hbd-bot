/**
 * Step 1 — who hears this, decided before anything is written.
 *
 * ## The count is the thing being approved, and it is `reachable`
 *
 * `matched`, `skippedBlocked` and `skippedBotBlocked` overlap: the first is everyone the document
 * selects, the second the accounts we barred, the third the accounts that blocked the bot, and
 * one person can be in both bars. Only `reachable` is the complement, so it is what the step
 * gates on and what the review restates. The two skips are drawn as REASONS underneath and never
 * added to anything.
 *
 * ## An empty document is everyone, said before the freeze and not after
 *
 * The root may legally carry no rules, and that is the whole database rather than "nothing
 * selected". The builder says so in its own words; this step says it again in warning tone,
 * because the next button an operator presses freezes it.
 *
 * ## The sample is the Users list, not a second projection
 *
 * `GET /api/segments/preview` answers with counts and deliberately no rows — a second,
 * differently-masked projection of a customer would be a second thing to keep true. So "show me
 * who this is" is answered by the SAME `?segment=` token against `GET /api/users`, the same
 * compiler, the same permission and the same masked columns the directory shows. It is behind a
 * disclosure and it asks for five rows: a sanity check is a handful of accounts an operator
 * recognises, and a page of fifty here would be a membership list of the audience they are about
 * to message.
 */

import { useState, type JSX } from "react";

import { DEFAULT_PAGE_LIMIT } from "@/api/pagination";
import type { SegmentFieldsView, SegmentPreviewView } from "@/api/segments";
import type { UserView } from "@/api/users";
import { CELL_SECONDARY_CLASS, DataTable, type Column } from "@/components/DataTable";
import { ErrorNote } from "@/components/ErrorNote";
import { SegmentBuilder } from "@/components/SegmentBuilder";
import { Skeleton } from "@/components/Skeleton";
import { formatAbsolute, formatCount, type Translate } from "@/features/broadcasts/broadcastFormat";
import { Panel } from "@/features/users/detailKit";
import { useUsers } from "@/features/users/useUsers";
import { useI18n } from "@/i18n";
import type { TranslationPath } from "@/i18n/types";
import type { AdminQueryError } from "@/lib/adminQuery";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";
import { isSegmentEmpty, segmentToken, type Segment } from "@/lib/segmentCodec";

import type { AudienceRefusal } from "./wizardState";

/** Five rows: enough to recognise the audience, far short of enumerating it. */
export const AUDIENCE_SAMPLE_LIMIT = 5;

const REFUSAL_KEY: Readonly<Record<AudienceRefusal, TranslationPath>> = {
  counting: "broadcasts.wizard.audience.refusalCounting",
  invalid: "broadcasts.wizard.audience.refusalInvalid",
  nobody: "broadcasts.wizard.audience.refusalNobody",
  unreadable: "broadcasts.wizard.audience.refusalUnreadable",
};

export interface AudienceStepProps {
  readonly value: Segment;
  readonly onChange: (next: Segment) => void;
  readonly registry: SegmentFieldsView | null;
  readonly isRegistryPending: boolean;
  readonly registryError: AdminQueryError | null;
  readonly preview: SegmentPreviewView | null;
  readonly isPreviewPending: boolean;
  readonly previewError: AdminQueryError | null;
  /** True once the campaign exists: the audience is history and the builder is read-only. */
  readonly isFrozen: boolean;
  readonly refusal: AudienceRefusal | null;
}

export function AudienceStep({
  value,
  onChange,
  registry,
  isRegistryPending,
  registryError,
  preview,
  isPreviewPending,
  previewError,
  isFrozen,
  refusal,
}: AudienceStepProps): JSX.Element {
  const { t } = useI18n();

  return (
    <Panel
      title={t("broadcasts.wizard.audience.heading")}
      caption={t("broadcasts.wizard.audience.caption")}
    >
      {isFrozen ? (
        <p role="status" className="m-0 rounded-field bg-accent/10 p-3 text-[13px] text-ink-800">
          {t("broadcasts.wizard.audience.frozenLocked")}
        </p>
      ) : null}

      {isSegmentEmpty(value) ? (
        <p className="m-0 rounded-field bg-warn-18 p-3 text-[13px] font-semibold text-warn-deep">
          {t("broadcasts.wizard.audience.everyoneWarning")}
        </p>
      ) : null}

      {registryError !== null ? (
        <ErrorNote
          tone={registryError.code === "FORBIDDEN" ? "denied" : "error"}
          title={t("broadcasts.wizard.audience.registryFailedTitle")}
          message={
            registryError.code === "FORBIDDEN"
              ? t("broadcasts.wizard.audience.registryForbidden")
              : registryError.message
          }
          retryable={false}
        />
      ) : null}

      {registry === null ? (
        isRegistryPending ? (
          <div className="flex flex-col gap-2" aria-busy>
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : null
      ) : (
        <SegmentBuilder
          value={value}
          onChange={onChange}
          fields={registry.fields}
          limits={registry.limits}
          version={registry.version}
          /* A campaign's order is the sender's: there is no page to walk and nothing to sort. */
          showSort={false}
          showFreezeNote
          disabled={isFrozen}
          label={t("broadcasts.wizard.audience.builderLabel")}
          preview={
            <AudienceCount
              preview={preview}
              isPending={isPreviewPending}
              error={previewError}
              t={t}
            />
          }
        />
      )}

      {refusal === null ? null : (
        <p role="status" className="m-0 text-[13px] font-medium text-required-deep">
          {t(REFUSAL_KEY[refusal])}
        </p>
      )}

      {isFrozen || registry === null ? null : <AudienceSampleDisclosure segment={value} />}
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* The count                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * The exact audience, and what it is not.
 *
 * Exact, because the list's bounded total saturates at `TOTAL_COUNT_CAP` and "10,000+" is a
 * refusal to answer rather than an approximation — nobody can approve a campaign against a
 * ceiling. `aria-live="polite"` so the number a debounce moved is announced rather than silently
 * replaced under a screen reader.
 */
function AudienceCount({
  preview,
  isPending,
  error,
  t,
}: {
  readonly preview: SegmentPreviewView | null;
  readonly isPending: boolean;
  readonly error: AdminQueryError | null;
  readonly t: Translate;
}): JSX.Element {
  if (error !== null) {
    return (
      <p className="m-0 text-[13px] text-required-deep">
        {error.code === "FORBIDDEN"
          ? t("broadcasts.wizard.audience.countForbidden")
          : t("broadcasts.wizard.audience.countFailed", { message: error.message })}
      </p>
    );
  }

  if (preview === null) {
    return (
      <p className="m-0 text-[13px] text-ink-400">{t("broadcasts.wizard.audience.counting")}</p>
    );
  }

  return (
    <div className="flex flex-col gap-1" aria-live="polite" aria-busy={isPending}>
      <p className="m-0 text-[14px] font-semibold leading-5 tracking-[-0.084px] text-ink-800">
        {t("broadcasts.wizard.audience.reachable", {
          count: formatCount(preview.reachable),
        })}
      </p>
      <p className="m-0 text-[12px] leading-4 text-ink-400">
        {t("broadcasts.wizard.audience.matched", {
          matched: formatCount(preview.matched),
          blocked: formatCount(preview.skippedBlocked),
          botBlocked: formatCount(preview.skippedBotBlocked),
        })}
      </p>
      {preview.byLanguage.length === 0 ? null : (
        <p className="m-0 text-[12px] leading-4 text-ink-400">
          {t("broadcasts.wizard.audience.byLanguage", {
            split: preview.byLanguage
              .map(
                (entry) =>
                  `${t(LANGUAGE_LABEL_KEY[entry.language])} ${formatCount(entry.count)}`,
              )
              .join(" · "),
          })}
        </p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The sample                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * "Show me five of them" — mounted only when asked, because mounting IS the request.
 *
 * The disclosure is what gates the query: `useUsers` fires as soon as it is rendered, so the
 * child is not rendered until the operator asks. That keeps a plain visit to the wizard down to
 * the registry and the count, and it keeps a list of identified accounts off a screen nobody
 * asked to see one on.
 */
function AudienceSampleDisclosure({ segment }: { readonly segment: Segment }): JSX.Element {
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => {
          setIsOpen((current) => !current);
        }}
        aria-expanded={isOpen}
        aria-controls="wizard-audience-sample"
        className="w-fit rounded-field border border-stroke bg-card px-3 py-2 text-[13px] font-semibold text-ink-800 outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {isOpen
          ? t("broadcasts.wizard.audience.sampleHide")
          : t("broadcasts.wizard.audience.sampleShow")}
      </button>
      <div id="wizard-audience-sample" hidden={!isOpen}>
        {isOpen ? <AudienceSample segment={segment} /> : null}
      </div>
    </div>
  );
}

function AudienceSample({ segment }: { readonly segment: Segment }): JSX.Element {
  const { t } = useI18n();
  const token = segmentToken(segment);
  const sample = useUsers(
    { segment: token, withTotal: false },
    { limit: AUDIENCE_SAMPLE_LIMIT },
  );

  const columns: readonly Column<UserView>[] = [
    {
      key: "account",
      header: t("broadcasts.wizard.audience.sampleAccount"),
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-800">{row.telegramUserIdMasked}</span>
      ),
    },
    {
      key: "language",
      header: t("broadcasts.wizard.audience.sampleLanguage"),
      render: (row) => t(LANGUAGE_LABEL_KEY[row.uiLanguage]),
    },
    {
      key: "joined",
      header: t("broadcasts.wizard.audience.sampleJoined"),
      render: (row) => (
        <span className={CELL_SECONDARY_CLASS}>{formatAbsolute(row.accountCreatedAt)}</span>
      ),
    },
  ];

  if (sample.error !== null) {
    return (
      <p className="m-0 text-[13px] text-required-deep">
        {t("broadcasts.wizard.audience.sampleFailed", { message: sample.error.message })}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-[12px] leading-4 text-ink-400">
        {t("broadcasts.wizard.audience.sampleCaption", { count: AUDIENCE_SAMPLE_LIMIT })}
      </p>
      <DataTable
        columns={columns}
        rows={sample.data?.items ?? []}
        getRowKey={(row) => row.id}
        isLoading={sample.isPending}
        skeletonRows={AUDIENCE_SAMPLE_LIMIT}
        caption={t("broadcasts.wizard.audience.sampleCaption", { count: AUDIENCE_SAMPLE_LIMIT })}
        emptyMessage={t("broadcasts.wizard.audience.sampleEmpty")}
      />
      <p className="m-0 text-[12px] leading-4 text-ink-400">
        {t("broadcasts.wizard.audience.sampleNote", { limit: DEFAULT_PAGE_LIMIT })}
      </p>
    </div>
  );
}
