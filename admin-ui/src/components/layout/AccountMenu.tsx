/**
 * The top bar's account menu: who you are, at what role, since when — and the way out.
 *
 * The role is shown, always. §12.2 gives four roles whose visible difference is which
 * affordances exist, and §11.4 hides rather than disables the ones you lack. That is the
 * right default and it has one cost: an operator cannot tell, from an absent button, whether
 * the console is broken or their role is limited. Naming the role here is what pays that
 * cost — it is the only place the answer is written down.
 *
 * Sign-out clears the whole query cache before navigating. The cache holds order rows, user
 * rows and audit entries fetched under the outgoing session; leaving them for the next
 * sign-in to render from would be a cross-session data leak on a shared machine, and it
 * would do it invisibly, since the screen would look correct.
 *
 * The trigger gained a round avatar in the reskin, and it is drawn from the account's own
 * first character rather than from a generated image — no service is called, nothing is
 * uploaded, and a username is our own string. It is taken with `Array.from`, which cuts on a
 * code POINT, and with no case change at all: this file is outside `components/domain/` and
 * the lint fence does not reach it, but `toUpperCase()` on a name is the habit that fence
 * exists to prevent and an admin username is not the place to practise it.
 */

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Keyboard, LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { postLogout } from "@/api";
import { buttonVariants, useSession, useShortcutHelp } from "@/components/util";
import { formatTimestamp } from "@/lib/format";
import { usePrefsStore } from "@/lib/stores";
import { cn } from "@/lib/utils";
import { href } from "@/routes";

const ITEM_CLASS = cn(
  "type-body-sm flex cursor-default select-none items-center gap-2 rounded-control px-3 py-2",
  "text-ink-muted outline-none data-[highlighted]:bg-surface-control",
  "data-[highlighted]:text-ink",
);

/** The avatar's letter: the first code point of the account name, unchanged. */
function initialOf(name: string): string {
  return Array.from(name)[0] ?? "·";
}

export function AccountMenu() {
  const { me, role, isPending } = useSession();
  const timeZoneMode = usePrefsStore((state) => state.timeZoneMode);
  const shortcutHelp = useShortcutHelp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const onSignOut = (): void => {
    void postLogout().finally(() => {
      // Unconditional: a logout that failed on the wire still means this operator is done
      // with this screen, and leaving their data cached would be the worse of the two bugs.
      queryClient.clear();
      navigate(href.login(), { replace: true });
    });
  };

  const name = me?.username ?? (isPending ? "…" : "signed out");

  return (
    <DropdownMenu.Root>
      {/* A Radix trigger is its own `<button>`, so it takes the CLASSES from the shared
          definition. `quiet` — no ground until hover — is what it already was; it is here so
          it cannot drift. `text-ink` overrides the variant's label deliberately: the name is
          primary content, not a muted control label. */}
      <DropdownMenu.Trigger
        className={cn(
          buttonVariants({ variant: "quiet", size: "none", shape: "pill" }),
          "h-10 gap-2 py-1 pl-3 pr-1 text-ink",
        )}
      >
        <span className="type-body-sm max-w-40 truncate">{name}</span>
        {role === null ? null : <span className="type-caption text-ink-muted">{role}</span>}
        <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 text-ink-muted" />
        <span
          aria-hidden="true"
          className={cn(
            "type-body-sm flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
            "bg-brand-tint font-semibold text-brand",
          )}
        >
          {initialOf(name)}
        </span>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className={cn(
            "z-50 min-w-64 rounded-2xl bg-surface-card p-2 shadow-overlay",
          )}
        >
          <DropdownMenu.Label className="px-3 py-2">
            <span className="type-body block truncate font-semibold text-ink">{name}</span>
            <span className="type-caption block text-ink-muted">{role ?? "role unknown"}</span>
            <span className="type-body-sm mt-2 block text-ink-muted">
              last sign-in{" "}
              <span className="num">
                {me === null ? "—" : formatTimestamp(me.lastLoginAt, timeZoneMode)}
              </span>
            </span>
          </DropdownMenu.Label>

          {/* Whitespace does most of the separating in this design; the divider under the
              identity block is the one place a rule still earns its keep, because what is
              above it is a fact and what is below it is an action. */}
          <DropdownMenu.Separator className="my-2 h-px bg-hairline" />

          <DropdownMenu.Item
            className={ITEM_CLASS}
            onSelect={() => {
              shortcutHelp.setOpen(true);
            }}
          >
            <Keyboard aria-hidden="true" className="h-4 w-4" />
            Keyboard shortcuts
            <kbd className="type-mono ml-auto text-ink-muted">?</kbd>
          </DropdownMenu.Item>

          <DropdownMenu.Item className={ITEM_CLASS} onSelect={onSignOut}>
            <LogOut aria-hidden="true" className="h-4 w-4" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
