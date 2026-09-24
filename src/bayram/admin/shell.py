r"""The SPA shell as a one-substitution template: the per-response style nonce, and nothing else.

``SecurityHeadersMiddleware`` mints a fresh style nonce for every response and publishes it
on the request state. Until this module existed, **nothing read it**: the policy said
``style-src 'self' 'nonce-<per-response>'`` and the bundle never learned the value, so every
``<style>`` element the SPA injects at runtime was blocked.

**The nonce currently reaches no consumer, and that is correct — audited 2026-09-19.** The
paragraph that used to stand here named ``react-remove-scroll`` (mounted by every Radix
modal, injecting its scroll-lock stylesheet through ``react-style-singleton``) as the thing
blocked without a nonce, and cited a ``src/lib/csp.ts`` that calls ``get-nonce``'s
``setNonce``. All of that was true of ``admin-ui/``, the legacy console deleted on
2026-09-16. It has never been true of ``admin-dashboard/``, which is what ships: Radix,
``react-remove-scroll``, ``react-style-singleton`` and ``get-nonce`` are not dependencies and
are not installed even transitively, and the built bundle contains no
``createElement("style")``, no ``insertRule``, no ``adoptedStyleSheets`` and no
``__webpack_nonce__``. Its three dialogs (``components/ConfirmDialog.tsx``,
``features/support/SupportGroupDialog.tsx``, ``features/reveal/DialogShell.tsx``) lock
scrolling by assigning ``document.body.style.overflow`` — the CSSOM, which CSP does not
police — so the background-keeps-scrolling symptom this module was written to prevent cannot
occur. A consumer built today would read the meta and hand the value to nobody. **Do not
port one back on the strength of this docstring alone.**

What the substitution still buys is that the day a dependency *does* inject a ``<style>``
element, the nonce is already in the document and the fix is one module rather than a
policy change. Re-check before building anything on it::

    grep -rE 'createElement\("style"|insertRule|adoptedStyleSheets' \
        src/bayram/admin/static/assets/*.js

The distinction that made the old paragraph subtle is still worth keeping: style
*attributes* — React's ``style={{}}``, and any library positioning a popover with
``node.style.setProperty`` — go through the CSSOM and are not policed. Only a real
``<style>`` **element** appended to the document is. Do not "fix" ``style={{}}`` call sites.

**The shape.** ``admin-dashboard/index.html`` ships a meta element whose ``content`` is the literal
:data:`CSP_NONCE_PLACEHOLDER`; this module swaps that token for the response's nonce as the
shell is served. The shell is already ``no-store`` (it is deliberately outside
``IMMUTABLE_PATH_PREFIX`` — it is the one filename that never changes), so a per-response
body costs nothing a cache could have saved, and ``/assets/*`` stays byte-identical and
immutable. The nonce reaches exactly one document, the one whose header carries it.

**Why a meta element rather than an inline ``<script>`` assigning a global.** ``script-src``
is ``'self'`` with no nonce of its own and must stay that way — the moment the shell needs
an inline script, somebody adds ``'nonce-…'`` to ``script-src`` and the panel's strongest
directive is weakened to deliver a style fix.

The substitution is deliberately dumb — one ``str.replace`` of an unmistakable token — and
the nonce is validated against the base64url alphabet before it is spliced into an HTML
attribute. ``secrets.token_urlsafe`` cannot emit anything else, so the guard exists for the
day somebody changes how the nonce is minted.
"""

from __future__ import annotations

import re
from typing import Final

from bayram.logging import get_logger

__all__ = [
    "CSP_NONCE_META_NAME",
    "CSP_NONCE_PLACEHOLDER",
    "render_shell",
]

_LOGGER: Final = get_logger(__name__)

#: The token ``admin-dashboard/index.html`` carries and this module replaces. Chosen to be
#: impossible to type by accident and trivially greppable across both languages;
#: ``tests/test_admin/test_spa_nonce.py`` asserts the checked-in HTML still contains it, so
#: renaming it on one side alone fails the suite rather than a browser.
CSP_NONCE_PLACEHOLDER: Final[str] = "__BAYRAM_CSP_NONCE__"

#: The ``name`` of the meta element this module stamps the nonce into. **No SPA code reads
#: it today** — the consumer the previous wording named (``src/lib/csp.ts``) never existed in
#: ``admin-dashboard/``; it belonged to the deleted ``admin-ui/``. See the module docstring
#: before writing one.
CSP_NONCE_META_NAME: Final[str] = "csp-nonce"

#: base64url, which is all ``secrets.token_urlsafe`` produces. Anything else could close the
#: attribute and inject markup into the one document served at the panel's own origin.
_NONCE_ALPHABET: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9_-]*\Z")


def render_shell(html: str, nonce: str) -> str:
    """Return the shell with this response's style nonce in place of the placeholder.

    A shell with no placeholder is served unchanged and logged at WARNING. That combination
    — rather than a refusal — is deliberate: it is the shape of a bundle built before this
    change, and an operator reaching for the console during an incident is better served by
    a panel whose modals do not lock the background than by a 500. The log line is the thing
    that keeps it from being silent, which is the failure mode this module exists to end.
    """
    if _NONCE_ALPHABET.fullmatch(nonce) is None:
        raise ValueError(
            "the style nonce is not base64url; refusing to splice it into an HTML attribute"
        )
    if CSP_NONCE_PLACEHOLDER not in html:
        _LOGGER.warning(
            "the SPA shell carries no style-nonce placeholder; every <style> element the "
            "bundle injects at runtime will be blocked by the CSP. Rebuild with `make "
            "ui-build`.",
            extra={"event": "admin.spa.nonce_placeholder_missing"},
        )
        return html
    return html.replace(CSP_NONCE_PLACEHOLDER, nonce)
