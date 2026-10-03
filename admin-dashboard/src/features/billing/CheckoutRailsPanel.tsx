/**
 * The owner's per-rail sale switch (DECISIONS.md D28), drawn in the payments toolbar beside
 * the global pause.
 *
 * ## What a row says, and what it does not
 *
 * Each switchable rail (Rahmat, Payme, checkout.uz) gets its name, an On/Off badge for the
 * owner's Redis switch, and — when the bot reported that its environment did NOT wire the rail
 * — a "not live in env" badge. A rail sells only when all three hold: wired in the env, switched
 * on here, and checkouts not globally paused. This panel shows the first two; the pause verb
 * sits next to it.
 *
 * `wired === null` is "unknown", never "not wired": the bot publishes its wired rails at boot
 * and the admin process cannot read `bot.env` itself, so a deploy that has not booted the bot
 * yet, or a Redis hiccup, must not paint every rail as dead. The unknown case prints no badge.
 *
 * "On" is the switch, not a promise of sales: a missing key reads as on, because the switch
 * fails OPEN exactly like the pause does. The env flag is the hard off.
 *
 * ## Owner only, and the button is hidden rather than disabled
 *
 * The write is `CONFIG_MANAGE`, which only the owner holds. Every other role sees the badges
 * and no button: a press would be a 403 and a `permission.denied` audit row against somebody
 * who did nothing wrong. The server stays the authority — this only decides what is drawn —
 * and a 403 that still arrives renders as a plain `denied` note, never a credential prompt.
 *
 * ## Turning a rail off strands nothing
 *
 * Settlement never reads the switch. A payment opened before the switch moved still settles
 * and is credited; only new buttons and new checkouts stop. The dialog copy says so, because
 * that is the question an owner asks before pressing it in an incident.
 */

import { useState, type JSX } from "react";

import {
  SWITCHABLE_RAILS,
  type CheckoutRailView,
  type SwitchableRail,
} from "@/api/config";
import { Badge } from "@/components/Badge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorNote } from "@/components/ErrorNote";
import { ToolbarButton } from "@/components/Toolbar";
import {
  EMPTY_REASON,
  ReasonFieldset,
  canSubmitReason,
  reasonBodyOf,
  type ReasonState,
} from "@/features/users/ReasonFieldset";
import { useI18n } from "@/i18n";
import type { AdminQueryError } from "@/lib/adminQuery";
import { useCanManageConfig } from "@/lib/rbac";

import { useCheckoutRails, useSetCheckoutRail } from "./useCheckoutRails";

function isSwitchableRail(name: string): name is SwitchableRail {
  return (SWITCHABLE_RAILS as readonly string[]).includes(name);
}

interface PendingFlip {
  readonly rail: SwitchableRail;
  readonly enabled: boolean;
}

export function CheckoutRailsPanel(): JSX.Element | null {
  const { t } = useI18n();
  const rails = useCheckoutRails();
  const flip = useSetCheckoutRail();
  const canManage = useCanManageConfig();

  const [target, setTarget] = useState<PendingFlip | null>(null);
  const [reason, setReason] = useState<ReasonState>(EMPTY_REASON);

  /** A rail the server knows but this build does not prints under its raw name. */
  function railName(name: string): string {
    return isSwitchableRail(name) ? t(`billing.rails.names.${name}`) : name;
  }

  function open(next: PendingFlip): void {
    setReason(EMPTY_REASON);
    flip.reset();
    setTarget(next);
  }

  function close(): void {
    // The reason dies with the dialog: carried to the next press it would attach one stated
    // reason to a different decision, on an audit row that outlives both.
    setReason(EMPTY_REASON);
    flip.reset();
    setTarget(null);
  }

  if (rails.isLoading) return null;

  if (rails.data === undefined) {
    return (
      <Badge tone="muted" title={rails.error?.message}>
        {t("billing.rails.loadFailed")}
      </Badge>
    );
  }

  const config = rails.data;
  const body = reasonBodyOf(reason);
  const error: AdminQueryError | null = flip.error;
  const targetName = target === null ? "" : railName(target.rail);

  return (
    <>
      <div
        role="group"
        aria-label={t("billing.rails.heading")}
        className="flex flex-wrap items-center gap-2"
        data-testid="checkout-rails"
      >
        <span className="text-[14px] font-medium text-ink-500">
          {t("billing.rails.heading")}:
        </span>
        {config.rails.map((rail: CheckoutRailView) => {
          const name = railName(rail.name);
          return (
            <span
              key={rail.name}
              className="inline-flex items-center gap-1"
              data-testid={`checkout-rail-${rail.name}`}
            >
              <span className="text-[13px] text-ink-800">{name}</span>
              <Badge tone={rail.enabled ? "accent" : "danger"}>
                {rail.enabled ? t("billing.rails.on") : t("billing.rails.off")}
              </Badge>
              {rail.wired === false ? (
                <Badge tone="warning" title={t("billing.rails.notWiredHint")}>
                  {t("billing.rails.notWired")}
                </Badge>
              ) : null}
              {canManage && isSwitchableRail(rail.name) ? (
                <ToolbarButton
                  variant="secondary"
                  className="!h-8 !py-1 !px-2 !text-[13px]"
                  ariaLabel={t(
                    rail.enabled ? "billing.rails.turnOffAria" : "billing.rails.turnOnAria",
                    { rail: name },
                  )}
                  onClick={() => {
                    if (!isSwitchableRail(rail.name)) return;
                    open({ rail: rail.name, enabled: !rail.enabled });
                  }}
                >
                  {rail.enabled ? t("billing.rails.turnOff") : t("billing.rails.turnOn")}
                </ToolbarButton>
              ) : null}
            </span>
          );
        })}
        {config.wiredKnown ? null : (
          <span className="sr-only">{t("billing.rails.wiredUnknownHint")}</span>
        )}
      </div>

      {target === null ? null : (
        <ConfirmDialog
          isOpen
          title={t(
            target.enabled ? "billing.rails.onTitle" : "billing.rails.offTitle",
            { rail: targetName },
          )}
          description={t(target.enabled ? "billing.rails.onBody" : "billing.rails.offBody", {
            rail: targetName,
          })}
          confirmLabel={t(
            target.enabled ? "billing.rails.onLabel" : "billing.rails.offLabel",
            { rail: targetName },
          )}
          pendingLabel={
            target.enabled ? t("billing.rails.onPending") : t("billing.rails.offPending")
          }
          /* `danger` for the off direction: it stops a way of taking money. Turning a rail
             back on is the ordinary direction. */
          tone={target.enabled ? "default" : "danger"}
          isPending={flip.isPending}
          isConfirmDisabled={!canSubmitReason(reason)}
          error={
            error === null ? undefined : (
              <ErrorNote
                /* `denied` for a refusal — no Retry, because asking again cannot change a
                   role. Everything else is an `error` the owner may usefully re-press. */
                tone={error.status === 403 ? "denied" : "error"}
                title={t("billing.rails.failedTitle")}
                message={error.message}
                hint={
                  error.correlationId === null
                    ? undefined
                    : `${error.endpoint} · ${error.correlationId}`
                }
                retryable={false}
              />
            )
          }
          reason={{
            label: t("billing.rails.reasonLabel"),
            hint: t("billing.rails.reasonHint"),
            value: reason.text,
            isRequired: false,
            onChange: (text) => {
              setReason({ ...reason, text });
            },
          }}
          onConfirm={() => {
            if (body === null) return;
            flip.mutate(
              { ...body, rail: target.rail, enabled: target.enabled },
              {
                onSuccess: () => {
                  close();
                },
              },
            );
          }}
          onClose={close}
        >
          <ReasonFieldset value={reason} onChange={setReason} isDisabled={flip.isPending} />
        </ConfirmDialog>
      )}
    </>
  );
}
