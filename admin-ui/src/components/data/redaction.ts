/**
 * The client-side redaction predicate `JsonViewer` applies — §11.4's "belt-and-braces".
 *
 * Its own module for two reasons: `JsonViewer.tsx` stays a module of components only (Fast
 * Refresh), and the rule is worth reading and testing on its own, because getting it wrong
 * is what puts a credential on a shared screen.
 *
 * ## What this is and is not
 *
 * §12.3 puts masking SERVER-side, in `hbd/admin/serializers/redaction.py`, at the response
 * boundary: "not a CSS blur, not a client toggle — an unmasked value must never be in a JSON
 * payload the operator did not explicitly request". That is the control that matters, and
 * this one cannot substitute for it: by the time a viewer sees a value it is already in the
 * browser's memory, and a reader with devtools open is not stopped by anything here.
 *
 * What it does buy is real. `*_api_key`, `*token`, `*secret` and `*_url` are the fields
 * §12.3 marks **"never returned at any role, revealed or not"** — so one appearing in a
 * payload is a server bug, and the failure mode of that bug is a credential in a screenshot
 * pasted into Slack or in a support recording. Masking on the way to the DOM turns an
 * exposure into an anomaly the operator can see and report.
 *
 * The key is matched with `_` removed and case folded, so the wire's camelCase (`redisUrl`,
 * `adminAuditHmacKey`) and the database's snake_case (`redis_url`, `openai_api_key`) are one
 * rule. Case folding is safe here and only here because these are OUR key names: the ban
 * inside `components/domain/` exists for user-written VALUES, not for the keys of a config
 * object.
 */

/**
 * The four suffixes §11.4 names. `url` matches bare as well as suffixed: a key called
 * exactly `url` is the presigned-link case, and a presigned link IS the credential.
 */
export const REDACTED_KEY_SUFFIXES = ["apikey", "token", "secret", "url"] as const;

/** Whether a key's value must never reach the DOM. Matches camelCase and snake_case alike. */
export function isRedactedKey(key: string): boolean {
  const folded = key.replace(/_/g, "").toLowerCase();
  return REDACTED_KEY_SUFFIXES.some((suffix) => folded.endsWith(suffix));
}
