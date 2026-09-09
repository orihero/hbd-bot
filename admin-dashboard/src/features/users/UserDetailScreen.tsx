/**
 * `/users/:telegramUserId` — one customer, and the two privileged writes that can be made
 * against them.
 *
 * ## The route key is the INTEGER Telegram id, and it is never drawn
 *
 * Every `/users/**` route keys on it, so it has to be in the path; that much is unavoidable and
 * fine. Nothing else about this person goes into the URL — not a name, not a mask, and above
 * all not a revealed value, because a URL leaks through history, referrers and screenshots.
 * On screen the integer is replaced everywhere by `telegramUserIdMasked`, which is also the
 * label every dialog on this screen uses for its subject: the title of a dialog that exists to
 * reveal somebody's name must not be their name.
 *
 * Two id spaces, one row, and they are not interchangeable: `telegramUserId` is what block,
 * unblock and grant are keyed on and what their step-up scopes are built from; `user.id` (a
 * UUID) is the subject `POST /api/reveal` takes for a `user_profiles.*` column. Sending one
 * where the other belongs is a scope mismatch, a 404, or a reveal of somebody else.
 *
 * ## Role gates the affordance, not the request
 *
 * A role that cannot block sees no Block button, and a role that cannot grant sees no Grant
 * button. Pressing a button that always 403s writes a `permission.denied` audit row against an
 * operator who did nothing wrong and teaches them the console is broken. The reveal affordances
 * are gated the same way one level down, inside `<MaskedValue>`.
 *
 * ## The screen reflects what the server SAID
 *
 * A block answers with `isBlocked` and `changedAt`, and a grant with the balance read back from
 * the database. Both are shown from the response until the invalidated record actually lands —
 * compared on `dataUpdatedAt`, so the moment the refetch answers, the query wins again. Nothing
 * here guesses at a new state from what was asked for, which is the only way `isReplay: true`
 * ("already granted — nothing moved") can be told from a fresh grant.
 *
 * ## Paging is component state
 *
 * The two tables page independently and neither cursor is in the URL. See `useCursorStack`:
 * a keyset cursor cannot be paged backwards after a reload, so a "Previous" restored from a
 * pasted link would be either missing or wrong, and two tables would need two opaque keys in
 * that link. The addressable state of this screen is the Telegram id in its path.
 */

import { useState, type JSX, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { MessageSquare } from "lucide-react";

import type { CreditGrantResultView, UserBlockResultView, UserView } from "@/api/users";
import { PATH, chatDetailPath } from "@/app/paths";
import { Avatar } from "@/components/Avatar";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { Toolbar, ToolbarButton } from "@/components/Toolbar";
import { Notice, useCanBlockUsers, useCanGrantCredits } from "@/features/reveal";
import { useSessionGuard } from "@/state/useSessionGuard";

import { BlockUserDialog } from "./BlockUserDialog";
import { CreditsPanel } from "./CreditsPanel";
import { GrantCreditsDialog } from "./GrantCreditsDialog";
import { IdentityPanel } from "./IdentityPanel";
import { OrdersPanel } from "./OrdersPanel";
import { WizardStatePanel } from "./WizardStatePanel";
import { PANEL_NOTE_CLASS, Panel, QueryErrorNote, SectionHeading } from "./detailKit";
import { useI18n } from "@/i18n";
import { LANGUAGE_LABEL_KEY } from "@/lib/languageLabel";

import { formatInteger, formatTimestamp, initialsOf } from "./detailFormat";
import { useUser, useWizardState } from "./useUsers";

/** What the last privileged write answered, so the screen can show it before the refetch lands. */
type ActionOutcome =
  | { readonly kind: "block"; readonly result: UserBlockResultView; readonly at: number }
  | { readonly kind: "grant"; readonly result: CreditGrantResultView; readonly at: number };

export function UserDetailScreen(): JSX.Element {
  const { t } = useI18n();
  const params = useParams<{ telegramUserId: string }>();
  const raw = params.telegramUserId ?? "";
  const telegramUserId = parseTelegramUserId(raw);

  const detail = useUser(telegramUserId);
  const wizard = useWizardState(telegramUserId);

  /* Without this the tab keeps its `authed` store through an expired session: four reads
     answering 401 on every window focus, the rail still naming the account, and Block, Grant
     and Reveal still drawn and still pressable — each press a refused request. */
  useSessionGuard([detail.error, wizard.error]);

  const canBlock = useCanBlockUsers();
  const canGrant = useCanGrantCredits();

  const [isBlockOpen, setIsBlockOpen] = useState(false);
  const [isGrantOpen, setIsGrantOpen] = useState(false);
  const [outcome, setOutcome] = useState<ActionOutcome | null>(null);

  if (telegramUserId === null) {
    return (
      <PageFrame>
        <Toolbar title={t("users.detail.customer")} subtitle={t("users.notFound.badIdMessage")} />
        <EmptyState
          title={t("users.notFound.badIdTitle")}
          /* Whatever was in the URL bar, quoted back verbatim as a text child and nothing
             else, so an operator can see the character that broke the route. */
          message={`“${raw}” is not a whole number this API can be asked about.`}
        />
      </PageFrame>
    );
  }

  const user = detail.data?.user;
  /* The record is gone or was never there. Block and grant have NO 404 — they upsert, because
     the customer they are reached for often has no `users` row — so the actions stay. */
  const isMissing = detail.error !== null && detail.error.code === "NOT_FOUND";
  const subjectLabel = user?.telegramUserIdMasked ?? "this Telegram id";

  /* The response wins until the invalidated record actually lands — then the query does. */
  const fresh = outcome !== null && detail.dataUpdatedAt < outcome.at ? outcome : null;
  const blockOutcome = fresh !== null && fresh.kind === "block" ? fresh.result : null;
  const grantOutcome = fresh !== null && fresh.kind === "grant" ? fresh.result : null;
  const isBlocked = blockOutcome?.isBlocked ?? user?.isBlocked ?? false;

  return (
    <PageFrame>
      <Toolbar
        title={t("users.detail.customer")}
        subtitle={t("users.detail.customerSubtitle")}
        filters={
          user === undefined ? (
            isMissing ? (
              <p className={PANEL_NOTE_CLASS}>{t("users.notFound.missingMessage")}</p>
            ) : (
              <Skeleton className="h-8 w-48" />
            )
          ) : (
            <IdentityChips user={user} isBlocked={isBlocked} />
          )
        }
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <Link
              to={chatDetailPath(telegramUserId)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-stroke bg-card px-3 py-1.5 text-xs font-medium text-ink-700 shadow-2xs hover:bg-surface hover:text-ink-900"
            >
              <MessageSquare className="h-3.5 w-3.5 text-accent" />
              <span>{t("users.detail.viewChatHistory")}</span>
            </Link>
            {/* Hidden for a role without the cell, never disabled — §11.4's rule is hiding.
                The two writes are also the two that survive a missing record. */}
            {canGrant ? (
              <ToolbarButton
                onClick={() => {
                  setIsGrantOpen(true);
                }}
              >
                {t("users.detail.grantCredits")}
              </ToolbarButton>
            ) : null}
            {canBlock ? (
              <ToolbarButton
                variant={isBlocked ? "secondary" : "primary"}
                onClick={() => {
                  setIsBlockOpen(true);
                }}
              >
                {isBlocked ? "Unblock" : "Block"}
              </ToolbarButton>
            ) : null}
          </div>
        }
      />

      {outcome === null ? null : (
        <OutcomeNotice
          outcome={outcome}
          subjectLabel={subjectLabel}
          onDismiss={() => {
            setOutcome(null);
          }}
        />
      )}

      {detail.error === null ? null : (
        <QueryErrorNote
          error={detail.error}
          noun={t("users.detailNouns.record")}
          onRetry={() => {
            void detail.refetch();
          }}
          isRetrying={detail.isFetching}
        />
      )}

      {user === undefined ? (
        isMissing ? (
          <Panel ariaLabel="no record">
            <p className={PANEL_NOTE_CLASS}>
              Nothing is held under this Telegram id: no profile, no orders and no credit account.
              Blocking and granting still work — those routes open a record rather than refusing,
              which is deliberate, because the customer they are reached for often has none.
            </p>
          </Panel>
        ) : (
          <Skeleton className="h-48 w-full rounded-panel" />
        )
      ) : (
        /* Keyed on the subject: the cells inside hold revealed plaintext in their own state,
           and a cached user swapped in by Back/Forward re-renders this panel rather than
           remounting it — which would draw one customer's bought name under another's mask. */
        <IdentityPanel key={user.id} user={user} />
      )}

      {/* `/orders` and `/credits` 404 under an id nothing is held for, exactly as the record
          did — the existence probe is the point of those routes. Asking anyway would print the
          same refusal three times. The wizard draft is NOT skipped: it never 404s, and a
          customer stuck mid-flow can have a draft and no `users` row at all. */}
      <div
        className={
          isMissing
            ? "grid grid-cols-1 gap-6"
            : "grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]"
        }
      >
        {isMissing ? null : (
          <div className="flex min-w-0 flex-col gap-6">
            <CreditsPanel
              telegramUserId={telegramUserId}
              /* A grant inserts at the TOP of the ledger. The panel pages with a keyset
                 cursor, so without this the operator stays on page three and the row they
                 just wrote is on page one, invisible. */
              grantedAt={outcome !== null && outcome.kind === "grant" ? outcome.at : null}
              creditBalance={grantOutcome?.account.balance ?? user?.creditBalance}
              lifetimeCreditsGranted={
                grantOutcome?.account.lifetimeGranted ?? user?.lifetimeCreditsGranted
              }
              allowancePeriod={grantOutcome?.account.allowancePeriod ?? user?.allowancePeriod}
              creditsProjected={detail.data?.creditsProjected}
              inFlightRenderCount={detail.data?.inFlightRenderCount}
              isRecordUnavailable={detail.error !== null}
            />

            <OrdersPanel
              telegramUserId={telegramUserId}
              ordersByState={detail.data?.ordersByState}
              deliveredOrderCount={detail.data?.deliveredOrderCount}
              failedOrderCount={detail.data?.failedOrderCount}
            />
          </div>
        )}

        <aside className="flex min-w-0 flex-col gap-3" aria-label={t("users.wizard.aria")}>
          <SectionHeading>{t("users.wizard.title")}</SectionHeading>
          {wizard.error !== null ? (
            <QueryErrorNote
              error={wizard.error}
              noun={t("users.wizard.noun")}
              onRetry={() => {
                void wizard.refetch();
              }}
              isRetrying={wizard.isFetching}
            />
          ) : wizard.data === undefined ? (
            <Skeleton className="h-40 w-full rounded-panel" />
          ) : (
            <WizardStatePanel state={wizard.data} />
          )}
        </aside>
      </div>

      {/* Mounted only for a role that holds the cell, so there is no dialog to open by accident
          and no request that could 403 from this screen. */}
      {canBlock ? (
        <BlockUserDialog
          isOpen={isBlockOpen}
          onClose={() => {
            setIsBlockOpen(false);
          }}
          telegramUserId={telegramUserId}
          subjectLabel={subjectLabel}
          isBlocked={isBlocked}
          onBlocked={(result) => {
            setOutcome({ kind: "block", result, at: Date.now() });
          }}
          onConflict={() => {
            void detail.refetch();
          }}
        />
      ) : null}

      {canGrant ? (
        <GrantCreditsDialog
          isOpen={isGrantOpen}
          onClose={() => {
            setIsGrantOpen(false);
          }}
          telegramUserId={telegramUserId}
          subjectLabel={subjectLabel}
          onGranted={(result) => {
            setOutcome({ kind: "grant", result, at: Date.now() });
          }}
        />
      ) : null}
    </PageFrame>
  );
}

/**
 * The route parameter, or `null`.
 *
 * A hand-edited URL must produce a legible refusal rather than `/api/users/NaN/orders`, which
 * is a 422 the operator cannot act on. `isSafeInteger` is the second half of that: a 25-digit
 * "id" parses to a float that would be sent as `1.2e+24`.
 */
function parseTelegramUserId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) return null;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

/** The page band. `AppShell` owns the ground and the rail; drawing either again would double it. */
function PageFrame({ children }: { readonly children: ReactNode }): JSX.Element {
  return (
    <main className="py-6">
      <div className="mx-auto flex w-[min(1392px,100%-2rem)] flex-col gap-6">
        <Link
          to={PATH.users}
          className="w-fit text-[12px] leading-[16.392px] tracking-[-0.36px] text-ink-500 transition-colors hover:text-ink-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-deep"
        >
          ← Users
        </Link>
        {children}
      </div>
    </main>
  );
}

/**
 * Who this is, in the toolbar's middle slot: the picture, the masked id, and the counts.
 *
 * The monogram is derived from MASKED text only — a mask's first character is one the server
 * already chose to show. A letter lifted from a REVEALED name would put a bought, audited
 * character into a component with no audit row and no lifetime.
 */
function IdentityChips({
  user,
  isBlocked,
}: {
  readonly user: UserView;
  readonly isBlocked: boolean;
}): JSX.Element {
  const { t } = useI18n();

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-3">
      <Avatar
        src={user.avatarUrl}
        initials={initialsOf(user.firstNameMasked, user.lastNameMasked)}
        status={isBlocked ? "danger" : "ok"}
        statusLabel={isBlocked ? t("users.blockedShort") : t("users.ableToOrder")}
        size={40}
      />
      <div className="flex min-w-0 flex-col gap-1">
        <span className="font-mono text-[12px] leading-4 tracking-[-0.2px] text-ink-800">
          {user.telegramUserIdMasked}
        </span>
        <span className="text-[12px] leading-[16.392px] tracking-[-0.36px] text-ink-400">
          {t("users.orderSummaryLine", {
            orders: formatInteger(user.orderCount),
            paid: formatInteger(user.paidOrderCount),
            language: t(LANGUAGE_LABEL_KEY[user.uiLanguage]),
          })}
        </span>
      </div>
      {isBlocked ? (
        <Badge tone="danger" title={t("users.blockedBanner")}>
          {t("users.blockedShort")}
        </Badge>
      ) : null}
    </div>
  );
}

/**
 * What the last write actually did, in the server's own terms.
 *
 * The grant branch is the one that matters: `isReplay: true` means this idempotency key had
 * already been used for this account and **nothing moved**, while `grantedCredits` still echoes
 * what was asked for. Printing that number as a fresh success is how an operator grants twice.
 * The balance beside it was read back from the database, so it is the figure the ledger agrees
 * with — not arithmetic done here.
 */
function OutcomeNotice({
  outcome,
  subjectLabel,
  onDismiss,
}: {
  readonly outcome: ActionOutcome;
  readonly subjectLabel: string;
  readonly onDismiss: () => void;
}): JSX.Element {
  const { t } = useI18n();
  const dismiss = (
    <button
      type="button"
      onClick={onDismiss}
      className="self-start rounded-button border border-stroke px-2 py-0.5 text-[11px] leading-4 text-ink-500 transition-[filter] hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-deep"
    >
      {t("common.dismiss")}
    </button>
  );

  if (outcome.kind === "block") {
    const { result } = outcome;
    return (
      <Notice
        tone="quiet"
        testId="block-outcome"
        title={result.isBlocked ? `${subjectLabel} is blocked` : `${subjectLabel} can order again`}
      >
        <p className="m-0">
          {`Recorded ${formatTimestamp(result.changedAt)}, with your reason, on the audit log. ${
            result.isBlocked
              ? "The bot refuses them from now on."
              : "The bar is lifted; nothing else about the account changed."
          }`}
        </p>
        {dismiss}
      </Notice>
    );
  }

  const { result } = outcome;
  return (
    <Notice
      tone={result.isReplay ? "caution" : "quiet"}
      testId="grant-outcome"
      title={
        result.isReplay
          ? "Already granted — nothing moved"
          : `Granted ${formatInteger(result.grantedCredits)} ${result.grantedCredits === 1 ? "credit" : "credits"}`
      }
    >
      <p className="m-0">
        {result.isReplay
          ? `This request had already been used for ${subjectLabel}, so no credits were added a second time. The audit log records that somebody asked again.`
          : `${subjectLabel} can spend them immediately.`}
      </p>
      <p className="m-0">
        {`Balance now ${formatInteger(result.account.balance)}, read back from the database — ${formatInteger(result.account.lifetimeGranted)} granted over the account's lifetime.`}
      </p>
      {dismiss}
    </Notice>
  );
}
