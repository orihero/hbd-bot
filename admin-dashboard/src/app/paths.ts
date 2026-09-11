/**
 * The route table's strings, in a leaf module that imports nothing.
 *
 * They lived in `routes.tsx` first, which made every consumer import the router — and the
 * router imports the screens, so `LoginPage -> routes -> LoginPage` was a cycle that only
 * worked because `PATH` was read at call time. One top-level `const x = PATH.login` in a
 * screen would have thrown a TDZ `ReferenceError` at startup, from the wrong file.
 */
export const PATH = {
  login: "/login",
  changePassword: "/change-password",
  dashboard: "/",
  chats: "/chats",
  /** The router's PATTERN. Never navigate to this — call `chatDetailPath`. */
  chatDetail: "/chats/:telegramUserId",
  users: "/users",
  /** The router's PATTERN. Never navigate to this — call `userDetailPath`. */
  userDetail: "/users/:telegramUserId",
  generations: "/generations",
  /** The router's PATTERN. Never navigate to this — call `generationDetailPath`. */
  generationDetail: "/generations/:attemptId",
  /*
   * Below the rail's rule, in its order. Neither takes a parameter and neither gets a
   * builder: a `xDetailPath` exists to keep an id out of a template literal at the call
   * site, and there is no id here. The roster has no per-account route because no endpoint
   * serves one, and audit narrows itself through query parameters the screen owns — filters
   * rather than an address, so they live in that screen's `PARAM` map, not in this table.
   */
  broadcasts: "/broadcasts",
  /**
   * The wizard. A ROUTE and not a dialog, because it carries an audience in the URL and has
   * to survive a refresh — and because `/users` hands it one, which a dialog could not be
   * linked to. Registered before `/broadcasts/:broadcastId`, or the literal reads as an id.
   */
  broadcastNew: "/broadcasts/new",
  /**
   * The router's PATTERN. Never navigate to this — call `broadcastDetailPath`.
   *
   * Registered AFTER `broadcastNew` in `routes.tsx`, so the literal `new` is matched as the
   * wizard rather than read as a campaign id — a `/broadcasts/new` that resolved here would
   * ask the API for a campaign whose id is the word "new" and render a 404 for the one route
   * an operator reaches from the primary action on two screens.
   */
  broadcastDetail: "/broadcasts/:broadcastId",
  /*
   * The Payme rail. Three paths, and the section's landing screen is the payments LIST: the
   * filters that narrow it and the lookup that jumps out of it are the whole screen, and the
   * status the board used to explain at length is one pause control in the toolbar.
   */
  rail: "/billing",
  railCalls: "/billing/calls",
  /** The dossier's parent segment. Not a route of its own — the list lives at `rail`. */
  railIntents: "/billing/intents",
  /** The router's PATTERN. Never navigate to this — call `intentDetailPath`. */
  railIntentDetail: "/billing/intents/:intentId",
  audit: "/audit",
  admins: "/admins",
} as const;

/**
 * One payment, by its `payment_intents.id`.
 *
 * A payment-intent UUID carries nothing about a customer, which is what makes it safe in an
 * address bar — through history, referrers and screenshots. That is also why it, and not
 * `publicRef`, is the URL key: the public reference is the string that crosses to Payme and
 * gets read aloud over the phone, so it belongs in the LOOKUP box rather than in every link.
 * `idempotencyKey` appears in neither, ever: it is shaped `topup:{tg}:{scope}:{seq}` and
 * embeds the customer's Telegram id, which is the leak `publicRef` exists to prevent.
 *
 * The server insists on the same key for a second reason: every path parameter on this API is
 * asserted to be a `UUID` or an `int`, so a `{publicRef}` route typed as a pattern-checked
 * string would not have been mountable at all.
 */
export function intentDetailPath(intentId: string): string {
  return `${PATH.railIntents}/${encodeURIComponent(intentId)}`;
}

/**
 * The wizard, opened on an audience the operator has already composed.
 *
 * The token is `encodeSegment`'s output verbatim — the same bytes `/users?segment=` walks and
 * the same bytes `POST /api/broadcasts` freezes — so the audience an operator approved is
 * provably the audience they were looking at. `null` opens an empty wizard, which is the
 * "start from nothing" case rather than "everyone".
 */
export function broadcastNewPath(segmentToken: string | null): string {
  if (segmentToken === null) return PATH.broadcastNew;
  return `${PATH.broadcastNew}?segment=${encodeURIComponent(segmentToken)}`;
}

/**
 * One campaign, by its UUID.
 *
 * The id carries nothing about a customer — a campaign is a thing the console composed — so it
 * is safe in an address bar in a way no recipient identifier would be. `encodeURIComponent` for
 * the same reason `generationDetailPath` uses it: the value comes back off the wire, and a path
 * segment is not the place to trust a shape.
 */
export function broadcastDetailPath(broadcastId: string): string {
  return `${PATH.broadcasts}/${encodeURIComponent(broadcastId)}`;
}

/**
 * One person's record.
 *
 * The Telegram id is the key `/api/users/{id}` is addressed by, so it is unavoidable in the
 * path and fine there. Nothing else about a customer ever enters a URL: a name or a revealed
 * value in the address bar leaks through history, referrers and screenshots.
 */
export function userDetailPath(telegramUserId: number): string {
  return `${PATH.users}/${String(telegramUserId)}`;
}

/**
 * One user's chat transcript and dialogue history.
 */
export function chatDetailPath(telegramUserId: number): string {
  return `${PATH.chats}/${String(telegramUserId)}`;
}

/**
 * One generation attempt, by its UUID.
 *
 * `/generations` renders the attempt beside the list, from `?attempt=<uuid>`, so this deep
 * link is a second spelling of the same place rather than a second screen — `routes.tsx`
 * canonicalises it. The UUID is a pipeline identifier and carries nothing about a customer.
 */
export function generationDetailPath(attemptId: string): string {
  return `${PATH.generations}/${encodeURIComponent(attemptId)}`;
}
