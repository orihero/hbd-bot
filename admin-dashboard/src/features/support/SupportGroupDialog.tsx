/**
 * **Where ticket cards are posted** — the surface that replaced an environment variable.
 *
 * Until today the support group was `BAYRAM_SUPPORT_GROUP_CHAT_ID`, which meant a redeploy to
 * change and a value nobody in the console could read. This lists every chat the bot knows it is
 * in, says which one receives the cards, and lets an ADMIN or an OWNER move it.
 *
 * ## A dialog, not a screen — decided, not defaulted
 *
 * A route under `/support/groups` was the alternative and it was rejected on three counts, one
 * of them mechanical. **Where the question is asked:** "where do my tickets go?" is asked while
 * looking at the board, usually because a card did not arrive, and a surface that answers it
 * without leaving the board answers it at the moment it is asked. **What the surface is:** this
 * is configuration performed once and then not again for months — a nav entry would put a
 * permanent item in front of every VIEWER for a screen they may look at twice a year, and the
 * sidebar is the console's scarcest space. **And the mechanical half:** a route costs an entry
 * in `app/paths.ts`, one in `routes.tsx` and one in `app/navItems.ts`, three files shared with
 * every other feature in flight, to buy a URL nobody would ever paste to a colleague. A dialog
 * costs one button on the toolbar that already owns this section.
 *
 * What a dialog gives up is deep-linking and browser history, and both are worth naming: an
 * operator cannot send "look at this" as a link, and Escape closes rather than going back. If
 * this surface ever grows a per-chat detail view, that is the point at which it should become a
 * route — one screen with a list and a panel — rather than a dialog with a second dialog in it.
 *
 * It is hand-rolled rather than built on `ConfirmDialog`, which every other privileged act in
 * this console uses. That component is a ONE-VERB confirmation: a required `confirmLabel`, a
 * single `onConfirm`, an optional reason field, and the rule that nothing closes while a request
 * is in flight. This surface has as many verbs as there are rows, plus a paste form and a clear,
 * and no single action to name on a footer button. Bending `ConfirmDialog` into a
 * no-confirm-button mode would change a component four §9.2 writes depend on, to serve one
 * caller. The a11y contract is not given up with it — focus moves in, focus is trapped, Escape
 * closes, focus returns to the toolbar button — because that contract is the reason the
 * component exists, not an ornament on it.
 *
 * ## The one thing this screen must never do
 *
 * **It must not report a selection as working.** The admin process holds no bot token
 * (`ADMIN_PANEL_PLAN D10 / §4.2`); a Select is a database write plus an ARQ job, and whether the
 * bot can actually post in that room is a question only the worker can answer, seconds later, by
 * posting a message into it. So a row moves to *checking…* and stays there until `verifiedAt` or
 * `verificationError` says otherwise. A dialog that showed a green tick the moment the POST
 * returned would be strictly worse than the environment variable it replaces: the env var never
 * claimed to have been checked.
 *
 * Three consequences of that run through the whole file:
 *
 *  1. **The badge is driven by `verifiedAt`/`verificationError`, never by `botStatus`.**
 *     `verificationStateOf` is the only thing allowed to decide it. `botStatus` is what Telegram
 *     last said at the instant it said it — an administrator can lose `can_post_messages` with
 *     no membership transition sent at all — so it is rendered as evidence, in muted ink, beside
 *     a sentence saying so.
 *  2. **`verificationError` is rendered verbatim and in full.** It is English operator prose
 *     written by the worker, never a catalogue key: there is nothing to map it to, and the
 *     migrated-group message CONTAINS THE GROUP'S NEW CHAT ID as a bare number an operator
 *     copies straight back into the paste field below it. That is the entire recovery path for a
 *     group Telegram upgraded under us, so the row wraps rather than truncates.
 *  3. **A 503 is not a failed write.** The handler commits and then enqueues, so "no worker"
 *     means the inbox HAS moved and nothing will check it. The note says exactly that.
 *
 * ## `threadId` travels with the selection
 *
 * `select_support_group` sets `thread_id` from the request on every call, so a re-select without
 * it CLEARS the topic. Every Select button here therefore sends the row's own `threadId` back,
 * and says so on the button when there is one — a form that dropped the field meaning "leave it
 * alone" would move the inbox out of the topic staff are reading. Changing the topic is done
 * from the paste form, which is where both halves of the value are in one place.
 *
 * ## Read is `support.read`; the controls are `support.group.write`
 *
 * Every role sees the directory and the verification state, because "where do my tickets go?"
 * must be answerable by the operator working the queue. A role without the write cell gets no
 * Select buttons, no paste field and no Clear — absent, not disabled, because a press would be a
 * 403 and a `permission.denied` audit row against somebody who did nothing wrong — and one
 * sentence naming the permission they lack. That sentence is this section's own and not the
 * generic `errors.detail.roleCannotTitle`: `support.actions.readOnly` is the precedent, and the
 * only reason to print a line there at all is to name the thing that is missing.
 */

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";

import {
  parseChatIdInput,
  parseThreadIdInput,
  verificationStateOf,
  type SupportGroupSelectRequest,
  type SupportGroupView,
} from "@/api/support";
import { Badge } from "@/components/Badge";
import { ErrorNote } from "@/components/ErrorNote";
import { ToolbarButton } from "@/components/Toolbar";
import {
  BOT_STATUS_LABEL_KEY,
  BOT_STATUS_TONE,
  CHAT_SOURCE_LABEL_KEY,
  CHAT_SOURCE_HINT_KEY,
  CHAT_SOURCE_TONE,
  CHAT_TYPE_LABEL_KEY,
  VERIFICATION_LABEL_KEY,
  VERIFICATION_TONE,
  chatDisplayName,
  groupNoteFor,
  selectedGroupOf,
} from "@/features/support/groupFormat";
import { formatAbsolute, formatRelative, type Translate } from "@/features/support/ticketFormat";
import {
  useClearSupportGroup,
  useSelectSupportGroup,
  useSupportGroups,
} from "@/features/support/useSupportGroups";
import { useI18n } from "@/i18n";
import { failureOf } from "@/lib/adminQuery";
import { cn } from "@/lib/cn";
import { useCanWriteSupportGroup } from "@/lib/rbac";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

const FIELD_CLASS = [
  "block w-full rounded-field border border-stroke bg-card px-3 py-2",
  "font-mono text-[13px] leading-[18px] text-ink-900",
  "placeholder:font-sans placeholder:text-ink-300",
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep",
  "disabled:cursor-not-allowed disabled:bg-bg",
].join(" ");

const LABEL_CLASS =
  "block text-[12px] font-semibold leading-[16.392px] tracking-[-0.36px] text-label";

const HINT_CLASS = "m-0 mt-1 text-[11px] font-normal leading-[1.35] text-ink-400";

interface SupportGroupDialogProps {
  readonly onClose: () => void;
}

/**
 * **There is no `isOpen` prop, and that is the one place this dialog departs from
 * `ConfirmDialog`'s shape rather than from its behaviour.**
 *
 * `ConfirmDialog` takes `isOpen` and returns `null` when it is false, which is free because that
 * component holds nothing but local state. This one holds a QUERY: an `isOpen` that only skipped
 * the render would still run `useSupportGroups` on every board load, so every operator looking
 * at the Kanban would be fetching a directory nobody asked for. Mounting IS the switch — the
 * caller renders it when open — and unmounting is what tears the query down, restores focus to
 * the toolbar button and unlocks the page behind.
 */
export function SupportGroupDialog({ onClose }: SupportGroupDialogProps): JSX.Element {
  const { t } = useI18n();
  const canWrite = useCanWriteSupportGroup();
  const directory = useSupportGroups();
  const select = useSelectSupportGroup();
  const clear = useClearSupportGroup();

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const ids = useId();
  const titleId = `${ids}-title`;
  const descriptionId = `${ids}-description`;
  const chatFieldId = `${ids}-chat`;
  const threadFieldId = `${ids}-thread`;
  const chatHintId = `${ids}-chat-hint`;
  const threadHintId = `${ids}-thread-hint`;

  const [chatText, setChatText] = useState("");
  const [threadText, setThreadText] = useState("");

  const isPending = select.isPending || clear.isPending;

  /* Remember the trigger and give focus back to it on close, both halves in one effect so they
     cannot drift apart. The trigger is the toolbar button, which is where an operator's eye
     already is. */
  useEffect(() => {
    const active = document.activeElement;
    restoreRef.current = active instanceof HTMLElement ? active : null;
    return () => {
      const trigger = restoreRef.current;
      restoreRef.current = null;
      if (trigger !== null && trigger.isConnected) trigger.focus();
    };
  }, []);

  /* Move focus in — to the first focusable, which is the close button, and never to a Select.
     A stray Enter on open must not repoint the support inbox. */
  useEffect(() => {
    const node = dialogRef.current;
    if (node === null) return;
    const target = node.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    (target ?? node).focus();
  }, []);

  /* Escape, and the focus fence. The fence catches what a Tab-only trap misses: a click on the
     scrim leaves focus on <body>, from where Tab walks back out into the page behind. Escape
     rests while a write is in flight — a Select that closed over its own answer would leave an
     operator unable to read whether the selection moved, was created, or lost a race. */
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent): void {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      if (!isPending) onClose();
    }

    function onFocusIn(event: FocusEvent): void {
      const node = dialogRef.current;
      if (node === null) return;
      const target = event.target;
      if (target instanceof Node && node.contains(target)) return;
      const first = node.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (first ?? node).focus();
    }

    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [isPending, onClose]);

  /* The page behind must not scroll under the scrim. The previous value is restored rather than
     cleared, so a nested overlay does not un-lock the one below it. */
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  const groups = directory.data?.groups ?? [];
  const selected = selectedGroupOf(groups);

  /* One parse, read by the field's validity message, by the Select button's disabled state and
     by the submit itself — so a form that looks submittable and a body the server would refuse
     cannot come apart. `null` means "not a chat id", which includes the blank field. */
  const pastedChatId = parseChatIdInput(chatText);
  const pastedThreadId = parseThreadIdInput(threadText);
  const isChatBlank = chatText.trim() === "";
  const isThreadBlank = threadText.trim() === "";
  const isPasteSubmittable = pastedChatId !== null && (isThreadBlank || pastedThreadId !== null);

  const submit = useCallback(
    (body: SupportGroupSelectRequest) => {
      select.mutate(body);
    },
    [select],
  );

  /* The failure to show, and the read's is only shown when there is nothing on screen: a
     directory that loaded and then failed to refresh is stale, not missing, and the rows below
     are still the last good answer. A write's failure always shows, because it is about
     something the operator just pressed. */
  const writeFailure = failureOf(select.error) ?? failureOf(clear.error);
  const readError = directory.error;
  const note = useMemo(() => {
    if (select.error !== null) return groupNoteFor(select.error, false, t);
    if (clear.error !== null) return groupNoteFor(clear.error, false, t);
    if (readError !== null) return groupNoteFor(readError, groups.length > 0, t);
    return null;
  }, [select.error, clear.error, readError, groups.length, t]);

  function onTabKey(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== "Tab") return;
    const node = dialogRef.current;
    if (node === null) return;
    const focusables = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (first === undefined || last === undefined) {
      event.preventDefault();
      node.focus();
      return;
    }
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === node)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onScrimMouseDown(event: MouseEvent<HTMLDivElement>): void {
    if (event.target !== event.currentTarget) return;
    if (isPending) return;
    onClose();
  }

  return createPortal(
    <div
      onMouseDown={onScrimMouseDown}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-overlay p-4"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={isPending}
        tabIndex={-1}
        onKeyDown={onTabKey}
        className="my-8 w-full max-w-[760px] rounded-panel border border-stroke bg-card p-6 shadow-panel outline-none"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="m-0 text-[22px] font-semibold leading-[30.052px] tracking-[-0.44px] text-ink-900"
            >
              {t("support.groups.title")}
            </h2>
            {/* No subtitle. The heading names the screen and every row below states its own
                condition; a paragraph restating both was three lines an operator scrolled past
                to reach the list they came for. `aria-describedby` points at the one sentence
                that is NOT inferable from the list — the Telegram constraint, below. */}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-3">
            <ToolbarButton
              variant="secondary"
              disabled={directory.isFetching || isPending}
              onClick={() => {
                void directory.refetch();
              }}
            >
              {t("support.groups.refresh")}
            </ToolbarButton>
            <ToolbarButton variant="secondary" disabled={isPending} onClick={onClose}>
              {t("support.groups.close")}
            </ToolbarButton>
          </div>
        </div>

        {/* The constraint, said once and at the top. Everything below it — the unpaged list, the
            paste field, the fact that a group the bot has been in for a year may simply not be
            here — is a consequence of Telegram having no "list my groups" API, and an operator
            who has not been told that reads the missing group as a bug in this panel. */}
        <p id={descriptionId} className={cn("m-0 mt-3 max-w-[72ch]", HINT_CLASS)}>
          {t("support.groups.constraint")}
        </p>

        <CurrentSelection selected={selected} t={t} />

        {note === null ? null : (
          <div className="mt-4">
            <ErrorNote
              tone={note.tone}
              title={note.title}
              message={note.message}
              hint={
                writeFailure === null
                  ? undefined
                  : `${writeFailure.endpoint} · ${writeFailure.correlationId ?? t("errors.query.noCorrelationId")}`
              }
              onRetry={() => {
                void directory.refetch();
              }}
              isRetrying={directory.isFetching}
              retryable={note.canRetry}
            />
          </div>
        )}

        {canWrite ? null : (
          /* Not a row of disabled buttons: a press would be a 403 and a `permission.denied`
             audit row against somebody who did nothing wrong. The sentence names the permission,
             which is the only reason to print a line here at all — `support.actions.readOnly` is
             the precedent and `errors.detail.roleCannotTitle` is the generic it is not. */
          <p className={cn("m-0 mt-4 max-w-[60ch]", HINT_CLASS)}>
            {t("support.groups.readOnly")}
          </p>
        )}

        <section aria-labelledby={`${ids}-known`} className="mt-5">
          <h3
            id={`${ids}-known`}
            className="m-0 text-[14px] font-semibold leading-[19px] tracking-[-0.28px] text-ink-800"
          >
            {t("support.groups.known")}
          </h3>

          {groups.length === 0 ? (
            <p className={cn("m-0 mt-2 max-w-[60ch]", HINT_CLASS)}>
              {directory.isLoading
                ? t("support.groups.loading")
                : t("support.groups.emptyMessage")}
            </p>
          ) : (
            <ul
              aria-label={t("support.groups.listAria")}
              className="m-0 mt-2 flex list-none flex-col gap-2 p-0"
            >
              {groups.map((group) => (
                <GroupRow
                  key={group.chatId}
                  group={group}
                  canWrite={canWrite}
                  isPending={isPending}
                  t={t}
                  onSelect={() => {
                    /* The row's own topic goes back with it. Omitting it would CLEAR the topic
                       server-side — `thread_id` is set from the request on every call — which is
                       how an inbox silently leaves the topic staff are reading. */
                    submit(
                      group.threadId === null
                        ? { chatId: group.chatId }
                        : { chatId: group.chatId, threadId: group.threadId },
                    );
                  }}
                />
              ))}
            </ul>
          )}
        </section>

        {canWrite ? (
          <section aria-labelledby={`${ids}-paste`} className="mt-6 border-t border-stroke pt-5">
            <h3
              id={`${ids}-paste`}
              className="m-0 text-[14px] font-semibold leading-[19px] tracking-[-0.28px] text-ink-800"
            >
              {t("support.groups.paste.heading")}
            </h3>
            <p className={cn("m-0 mt-1 max-w-[72ch]", HINT_CLASS)}>
              {t("support.groups.paste.hint")}
            </p>

            <form
              className="mt-3 flex flex-wrap items-start gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (pastedChatId === null || !isPasteSubmittable) return;
                submit(
                  pastedThreadId === null
                    ? { chatId: pastedChatId }
                    : { chatId: pastedChatId, threadId: pastedThreadId },
                );
              }}
            >
              <div className="min-w-[220px] flex-1">
                <label htmlFor={chatFieldId} className={LABEL_CLASS}>
                  {t("support.groups.paste.chatLabel")}
                </label>
                <input
                  id={chatFieldId}
                  value={chatText}
                  inputMode="text"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={isPending}
                  aria-invalid={!isChatBlank && pastedChatId === null}
                  aria-describedby={chatHintId}
                  placeholder={t("support.groups.paste.chatPlaceholder")}
                  onChange={(event) => {
                    setChatText(event.target.value);
                  }}
                  className={FIELD_CLASS}
                />
                <p id={chatHintId} className={HINT_CLASS}>
                  {isChatBlank || pastedChatId !== null
                    ? t("support.groups.paste.chatHint")
                    : /* The specific refusal, not a generic "invalid": a non-negative id is a
                         PRIVATE chat, which is a person, and an operator who pasted their own
                         user id has to be told that rather than told to try again. */
                      t("support.groups.paste.chatIsPerson")}
                </p>
              </div>

              <div className="min-w-[180px] flex-1">
                <label htmlFor={threadFieldId} className={LABEL_CLASS}>
                  {t("support.groups.paste.threadLabel")}
                </label>
                <input
                  id={threadFieldId}
                  value={threadText}
                  inputMode="numeric"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={isPending}
                  aria-invalid={!isThreadBlank && pastedThreadId === null}
                  aria-describedby={threadHintId}
                  placeholder={t("support.groups.paste.threadPlaceholder")}
                  onChange={(event) => {
                    setThreadText(event.target.value);
                  }}
                  className={FIELD_CLASS}
                />
                <p id={threadHintId} className={HINT_CLASS}>
                  {isThreadBlank || pastedThreadId !== null
                    ? t("support.groups.paste.threadHint")
                    : t("support.groups.paste.threadInvalid")}
                </p>
              </div>

              <div className="flex items-center gap-3 pt-[22px]">
                <ToolbarButton
                  type="submit"
                  variant="primary"
                  disabled={!isPasteSubmittable || isPending}
                >
                  {select.isPending
                    ? t("support.groups.actions.selecting")
                    : t("support.groups.paste.submit")}
                </ToolbarButton>
              </div>
            </form>

            {selected === null ? null : (
              <div className="mt-5 flex flex-wrap items-center gap-3">
                <ToolbarButton
                  variant="secondary"
                  disabled={isPending}
                  onClick={() => {
                    clear.mutate();
                  }}
                >
                  {clear.isPending
                    ? t("support.groups.actions.clearing")
                    : t("support.groups.actions.clear")}
                </ToolbarButton>
                {/* No confirmation step. This destroys nothing, discloses nothing and is undone
                    by selecting the group again — `selectedAt`, `selectedByUsername` and the
                    topic all stay standing on the row — and "no group selected" is a SUPPORTED
                    state in which tickets keep working and only the group post stops. A modal
                    over a reversible act is the habit that makes confirmations meaningless where
                    they matter. */}
                <p className={cn("m-0 max-w-[44ch]", HINT_CLASS)}>
                  {t("support.groups.actions.clearHint")}
                </p>
              </div>
            )}
          </section>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

/* -------------------------------------------------------------------------- */
/* The answer to "where do my tickets go?", at the top, in one sentence        */
/* -------------------------------------------------------------------------- */

function CurrentSelection({
  selected,
  t,
}: {
  readonly selected: SupportGroupView | null;
  readonly t: Translate;
}): JSX.Element {
  if (selected === null) {
    return (
      <div className="mt-4 rounded-card border border-stroke bg-bg px-4 py-3">
        <p className="m-0 text-[14px] font-semibold leading-[19px] text-ink-800">
          {t("support.groups.current.none")}
        </p>
        {/* Not an error state, and it must not look like one: this is the fallback D18 named,
            reached by a click now rather than by a redeploy. Tickets are still filed, still
            answered from this console and still carry a reference the customer was given. */}
        <p className={cn("m-0 mt-1 max-w-[60ch]", HINT_CLASS)}>
          {t("support.groups.current.noneHint")}
        </p>
      </div>
    );
  }

  const state = verificationStateOf(selected);
  return (
    <div className="mt-4 rounded-card border border-stroke bg-bg px-4 py-3">
      <p className="m-0 text-[12px] font-semibold uppercase leading-[16px] tracking-[0.04em] text-ink-400">
        {t("support.groups.current.heading")}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className="text-[16px] font-semibold leading-[22px] tracking-[-0.32px] text-ink-900">
          {chatDisplayName(selected)}
        </span>
        <Badge tone={VERIFICATION_TONE[state]}>{t(VERIFICATION_LABEL_KEY[state])}</Badge>
      </div>
      <p className={cn("m-0 mt-1", HINT_CLASS)}>
        {selected.threadId === null
          ? t("support.groups.current.noThread")
          : t("support.groups.current.thread", { id: String(selected.threadId) })}
        {selected.selectedByUsername === null || selected.selectedAt === null
          ? ""
          : ` · ${t("support.groups.current.chosenBy", {
              username: selected.selectedByUsername,
              when: formatAbsolute(selected.selectedAt),
            })}`}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One chat                                                                    */
/* -------------------------------------------------------------------------- */

function GroupRow({
  group,
  canWrite,
  isPending,
  t,
  onSelect,
}: {
  readonly group: SupportGroupView;
  readonly canWrite: boolean;
  readonly isPending: boolean;
  readonly t: Translate;
  readonly onSelect: () => void;
}): JSX.Element {
  const state = verificationStateOf(group);
  const verifiedWhen = group.verifiedAt === null ? null : formatRelative(group.verifiedAt, t);

  return (
    <li
      className={cn(
        "rounded-card border px-4 py-3",
        group.isSupportGroup ? "border-accent-deep bg-bg" : "border-stroke bg-card",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[14px] font-semibold leading-[19px] text-ink-900">
              {chatDisplayName(group)}
            </span>
            {group.isSupportGroup ? (
              <Badge tone="accent">{t("support.groups.row.selected")}</Badge>
            ) : null}
            {/* Telegram's own word, or an operator's paste. The whole reason a manual row is
                riskier, so it is never folded into the title line's ink. */}
            <Badge tone={CHAT_SOURCE_TONE[group.source]} title={t(CHAT_SOURCE_HINT_KEY[group.source])}>
              {t(CHAT_SOURCE_LABEL_KEY[group.source])}
            </Badge>
            <Badge tone="muted">{t(CHAT_TYPE_LABEL_KEY[group.chatType])}</Badge>
            <Badge tone={BOT_STATUS_TONE[group.botStatus]} title={t("support.groups.botStatusHint")}>
              {t(BOT_STATUS_LABEL_KEY[group.botStatus])}
            </Badge>
            <Badge tone={VERIFICATION_TONE[state]}>{t(VERIFICATION_LABEL_KEY[state])}</Badge>
          </div>

          {/* The id, always, in a monospace run. It is what an operator matches against
              Telegram, what they paste back after a migration, and for an untitled row it is the
              only thing that distinguishes it — so it is on the row even when a title is. */}
          <p className={cn("m-0 mt-1 font-mono", HINT_CLASS)}>
            {String(group.chatId)}
            {group.threadId === null
              ? ""
              : ` · ${t("support.groups.row.thread", { id: String(group.threadId) })}`}
          </p>

          {state === "verified" && verifiedWhen !== null ? (
            <p className={cn("m-0 mt-1", HINT_CLASS)}>
              {t("support.groups.verification.verifiedWhen", { when: verifiedWhen })}
            </p>
          ) : null}

          {/* The "what checking means" paragraph used to print HERE, under every row, which put
              three copies of the same three lines on a three-chat deployment. The badge says
              `checking`; the one row that is actually being checked explains itself once, up
              beside the current selection. */}

          {group.verificationError === null ? null : (
            /* VERBATIM, WRAPPED, AND NEVER TRUNCATED. This is English prose the worker wrote for
               a member of staff, not a catalogue key with a translation somewhere — and when the
               group has migrated it carries the NEW chat id as a bare number, which is the whole
               recovery path: read it, copy it, paste it into the field below. A `truncate` here
               would delete the fix. */
            <p
              className="m-0 mt-2 max-w-[72ch] whitespace-pre-wrap break-words text-[12px] font-normal leading-[16.392px] text-required-deep"
            >
              {group.verificationError}
            </p>
          )}
        </div>

        {canWrite ? (
          <div className="flex shrink-0 items-center">
            <ToolbarButton
              variant={group.isSupportGroup ? "secondary" : "primary"}
              disabled={isPending}
              ariaLabel={t("support.groups.row.selectAria", { chat: chatDisplayName(group) })}
              onClick={onSelect}
            >
              {group.isSupportGroup
                ? t("support.groups.actions.recheck")
                : t("support.groups.actions.select")}
            </ToolbarButton>
          </div>
        ) : null}
      </div>
    </li>
  );
}
