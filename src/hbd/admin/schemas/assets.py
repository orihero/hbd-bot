"""The one asset body that is not metadata: the lyric sheet, as JSON.

§12.1 T7 is the whole reason this model exists rather than a ``PlainTextResponse``. A
same-origin response whose body is up to three thousand characters of customer-written free
text, served as ``text/plain``, is a document a browser may sniff as HTML and render at the
panel's origin under the operator's session cookie — and ``script-src 'self'`` does not stop
an inline event handler in it. React never sees it, so React's escaping never applies.

Wrapping the text in a JSON object fixes that at the source rather than relying on a header:
``application/json`` is not a renderable document type in any browser, the SPA reads
``text`` as a string and puts it through the same escaping every other value gets, and
``X-Content-Type-Options: nosniff`` (unconditional, from ``SecurityHeadersMiddleware``) is
then a second lock on a door that is already shut.
"""

from __future__ import annotations

from uuid import UUID

from hbd.admin.schemas.common import ApiModel

__all__ = ["AssetTextView"]


class AssetTextView(ApiModel):
    """A lyric sheet's content, revealed. ``{"assetId": …, "text": …}`` on the wire."""

    asset_id: UUID
    #: The sheet exactly as it was typeset for the customer — byte for byte, never
    #: normalised, never case-folded, never re-encoded. U+02BB in ``Gʻulom`` is correct Uzbek
    #: Latin orthography and the reveal path is the one place the whole string is returned,
    #: so any "tidying" here would corrupt the very value an operator opened this to check.
    text: str
