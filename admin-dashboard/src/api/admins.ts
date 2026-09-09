/**
 * `GET /api/admins` — the operator roster: who can sign in to this panel, and who cannot.
 *
 * Transcribed from `hbd/admin/schemas/admins.py` (`AdminAccountView`, `AdminRosterResponse`)
 * over `hbd/admin/routers/admins.py`. Eight fields, all camelCase on the wire because
 * `ApiModel` sets `alias_generator=to_camel`; they are transcribed byte for byte, because a
 * prettier local name would make the `safeParse` in `client.ts` a permanent `SCHEMA_DRIFT`
 * banner.
 *
 * ## There is one route, it takes no parameters, and it does not page
 *
 * The handler is `async def list_admins(db: Db)` — no `limit`, no `cursor`, no `q`, no
 * `role`, no `includeInactive`. Anything appended to the query string is simply unbound, so
 * filtering and sorting are the screen's own work. The envelope is `{items}` and **nothing
 * else**: no `nextCursor`, no `total`, no `hasMore`, so there is deliberately no
 * `pageMetaSchema` here and this module imports nothing from `./pagination`. The server caps
 * the read at `MAX_ADMIN_ACCOUNTS`, and that bound is the shape of the question rather than a
 * deferred pagination default — "who has access?" has one useful answer and it is the whole
 * list at once.
 *
 * Rows arrive **oldest account first** (`created_at ASC, id ASC`, the id tiebreak so two
 * accounts created in one transaction cannot swap places between requests). That order is the
 * stable default a client sorts away from, never something to assume was chosen for display.
 *
 * ## `password_hash` is absent, not masked — and must stay unrepresented here
 *
 * The argon2id PHC string carries its own salt and parameters, so there is no redacted form
 * of it worth anything to a panel and every form of it is worth something to an attacker
 * holding a response body. The server names its eight exposed fields one at a time rather
 * than projecting the row and dropping a key; the schema below does the same, so a column
 * somebody adds to `admin_users` next cannot arrive here by accident. No field, no
 * placeholder, no reveal affordance for the credential — at any role.
 *
 * ## `lastLoginAt: null` is "never signed into", not "signed in long ago"
 *
 * It is the only nullable field on the row, and the schema's own docstring calls the
 * distinction out as the fact worth chasing after a handover. A UI that renders both as a
 * dash destroys the one signal this endpoint carries for free.
 *
 * ## `isActive: false` is a row that stays in the list
 *
 * An operator is deactivated, never deleted — the audit log points at these rows and deleting
 * one would make every action they ever took unattributable. The flag is on the wire so a
 * panel can grey them rather than omit them; a roster that hides them answers "who has
 * access?" with a number smaller than the number of credentials that exist.
 *
 * ## Usernames are in the clear, and that is not a masking loophole
 *
 * §12.3's masking governs *customer* personal data. An operator is staff, their account is
 * the thing this endpoint exists to enumerate, and a roster of `o•••` answers no question
 * anybody opens it to ask (`mask_name` is deliberately not imported on the server side
 * either). So `username` gets no `MaskedValue`, no step-up, no reveal button — and
 * `admin_users` carries no retention clock, so it has no purged state to render.
 *
 * ## Roles: OWNER, and no step-up
 *
 * The router carries one dependency, `require_permission(Permission.ADMIN_READ)`, whose cell
 * is `_row(owner=_W)` — owner only, **step-up `NONE`**. §6.8 line 949 gives `GET /admins` a
 * bare `W` while the four account writes below it each carry `W +S`; §12.2's collapsed
 * `W+S` row was not followed and has since been split to match (lines 1883-1884), because
 * the router guard is `check_role`, which holds no subject and would answer
 * `STEP_UP_REQUIRED` to an OWNER for ever — including one holding a valid `admin.manage`
 * grant. So the other three roles get a plain **403 `FORBIDDEN`** (never
 * `STEP_UP_REQUIRED`), a refusal a caller must render as a flat denial with no
 * re-authentication prompt and no retry: the guard writes a `permission.denied` audit row in
 * its own committed transaction before raising, so every attempt costs a row in the log.
 *
 * ## There are no writes on this build
 *
 * `admins.py` declares exactly one route and its opening line says it: "It is a read and it
 * writes nothing." `Permission.ADMIN_MANAGE` exists in the matrix and in `STEP_UP_ACTIONS`
 * but no route declares it. `POST /admins`, `PATCH /admins/{id}`,
 * `POST /admins/{id}/reset-password` and `DELETE /admins/{id}/sessions` are §6.8 future work
 * and will 404 today — so this module exports no writer, and adding one here is how a button
 * that 404s gets drawn.
 */

import { z } from "zod";

import { adminRoleSchema } from "./auth";
import { request, type ApiResult } from "./client";
import { ADMINS_PREFIX } from "./constants";

/* The role vocabulary is declared beside `MeResponse`, its first consumer, and imported here
   rather than spelled a second time: two tuples of one closed vocabulary drift, and the drift
   shows up as a role pill that renders as an unknown member or as a `SCHEMA_DRIFT` banner for
   a role the server has always sent. `auth.ts` exports no `AdminRole` type; consumers take it
   from `@/lib/rbac`, which derives it from `MeResponse["role"]` — the same four members. */
export { ADMIN_ROLE_VALUES, adminRoleSchema } from "./auth";

/* -------------------------------------------------------------------------- */
/* Scalars                                                                     */
/* -------------------------------------------------------------------------- */

/** RFC 3339, `Z`-suffixed. A string, for `auth.ts`'s reason. */
const timestampSchema = z.string();

/* -------------------------------------------------------------------------- */
/* GET /api/admins                                                             */
/* -------------------------------------------------------------------------- */

/**
 * One `admin_users` row as the panel sees it. Every field the server exposes is here, and
 * every field it withholds is absent rather than nulled.
 */
export const adminAccountViewSchema = z.object({
  id: z.string().uuid(),
  /** Already casefolded and trimmed by `normalize_username`; ≤64 chars. Staff, so in the clear. */
  username: z.string(),
  role: adminRoleSchema,
  /** `false` = the account exists and cannot sign in. Never a reason to drop the row. */
  isActive: z.boolean(),
  /** `true` = the credential somebody else chose is still the credential on this account. */
  mustChangePassword: z.boolean(),
  /** `null` = never signed into, which is not the same fact as a sign-in that is merely old. */
  lastLoginAt: timestampSchema.nullable(),
  /** The instant every session issued before it became void (§12.1 T9). Never null. */
  passwordChangedAt: timestampSchema,
  createdAt: timestampSchema,
});
export type AdminAccountView = z.infer<typeof adminAccountViewSchema>;

/**
 * The whole roster in one response.
 *
 * `items` is the only key — there is no `meta` to compose in, and inventing one "just in
 * case" would be a page control drawn in front of a list that does not page.
 */
export const adminRosterSchema = z.object({
  items: z.array(adminAccountViewSchema),
});
export type AdminRoster = z.infer<typeof adminRosterSchema>;

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. */
export const ADMINS_ENDPOINT = {
  list: "GET /api/admins",
} as const;

/**
 * Every operator account, oldest first, deactivated ones included.
 *
 * OWNER only. The three other roles resolve to a 403 `FORBIDDEN` that has already written a
 * `permission.denied` audit row by the time this promise settles — so a caller must not poll
 * this route, must not auto-retry it on a refusal, and must not offer a Retry button that
 * would mint another row against an operator who did nothing wrong.
 */
export function listAdmins(signal?: AbortSignal): Promise<ApiResult<AdminRoster>> {
  return request({
    endpoint: ADMINS_ENDPOINT.list,
    // No query builder: the route accepts no parameters, so there is no `?` to compose.
    path: ADMINS_PREFIX,
    schema: adminRosterSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
