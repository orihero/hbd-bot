/**
 * `GET /api/admins` — the operator roster: who can sign in to this panel, and who cannot.
 *
 * Transcribed from `bayram/admin/schemas/admins.py` (`AdminAccountView`, `AdminRosterResponse`)
 * over `bayram/admin/routers/admins.py`. Eight fields, all camelCase on the wire because
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
 * ## One write: `POST /api/admins`
 *
 * Creating an operator is the first of §6.8's four account writes to land. The other three —
 * `PATCH /admins/{id}`, `POST /admins/{id}/reset-password` and
 * `DELETE /admins/{id}/sessions` — are still future work and still 404 today, so this module
 * exports one writer and no more; adding another here is how a button that 404s gets drawn.
 *
 * **It needs a step-up, and the subject is the USERNAME.** Every other subject-scoped action
 * in this console re-authenticates against a row that already exists — a Telegram id, a
 * campaign UUID. This one cannot: the id it would name is minted by the insert being asked
 * for. So the grant is `admin.manage:{username}`, taken from the refusal's `details`
 * verbatim like every other, and the practical consequence for a form is that **editing the
 * username after re-authenticating invalidates the grant** — which is the point, not a
 * defect: the owner re-authenticated to create *that* operator.
 *
 * **The role half is `ADMIN_MANAGE_WRITE` and it is OWNER's alone**, so the three other roles
 * get a flat `FORBIDDEN` here exactly as they do on the roster read — never a step-up prompt,
 * which no password could satisfy. A caller that already has a 403 on the list read must not
 * draw a create button at all.
 *
 * **`role: "owner"` is refused with `INVALID_INPUT` (422), not accepted.** The database holds
 * one active owner (`ix_admin_users_active_owner`); ownership moves with
 * `python -m bayram.admin.bootstrap --reset-owner` on the host. The refusal carries that
 * sentence, so render the server's message rather than a generic "invalid input".
 *
 * **A taken username is `CONFLICT` (409)** — the ordinary case is retyping a name already on
 * the roster in front of you — and so is a roster that has reached `MAX_ADMIN_ACCOUNTS`.
 *
 * **The password goes up and never comes back.** The response is an `AdminAccountView` like
 * any other row, with `mustChangePassword: true`: the account holds a credential its holder
 * did not choose, and the first sign-in reaches nothing until it is replaced. Nothing here
 * stores, echoes or logs what was sent.
 */

import { z } from "zod";

import { adminRoleSchema } from "./auth";
import { request, type ApiResult } from "./client";
import { ADMINS_PREFIX, MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS } from "./constants";
import { reasonedRequestSchema } from "./reveal";

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
/* POST /api/admins                                                            */
/* -------------------------------------------------------------------------- */

/**
 * The shortest login this route accepts, and the longest.
 *
 * `bayram.admin.schemas.admins.MAX_ADMIN_USERNAME_CHARS` is 32 — half of
 * `admin_users.username`'s 64 — because the audit boundary refuses any
 * `[A-Za-z0-9_-]{40,}` run as credential-shaped, and a 44-character login would be a legal
 * account whose every audit row was rejected.
 */
export const MIN_ADMIN_USERNAME_CHARS = 3;
export const MAX_ADMIN_USERNAME_CHARS = 32;

/**
 * `ADMIN_USERNAME_PATTERN`, restated so a form refuses before a round trip that would write
 * no audit row.
 *
 * The charset is the step-up scope's, not a house style: the name travels into
 * `admin_sessions.step_up_scope` as `admin.manage:{username}` and into
 * `admin_audit_log.subject_id`, and both columns are closed character classes. `:` is
 * excluded on top of that because it is the scope separator, and `@` is in neither class —
 * **an email-shaped login cannot be created from this console**, only from the bootstrap CLI.
 *
 * Lowercase is required rather than folded, because a scope is compared byte for byte: a
 * form that sent `Dilnoza` after re-authenticating for `admin.manage:dilnoza` would earn a
 * 403 nobody can debug. Lowercase the field as the operator types instead of accepting it.
 */
export const ADMIN_USERNAME_PATTERN = /^[a-z0-9][a-z0-9._-]*[a-z0-9]$/;

/**
 * `schemas.admins.AdminCreateRequest` — the reason trio, a name, a password and a role.
 *
 * There is no `isActive`, no `mustChangePassword` and no `id`: a new account is active, it
 * always holds a password somebody else chose, and its id is the database's. `role` accepts
 * `"owner"` here because the SERVER is what refuses it, with a sentence naming the CLI that
 * does hand ownership over — a client-side narrowing would hide that sentence.
 */
export const adminCreateRequestSchema = reasonedRequestSchema.extend({
  username: z
    .string()
    .min(MIN_ADMIN_USERNAME_CHARS)
    .max(MAX_ADMIN_USERNAME_CHARS)
    .regex(ADMIN_USERNAME_PATTERN),
  password: z.string().min(MIN_PASSWORD_CHARS).max(MAX_PASSWORD_CHARS),
  role: adminRoleSchema,
});
export type AdminCreateRequest = z.infer<typeof adminCreateRequestSchema>;

/* -------------------------------------------------------------------------- */
/* The routes                                                                  */
/* -------------------------------------------------------------------------- */

/** The route templates, as a failure names them. */
export const ADMINS_ENDPOINT = {
  list: "GET /api/admins",
  create: "POST /api/admins",
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

/**
 * Add one operator account. **OWNER only, and it needs a live `admin.manage:{username}` grant.**
 *
 * Expect `STEP_UP_REQUIRED` on the first attempt and drive `POST /api/auth/step-up` from the
 * refusal's `details` — then replay this identical body, because a grant authorises an action
 * on a subject and the server has no memory of the request that was refused. Editing the
 * username between the two spends the grant on a name nobody asked for and earns another 403.
 *
 * On 201 the answer is the row the database wrote — `id`, `createdAt` and `passwordChangedAt`
 * are its answers, not an echo — and `mustChangePassword` is `true`. Append it to the roster
 * rather than refetching blind; the account cannot reach anything until its holder replaces
 * the password.
 *
 * The refusals worth branching on: `CONFLICT` (409) for a username already taken or a roster
 * at `MAX_ADMIN_ACCOUNTS`, and `INVALID_INPUT` (422) for `role: "owner"` — whose message
 * names the CLI that does move ownership and is worth rendering verbatim.
 */
export function createAdmin(
  body: AdminCreateRequest,
  signal?: AbortSignal,
): Promise<ApiResult<AdminAccountView>> {
  return request({
    endpoint: ADMINS_ENDPOINT.create,
    path: ADMINS_PREFIX,
    method: "POST",
    body,
    schema: adminAccountViewSchema,
    ...(signal === undefined ? {} : { signal }),
  });
}
