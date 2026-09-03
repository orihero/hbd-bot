/**
 * `<TelegramUserChip>` — a link to a user that never draws their id.
 *
 * §12.3 masks `telegram_user_id` to `•••••123` at every role, and contract D10 ships the
 * unmasked integer alongside the masked string for one reason only: **to build the link**.
 * `/api/users/**` and `/users/:telegramUserId` are both keyed on the integer, so it has to
 * be on the wire — but it must not reach the screen, a screenshot, or a Slack paste.
 *
 * This component is the place that rule is enforced: it takes both, renders
 * `telegramUserIdMasked` and puts `telegramUserId` in the href. A caller that renders
 * `{order.telegramUserId}` directly has silently defeated the mask, and having exactly one
 * component that knows the difference is what makes that reviewable.
 *
 * The masked string is OUR construction (five U+2022 then three digits), not user content,
 * so it is not a `<NameText>` case.
 */

import type { ReactElement } from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib";
import { href } from "@/routes";

export interface TelegramUserChipProps {
  /** The INTEGER id. Used to build the link and for nothing else. */
  telegramUserId: number;
  /** `•••••123`, exactly as the server masked it. This is what gets drawn. */
  telegramUserIdMasked: string;
  isBlocked?: boolean | undefined;
  className?: string | undefined;
}

export function TelegramUserChip({
  telegramUserId,
  telegramUserIdMasked,
  isBlocked = false,
  className,
}: TelegramUserChipProps): ReactElement {
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <Link
        to={href.user(telegramUserId)}
        data-testid="telegram-user-chip"
        className={cn(
          "type-mono rounded-pill px-1.5 py-0.5 text-ink-muted",
          "transition-colors duration-fast ease-standard hover:bg-surface-control-hover hover:text-ink",
        )}
      >
        {telegramUserIdMasked}
      </Link>
      {isBlocked ? (
        <span
          data-testid="telegram-user-blocked"
          title="blocked"
          className="type-caption inline-flex items-baseline gap-0.5"
          style={{ color: "var(--error)" }}
        >
          <span aria-hidden="true">⊘</span>
          <span>blocked</span>
        </span>
      ) : null}
    </span>
  );
}
