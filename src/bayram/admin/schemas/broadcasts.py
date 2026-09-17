"""Wire models for ``/broadcasts`` — what an operator may compose, and what comes back.

**Everything expensive about a campaign is decided in this module, before a row exists.** A
broadcast is the one thing this API does that cannot be undone one record at a time: forty
thousand messages leave, and a body Telegram refuses is refused for every one of them
identically. So the compose-time refusals live here — in the schema, not the handler —
because a handler is a place a second endpoint forgets to call and a model is not.

**The three refusals, and why each is a 422 rather than a discovery.**

* **Length, measured on the string that will actually be sent.** The body is authored as
  Telegram HTML and rendered by :func:`render_body_html` — literal runs escaped, allowlisted
  tags kept — so an ampersand the operator typed once costs five characters on the wire and
  one in the editor. A 4 096-character body of ampersands is 20 480 characters to Telegram
  and a rejected message to everybody. Both lengths are therefore bounded: the RAW text
  against the column it is stored in, and the RENDERED text against Telegram's ceiling. They
  are not the same bound and neither implies the other — ``&`` renders longer than it is
  stored, ``&nbsp;`` renders shorter.
* **Markup, against an allowlist and never a stripper.** :data:`TELEGRAM_TAGS` is what
  Telegram's HTML parser accepts; anything else is refused by name of the rule. Stripping
  would be the worse failure in both directions: a ``<script>`` silently deleted teaches the
  operator nothing, and an unclosed ``<b>`` silently closed changes what the message says.
  An unclosed tag is a ``TelegramBadRequest`` at send time for *every* recipient, so
  validating once at compose is the difference between a caught typo and a dead campaign.
* **The button's URL, which is a destination and not a string.** It must be absolute,
  ``http``/``https``, and carry a host. A relative path in an inline button is a Telegram
  400; a ``javascript:`` or ``tg://`` scheme in a message sent to the whole database is not
  a typo worth tolerating.

**No ``{placeholder}`` interpolation is accepted at any layer, and this is where that is
enforceable.** ``broadcast_bodies`` holds no personal data precisely because the body is the
same text for everyone who reads that language. There is no field here that could carry a
customer's name and no substitution step that could put one there, which is what keeps one
rendered message reviewable before a send instead of forty thousand unreviewable ones.

**The recipient projection carries no Telegram id, and that is the one masking rule this
module differs from ``/users`` on.** :class:`~bayram.admin.schemas.users.UserView` publishes the
raw id beside its mask because every ``/users/**`` route keys on it. Nothing here does: a
recipient row is addressed by its own UUID, so :class:`BroadcastRecipientView` carries the
mask alone. A campaign's recipient list is a membership disclosure — "these are the people we
decided were lapsed subscribers" — and it is the one list in this API that can be paged
through in bulk, so the id is absent from the bytes rather than withheld by a renderer.

**Two fields exist on the row and deliberately never reach this wire.**
``broadcast_bodies.media_file_id`` is minted by Telegram on the first send and is worker-
owned; accepting one on the way in would let the panel address a file this deployment never
uploaded, and publishing one on the way out would put a live handle to our own bot's storage
into a browser. ``broadcast_recipients.telegram_user_id`` is the masking rule above.

**The audience is frozen at creation, so the shapes below are not the blueprint's.**
§3.3 put ``expectedAudienceSize`` on the schedule request, where it guarded a re-count
between the preview and the click. Recipient rows are materialised at CREATION now, so a
re-count at schedule time would be a number nobody sends to: the drift catch moves to
:class:`BroadcastCreateRequest`, which is the request that actually decides who is in. For
the same reason :class:`BroadcastReviseRequest` carries a title and bodies and no segment —
re-pointing a frozen audience is not an edit, it is a different campaign.
"""

from __future__ import annotations

import html
from datetime import datetime
from html.parser import HTMLParser
from typing import Annotated, Any, Final
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator

from bayram.admin.schemas.actions import ReasonedRequest
from bayram.admin.schemas.common import ApiModel
from bayram.admin.schemas.page import PageMeta
from bayram.admin.schemas.segment import SegmentModel
from bayram.admin.serializers.redaction import mask_telegram_user_id
from bayram.bot.i18n import escape_html
from bayram.contracts import BroadcastKind, BroadcastRecipientState, BroadcastState, Language
from bayram.db.admin.broadcasts import BroadcastStats
from bayram.db.admin.views import BroadcastBodyView as BroadcastBodyRecord
from bayram.db.admin.views import (
    BroadcastDetail,
    BroadcastListItem,
    BroadcastProgress,
    BroadcastRecipientItem,
)
from bayram.db.enums import AuditReasonCode
from bayram.db.models.broadcast import BROADCAST_TITLE_LENGTH
from bayram.db.models.broadcast_body import (
    BROADCAST_BODY_LENGTH,
    BROADCAST_CAPTION_LENGTH,
    BUTTON_LABEL_LENGTH,
    BUTTON_URL_LENGTH,
    MEDIA_STORAGE_KEY_LENGTH,
)

__all__ = [
    "TELEGRAM_TAGS",
    "MAX_BODIES",
    "TERMINAL_STATES",
    "render_body_html",
    "BroadcastBodyInput",
    "BroadcastCreateRequest",
    "BroadcastReviseRequest",
    "BroadcastSendRequest",
    "BroadcastTestSendRequest",
    "BroadcastBodyView",
    "BroadcastProgressView",
    "BroadcastView",
    "BroadcastsPage",
    "BroadcastStateTotalView",
    "BroadcastStatsView",
    "BroadcastDetailView",
    "BroadcastRecipientView",
    "BroadcastRecipientsPage",
    "BroadcastTestSendResultView",
    "to_body_view",
    "to_broadcast_view",
    "to_broadcast_stats_view",
    "to_broadcast_detail_view",
    "to_recipient_view",
]

#: The tags Telegram's HTML parser accepts, written as Telegram documents them rather than as
#: a subset somebody found convenient. The aliases are here because Telegram takes them and an
#: operator who pastes ``<strong>`` out of a word processor should not be told it is invalid
#: markup — it is not, and refusing it would be this module inventing a rule.
#:
#: Four of Telegram's own are deliberately absent. ``<span class="tg-spoiler">`` is refused in
#: favour of ``<tg-spoiler>``, which means the identical thing without an attribute to police.
#: ``<pre class="language-…">`` is refused because a campaign is not a code listing and the
#: attribute is the only place a class name could ride in. ``<tg-emoji emoji-id="…">`` needs a
#: custom emoji this bot does not own, so it is a guaranteed ``TelegramBadRequest``.
#: ``<blockquote expandable>`` is refused for the attribute alone; the plain quote is allowed.
TELEGRAM_TAGS: Final[frozenset[str]] = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "code",
        "pre",
        "tg-spoiler",
        "blockquote",
        "a",
    }
)

#: The only tag that may carry an attribute, and the only attribute it may carry.
_ANCHOR: Final[str] = "a"
_HREF: Final[str] = "href"

#: One body per language and no more. ``len(Language)`` rather than ``4``: a fifth locale is a
#: fifth body, and a literal here would cap the new one out of every campaign silently.
MAX_BODIES: Final[int] = len(Language)

#: States a campaign never leaves. Published through :attr:`BroadcastView.is_terminal` so the
#: panel's "can this still be cancelled?" question is answered by the server's own set rather
#: than by a second copy of it in TypeScript that a new state would not be added to.
TERMINAL_STATES: Final[frozenset[BroadcastState]] = frozenset(
    {BroadcastState.COMPLETED, BroadcastState.CANCELLED, BroadcastState.FAILED}
)

#: The schemes an inline button may point at. ``http`` is allowed beside ``https`` because
#: Telegram accepts it and a link the operator pasted from a partner is not ours to upgrade —
#: silently rewriting it would be this layer editing a destination.
_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

#: Characters that must not appear anywhere in a URL. Checked BEFORE :func:`urlsplit`, which
#: strips ASCII tabs and newlines per WHATWG and would otherwise turn a URL with a newline
#: spliced into it into a clean one that no longer resembles what was submitted.
_URL_FORBIDDEN: Final[frozenset[str]] = frozenset(' \t\r\n"<>\\^`{|}')

#: An object-store key names a file we already hold; it is not a path this API composes.
#: Segments are ASCII, and ``..`` is refused outright rather than normalised, because the only
#: reader of this value is a storage client and the only thing traversal buys is a file the
#: operator was not shown.
_KEY_ALLOWED: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/"
)
_PARENT_SEGMENT: Final[str] = ".."

# The closed set of markup refusals. Fixed strings with no caller text in them, for the reason
# ``bayram.admin.errors._handle_validation`` states: a pydantic message is built from the
# submitted document, and this API's 422 carries field locations only. So the message is here
# for the test suite and the reader, and naming the offending tag would buy a reflection risk
# for a string no operator ever sees.
_UNKNOWN_TAG: Final[str] = "the text uses an HTML tag Telegram does not accept"
_BAD_ATTRIBUTE: Final[str] = "an HTML tag carries an attribute that is not allowed"
_SELF_CLOSING: Final[str] = "a self-closing HTML tag is not Telegram markup"
_UNBALANCED: Final[str] = "an HTML tag is not closed, or closes one that was never opened"
_NESTED_LINK: Final[str] = "a link may not contain another link"
_NOT_MARKUP: Final[str] = "the text contains a comment or declaration, which is not markup"
_INCOMPLETE_TAG: Final[str] = "an HTML tag is missing its closing '>'"
_BAD_HREF: Final[str] = "a link's href is not an absolute http(s) URL"
_BLANK_TEXT: Final[str] = "the message has no text once its markup is parsed away"
_TOO_LONG: Final[str] = "the message is longer than Telegram accepts"
_BAD_URL: Final[str] = "the button URL is not an absolute http(s) URL"
_BUTTON_PAIR: Final[str] = "a button needs both a label and a URL, or neither"
_BAD_STORAGE_KEY: Final[str] = "the media key is not a storage key this deployment wrote"
_BLANK_TITLE: Final[str] = "a campaign needs a title"
_NO_BODIES: Final[str] = "a campaign needs at least one body"
_TOO_MANY_BODIES: Final[str] = "a campaign has at most one body per language"
_DUPLICATE_LANGUAGE: Final[str] = "two bodies claim the same language"
_NAIVE_INSTANT: Final[str] = "scheduledFor must carry a UTC offset, e.g. 2026-08-30T12:00:00Z"


def render_body_html(text: str) -> str:
    """The exact string the sender will hand Telegram, or a ``ValueError`` naming the rule.

    Literal runs are escaped with the bot's own :func:`~bayram.bot.i18n.escape_html`; allowlisted
    tags are re-emitted canonically. Both halves matter: the escaping is what lets an operator
    write ``Tom & Jerry`` and ``5 < 6`` without knowing they are composing HTML, and the
    re-emission is what makes the result a *parse* rather than a pass-through — a tag that
    survives this function was recognised, and one that was not is a refusal.

    **Character references are decoded and re-encoded**, so ``&amp;`` and ``&`` both render as
    ``&amp;`` and the function is idempotent on its own output. That is what makes the length
    measured here the length Telegram will see no matter which of the two an operator typed.

    **A bare ``<`` is text; an unterminated tag is a refusal.** ``5 < 6`` comes out as
    ``5 &lt; 6``, because a ``<`` that cannot begin a tag is a character somebody typed. ``<b``
    with no ``>`` is refused, and the reason is measured rather than aesthetic:
    ``HTMLParser`` DISCARDS an unterminated tag and everything after it — ``"a <b"`` reaches
    the handlers as ``"a "`` alone — so accepting it would silently delete the tail of a
    message, which is the exact failure this module refuses to let a stripper commit.

    Raises ``ValueError`` and never anything else, because its two callers are a pydantic
    validator — for which a ``ValueError`` *is* the refusal — and the sender, for which stored
    text that fails here is a defect its own guard must surface rather than swallow.
    """
    return _scan(text).rendered


class _Scanned:
    """What one pass over a body produced: the wire string, and the words inside it.

    A plain object rather than a dataclass because it is written once by a parser callback
    loop and read once by the caller; the two fields are built incrementally, which is the one
    shape a frozen dataclass cannot hold.
    """

    __slots__ = ("literal", "rendered")

    def __init__(self, rendered: str, literal: str) -> None:
        self.rendered = rendered
        self.literal = literal


class _MarkupParser(HTMLParser):
    """Telegram's HTML, and nothing that merely looks like it.

    ``convert_charrefs=True`` so ``&amp;`` reaches :meth:`handle_data` as ``&`` and is escaped
    back on the way out. Every other handler is overridden to refuse: a comment, a doctype or
    a processing instruction is not markup Telegram parses, and inheriting ``HTMLParser``'s
    default — which drops them — would be exactly the silent strip this module exists to
    avoid.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._literal: list[str] = []
        self._open: list[str] = []

    def result(self) -> _Scanned:
        """The two strings, after :meth:`close`. Refuses a document with a tag still open."""
        if self._open:
            raise ValueError(_UNBALANCED)
        return _Scanned("".join(self._parts), "".join(self._literal))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in TELEGRAM_TAGS:
            raise ValueError(_UNKNOWN_TAG)
        if tag == _ANCHOR:
            if _ANCHOR in self._open:
                raise ValueError(_NESTED_LINK)
            self._parts.append(f'<a href="{html.escape(_href(attrs), quote=True)}">')
        else:
            if attrs:
                raise ValueError(_BAD_ATTRIBUTE)
            self._parts.append(f"<{tag}>")
        self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._open or self._open[-1] != tag:
            # Both directions of unbalanced: a stray close, and a close that crosses another
            # tag's span. Telegram refuses the second as firmly as the first, and an operator
            # who wrote ``<b><i>x</b></i>`` meant the nesting they typed.
            raise ValueError(_UNBALANCED)
        self._open.pop()
        self._parts.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        # None of Telegram's tags is void, so ``<b/>`` is either a typo or markup from
        # somewhere else. Refused rather than treated as an open-and-close, which would put a
        # pair of tags into the message the operator did not write.
        raise ValueError(_SELF_CLOSING)

    def handle_data(self, data: str) -> None:
        self._parts.append(escape_html(data))
        self._literal.append(data)

    def handle_comment(self, data: str) -> None:
        del data
        raise ValueError(_NOT_MARKUP)

    def handle_decl(self, decl: str) -> None:
        del decl
        raise ValueError(_NOT_MARKUP)

    def handle_pi(self, data: str) -> None:
        del data
        raise ValueError(_NOT_MARKUP)

    def unknown_decl(self, data: str) -> None:
        del data
        raise ValueError(_NOT_MARKUP)


def _href(attrs: list[tuple[str, str | None]]) -> str:
    """The one attribute an anchor may carry, validated as a destination."""
    if len(attrs) != 1 or attrs[0][0] != _HREF:
        raise ValueError(_BAD_ATTRIBUTE)
    url = attrs[0][1]
    if url is None or not _is_absolute_http_url(url):
        raise ValueError(_BAD_HREF)
    return url


#: What may follow a ``<`` for ``HTMLParser`` to read it as the start of a tag, a closing tag,
#: a declaration or a processing instruction. A ``<`` followed by anything else — a space, a
#: digit — is data, which is why ``5 < 6`` needs no escaping by the operator.
_TAG_OPEN_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!?/"
)


def _has_unterminated_tag(text: str) -> bool:
    """Whether the text ends inside a tag that never closed.

    Checked BEFORE the parse rather than after, because ``HTMLParser`` does not report this:
    it drops the unterminated tag and every character after it, and by the time the handlers
    have run there is nothing left to notice the loss with. An unterminated tag can only be the
    LAST one — once ``<x`` opens, the parser consumes forward to the next ``>`` — so the final
    ``<`` is the only position worth testing.
    """
    opened = text.rfind("<")
    if opened < 0 or ">" in text[opened:]:
        return False
    return text[opened + 1 : opened + 2] in _TAG_OPEN_CHARS


def _scan(text: str) -> _Scanned:
    """One pass, producing the wire string and the words. Raises ``ValueError`` on refusal."""
    if _has_unterminated_tag(text):
        raise ValueError(_INCOMPLETE_TAG)
    parser = _MarkupParser()
    parser.feed(text)
    parser.close()
    return parser.result()


def _is_absolute_http_url(raw: str) -> bool:
    """Whether ``raw`` is a URL a Telegram button can actually open.

    Absolute, ``http``/``https``, with a host that carries a dot — a broadcast button points
    at a public name, and ``https://intranet/`` in a message to the whole database is a
    mistake rather than a deployment this product has. No userinfo: ``https://user:pw@host/``
    both leaks a credential into forty thousand chat logs and is the shape a phishing link
    uses to hide its real host behind a plausible one.
    """
    if not raw or any(char in _URL_FORBIDDEN or ord(char) < 0x20 for char in raw):
        return False
    parsed = urlsplit(raw)
    if parsed.scheme not in _URL_SCHEMES or "@" in parsed.netloc:
        return False
    host = parsed.hostname
    return host is not None and "." in host and not host.endswith(".")


def _is_storage_key(raw: str) -> bool:
    """Whether ``raw`` is shaped like a key this deployment's own uploader wrote."""
    if not raw or raw.startswith("/") or raw.endswith("/"):
        return False
    segments = raw.split("/")
    return all(
        segment and segment != _PARENT_SEGMENT and set(segment) <= _KEY_ALLOWED
        for segment in segments
    )


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------
class BroadcastBodyInput(ApiModel):
    """One language's message: text, an optional image, an optional button. Nothing else.

    The text is stored **verbatim**. Every check below reads it and none of them rewrites it:
    the operator's copy is the artefact they review before the send and the one an auditor
    reads afterwards, so a body that reaches the database differs from the one that was typed
    in no byte. The canonicalisation :func:`render_body_html` performs happens on the way to
    Telegram, where it is a rendering, and never on the way to the column.
    """

    language: Language
    #: Bounded by the COLUMN here; bounded again, rendered, by :meth:`_fits_telegram`. See the
    #: module docstring on why one bound does not imply the other.
    text: Annotated[str, Field(min_length=1, max_length=BROADCAST_BODY_LENGTH)]
    #: The operator's upload in our own object store. ``None`` is a text message.
    #: ``media_file_id`` has no counterpart here on purpose: it is minted by Telegram on the
    #: first send and written by the worker, and a client that could supply one could address
    #: a file this deployment never uploaded.
    media_storage_key: Annotated[
        str | None, Field(default=None, max_length=MEDIA_STORAGE_KEY_LENGTH)
    ] = None
    button_label: Annotated[str | None, Field(default=None, max_length=BUTTON_LABEL_LENGTH)] = None
    button_url: Annotated[str | None, Field(default=None, max_length=BUTTON_URL_LENGTH)] = None

    @field_validator("text")
    @classmethod
    def _valid_markup(cls, text: str) -> str:
        """Parse the body and refuse it, or hand back the identical string.

        The parse result is DISCARDED. That is deliberate: what is stored is what was typed,
        and the rendering is recomputed at send time from the stored text by the same function
        — one renderer, one string, no second copy to fall out of step with the column.
        """
        scanned = _scan(text)
        if not scanned.literal.strip():
            raise ValueError(_BLANK_TEXT)
        return text

    @field_validator("button_url")
    @classmethod
    def _valid_button_url(cls, url: str | None) -> str | None:
        if url is not None and not _is_absolute_http_url(url):
            raise ValueError(_BAD_URL)
        return url

    @field_validator("media_storage_key")
    @classmethod
    def _valid_storage_key(cls, key: str | None) -> str | None:
        if key is not None and not _is_storage_key(key):
            raise ValueError(_BAD_STORAGE_KEY)
        return key

    @model_validator(mode="after")
    def _fits_telegram(self) -> BroadcastBodyInput:
        """The two ceilings, chosen by whether an image is attached.

        A photo caption is a quarter of a message, and ``ck_broadcast_bodies_caption_length``
        enforces the same 1 024 on the stored text. Enforcing it here as well is what makes an
        over-long caption a 422 naming the body rather than an ``IntegrityError`` raised
        half-way through a transaction that has already counted an audience.

        Measured on BOTH strings against the same ceiling. The raw one is the column's bound;
        the rendered one is Telegram's, and it is the larger of the two for any text carrying
        an ``&``, a ``<`` or a tag.
        """
        limit = (
            BROADCAST_BODY_LENGTH if self.media_storage_key is None else BROADCAST_CAPTION_LENGTH
        )
        if len(self.text) > limit or len(render_body_html(self.text)) > limit:
            raise ValueError(_TOO_LONG)
        return self

    @model_validator(mode="after")
    def _button_is_a_pair(self) -> BroadcastBodyInput:
        """``ck_broadcast_bodies_button_pair``, one layer up: a label with no URL is a dead
        button, and a URL with no label is a button nobody can see."""
        if (self.button_label is None) != (self.button_url is None):
            raise ValueError(_BUTTON_PAIR)
        return self


class BroadcastCreateRequest(ApiModel):
    """Compose a draft and freeze its audience.

    This is the request that decides WHO, which is why the drift catch is on it. The wizard
    renders a preview count from ``GET /api/segments/preview``; between that render and this
    call the world moves, and ``expectedAudienceSize`` lets the handler refuse rather than
    materialise an audience the operator never saw. It is optional because the same endpoint
    serves a caller that never rendered a preview, and a required field would make them
    invent a number.

    No reason code, and the asymmetry with :class:`BroadcastSendRequest` is the point: this
    call messages nobody. It writes rows and spends a count; the *authorisation* to put text
    in front of forty thousand people is the send, and that is where the accountability trio
    and the step-up sit.
    """

    title: Annotated[str, Field(min_length=1, max_length=BROADCAST_TITLE_LENGTH)]
    kind: BroadcastKind
    #: Stored on the row verbatim, never re-evaluated. See ``bayram.db.models.broadcast``.
    segment: SegmentModel
    bodies: tuple[BroadcastBodyInput, ...]
    #: What the operator was shown. ``None`` means "do not check".
    expected_audience_size: Annotated[int | None, Field(default=None, ge=0)] = None

    @field_validator("title")
    @classmethod
    def _title_is_not_blank(cls, title: str) -> str:
        return _checked_title(title)

    @field_validator("bodies")
    @classmethod
    def _one_body_per_language(
        cls, bodies: tuple[BroadcastBodyInput, ...]
    ) -> tuple[BroadcastBodyInput, ...]:
        return _checked_bodies(bodies)


class BroadcastReviseRequest(ApiModel):
    """Re-compose a DRAFT: the title and the whole set of bodies, replaced together.

    A whole replacement rather than a patch, because ``extra="forbid"`` plus optional fields
    cannot express "leave the Russian body alone" and "delete the Russian body" as two
    different requests — they are the same JSON. Sending the set makes the intent explicit and
    makes the handler's job a diff it can audit.

    There is no ``segment`` and no ``kind``. The recipient rows exist from creation, so a new
    filter here would describe an audience nobody is going to receive this; and the kind is
    what selects the eligibility rule the audience was built under. Both are a new campaign.
    """

    title: Annotated[str, Field(min_length=1, max_length=BROADCAST_TITLE_LENGTH)]
    bodies: tuple[BroadcastBodyInput, ...]

    @field_validator("title")
    @classmethod
    def _title_is_not_blank(cls, title: str) -> str:
        return _checked_title(title)

    @field_validator("bodies")
    @classmethod
    def _one_body_per_language(
        cls, bodies: tuple[BroadcastBodyInput, ...]
    ) -> tuple[BroadcastBodyInput, ...]:
        return _checked_bodies(bodies)


class BroadcastSendRequest(ReasonedRequest):
    """Authorise the send: now, or at a stated instant.

    ``scheduledFor`` absent means immediately — the two are one endpoint because they are one
    decision, and a separate "send now" route would be a second place to forget the step-up.

    **Naive is refused here; "in the past" is not.** A missing UTC offset is a property of the
    document and this layer can see it, so it is a 422 naming the field, in
    ``bayram.admin.window.require_aware``'s own words because an operator should not meet two
    spellings of one rule. Whether an instant has already passed is a question about a clock,
    and no schema in this package reads one: the handler owns ``now`` and refuses the past
    against the same instant it stamps the row with.
    """

    scheduled_for: datetime | None = None

    @field_validator("scheduled_for")
    @classmethod
    def _must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(_NAIVE_INSTANT)
        return value


class BroadcastTestSendRequest(ReasonedRequest):
    """Send the composed bodies to ONE account, to see what a recipient will see.

    ``telegramUserId`` is a field and not a lookup, but it is **not** the control: the handler
    refuses any id outside ``admin_broadcast_test_recipients``, because a route that put
    operator-authored text in front of an arbitrary customer on the strength of a session is
    an arbitrary-message endpoint however carefully it is audited. This model only bounds the
    shape — a Telegram id is positive, and ``ge=1`` is what stops ``0`` and negative chat ids
    (a channel, a group) from reaching a send that is meant for a person.

    It carries the accountability trio because a test send is still a message that leaves the
    building, and the audit row for it is the only record that it did.
    """

    telegram_user_id: Annotated[int, Field(ge=1)]


class BroadcastTestSendResultView(ApiModel):
    """What was asked of the worker, and of whom — masked.

    The raw Telegram id is not echoed even though the caller sent it, for
    :class:`BroadcastRecipientView`'s reason: this API does not put an unmasked account
    identifier into a response body nobody asked to reveal, and a caller who supplied a value
    does not need it read back to know what they typed.
    """

    broadcast_id: UUID
    telegram_user_id_masked: str
    #: The ARQ job this enqueued. Unique per call — a second test send exists precisely
    #: because the body changed, so it must not be deduplicated against the first.
    job_id: str
    requested_at: datetime


def _checked_title(title: str) -> str:
    """Refuse a title that is only whitespace. Never trims — a stored title is what was typed."""
    if not title.strip():
        raise ValueError(_BLANK_TITLE)
    return title


def _checked_bodies(bodies: tuple[BroadcastBodyInput, ...]) -> tuple[BroadcastBodyInput, ...]:
    """One body at least, one per language at most.

    The duplicate check is ``uq_broadcast_bodies_broadcast_id_language`` restated where it can
    still be a 422. Without it the second Russian body is an ``IntegrityError`` from inside a
    transaction that has already written a campaign row.
    """
    if not bodies:
        raise ValueError(_NO_BODIES)
    if len(bodies) > MAX_BODIES:
        raise ValueError(_TOO_MANY_BODIES)
    languages = {body.language for body in bodies}
    if len(languages) != len(bodies):
        raise ValueError(_DUPLICATE_LANGUAGE)
    return bodies


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------
class BroadcastBodyView(ApiModel):
    """One language's message, as composed and as it will be sent.

    **Both strings are on the wire, and neither is redundant.** ``text`` is what the operator
    typed and what the editor must load to let them change it; ``renderedText`` is the exact
    argument the sender passes Telegram, and it is the artefact a reviewer approves. Showing
    only the first would ask somebody to sign off on markup by imagining its parse; showing
    only the second would make the edit box lossy.

    ``renderedLength`` is what Telegram counts, published beside the ceiling the panel already
    knows, so the compose screen's character counter and this server's refusal agree.
    """

    language: Language
    text: str
    rendered_text: str
    rendered_length: int
    has_media: bool
    #: The object-store key, so the editor can show the image that is attached. The bytes are
    #: served by the asset route; this is a key, not a URL, and not a Telegram handle.
    media_storage_key: str | None
    #: Whether Telegram has already handed us a ``file_id`` for that image — i.e. whether the
    #: next recipient costs an upload. The id ITSELF is never published: it is a live handle
    #: into our own bot's file storage and it addresses nothing the panel can use.
    is_media_cached: bool
    button_label: str | None
    button_url: str | None


class BroadcastProgressView(ApiModel):
    """The funnel from audience to messages, as arithmetic rather than as a percentage.

    **The five outcome counters do not add up to the audience, and the shape says why.**
    ``audienceSize`` is what the segment counted at creation; ``recipientCount`` is how many
    rows the expansion actually wrote. They differ while a campaign is expanding and are equal
    on every healthy one afterwards, which is what makes ``isAudienceComplete`` a fact rather
    than an assumption — a half-written expansion is visible instead of hiding behind one
    number that looks right.

    ``unsettledCount`` is everything not yet in a terminal state: rows still ``pending`` AND
    rows a claim has moved to ``sending``. Those two are not separated here because the
    difference between them is a few seconds of a worker's life, and a panel that showed them
    apart would show a number that changes under the reader for no decision they can make.

    ``unknownCount`` is its own number and is never folded into ``failedCount``. A row left in
    ``sending`` by a killed job may or may not have reached the customer; reporting it as a
    failure claims a message did not arrive when it may well have.
    """

    audience_size: int
    recipient_count: int
    is_audience_complete: bool
    sent_count: int
    failed_count: int
    skipped_count: int
    undeliverable_count: int
    unknown_count: int
    #: The five terminal counters summed — the rows this campaign is finished with.
    settled_count: int
    #: ``recipientCount - settledCount``, floored at zero. A negative would mean the rollup
    #: disagrees with the rows it was recomputed from, and the rows are truth; the floor keeps
    #: a rollup bug from rendering as a nonsensical progress bar while the counters are
    #: repaired.
    unsettled_count: int


class BroadcastView(ApiModel):
    """One campaign: what it is, who authorised it, and how far it got.

    The segment DOCUMENT is not here — it is on the detail view. A list of twenty campaigns
    would otherwise carry twenty filter documents nobody on that screen reads; ``segmentHash``
    is what the list needs, because it is what answers "is this the segment I am looking at?"
    without comparing two JSON blobs field by field.
    """

    id: UUID
    title: str
    kind: BroadcastKind
    state: BroadcastState
    #: ``state`` is in :data:`TERMINAL_STATES` — this campaign will not move again.
    is_terminal: bool
    #: SHA-256 of the stored segment document. An identity, never a filter to re-run.
    segment_hash: str
    #: The ``now`` the segment was compiled against. With ``audienceSize`` it is the whole
    #: answer to "why did twelve fewer people get this than the preview said": they joined
    #: afterwards, and the audience was frozen here.
    audience_evaluated_at: datetime
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    #: Denormalised onto the row so this list renders without a join. The tamper-evident
    #: record of who did what, with the role they held at the time, is ``admin_audit_log``.
    created_by_admin_id: UUID | None
    created_by_username: str | None
    scheduled_by_admin_id: UUID | None
    scheduled_by_username: str | None
    #: The closed half of the send's accountability. The operator's prose is NOT here and is
    #: not on the row: ``admin_audit_log.reason_text`` owns it, because that column owns the
    #: 90-day clock that nulls it and the sweep that reads the clock.
    reason_code: AuditReasonCode | None
    reason_ref: str | None
    #: Why the RUN failed, from a closed vocabulary. Never a vendor's message.
    error_code: str | None
    progress: BroadcastProgressView


class BroadcastsPage(ApiModel):
    items: list[BroadcastView]
    meta: PageMeta


class BroadcastStateTotalView(ApiModel):
    """One tile's worth of the Campaigns strip: a state, and how many campaigns are in it."""

    state: BroadcastState
    count: int


class BroadcastStatsView(ApiModel):
    """``/broadcasts/stats`` — the strip above the campaign list, for its whole filter set.

    Every :class:`~bayram.contracts.BroadcastState` is present, in enum declaration order, with
    a count that may be ``0``. ``BroadcastState`` is a closed vocabulary, so a state with no
    campaigns is a question this response answers with a zero rather than one it leaves out —
    the argument ``OrderStateCountsView`` makes for the Orders bar, and the opposite of a time
    series, where a day nobody measured has to stay missing.

    **``reachedRecipients`` and ``audienceTotal`` are two integers and never a percentage.**
    A ratio in this API carries the two numbers it was formed from — ``RatioView`` in
    ``schemas/overview.py`` cannot be constructed without them — so that a reader can see what
    was divided and check it against the rows. Here the two are published plainly rather than
    wrapped, because both are exact counts rather than measurements of different things, and
    the SPA that draws "1 240 of 1 500" needs the pair either way. A deployment that has sent
    nothing has ``audienceTotal == 0``, which the panel renders as a dash and a reason rather
    than as "0%" — a rate with no denominator is not a number.

    **``lastSendAt`` is ``null`` when no campaign in this filter set has ever started.** It is
    ``MAX(broadcasts.started_at)``, a column that stays NULL until the first message of a run
    leaves, and the null crosses as a null: a deployment that has never sent anything is a
    fact, and an epoch or a creation date put there in its place would render as a real send
    nobody made.

    ``total`` is the sum of the segments and is **exact**, unlike the list's
    ``meta.total``, which saturates at
    :data:`~bayram.db.admin.page.TOTAL_COUNT_CAP`. The two therefore disagree above that cap
    and should: "10,000+" is honest about being a ceiling, and a strip drawn from a capped
    sample would not be.
    """

    counts: list[BroadcastStateTotalView]
    total: int
    #: Recipient rows the campaigns in this filter set have finished with — sent, failed,
    #: skipped, undeliverable and unknown — from the campaign rows' own rollup. The numerator.
    reached_recipients: int
    #: What those campaigns froze into their audiences at creation. The denominator, and the
    #: number a human authorised: a half-written expansion must not flatter the strip by
    #: shrinking what the reach is measured against.
    audience_total: int
    #: The most recent instant a run STARTED, UTC, or ``null`` — see the class docstring.
    last_send_at: datetime | None


class BroadcastDetailView(ApiModel):
    """One campaign with its bodies and the filter it was pointed at.

    **``segment`` is nullable and its readability is a field, because a stored document is
    history and history does not re-validate.** The document was legal when it was written; a
    later schema version may not speak it, and the campaign it belongs to has already gone
    out. Failing the read would hide the whole record behind a filter nobody can change
    anyway, so an unreadable document is reported as a state — the posture
    ``bayram.db.admin.views`` takes towards a purge — and ``segmentHash`` still identifies it.
    """

    broadcast: BroadcastView
    #: In the order the read layer returned them; the panel groups by language itself.
    bodies: list[BroadcastBodyView]
    #: The stored filter, re-validated against today's shape. ``null`` when it no longer
    #: parses — see the class docstring.
    segment: SegmentModel | None
    is_segment_readable: bool
    #: The funnel recounted from ``broadcast_recipients``, beside
    #: :attr:`BroadcastView.progress`'s copy of it from the campaign row. Both, deliberately:
    #: the rows are truth, the rollup is what the worker last wrote, and a send being watched
    #: live is exactly when they differ. Collapsing them would hide a stalled rollup behind a
    #: number that keeps looking right.
    counted_progress: BroadcastProgressView


class BroadcastRecipientView(ApiModel):
    """One account's outcome in one campaign. **No Telegram id, at any role.**

    The module docstring argues the asymmetry with ``/users`` in full: nothing here routes on
    the id, and this is the one list in the API that pages through a membership decision the
    operator made about people. So the mask is the only form, there is no unmasked variant to
    ask for, and the row is addressed by its own ``id``.

    ``telegramUserIdMasked`` is ``null`` for exactly one reason and it is not masking:
    ``/forget`` nulls the column, so the row survives as evidence that a message was sent
    while the account it went to no longer exists here. ``isErased`` names that state rather
    than leaving a ``null`` to be read as a bug.
    """

    id: UUID
    #: ``•••••789``, or ``null`` after an erasure.
    telegram_user_id_masked: str | None
    is_erased: bool
    language: Language
    state: BroadcastRecipientState
    #: How many times the sender has tried. ``0`` on a row nothing has claimed.
    attempts: int
    #: A closed classification of Telegram's refusal, never its text.
    error_code: str | None
    #: When this row reached a TERMINAL state — any of them, not just a send. A delivery is
    #: ``state == "sent"`` together with this instant; a skip stamps the same column, which is
    #: what stops "never settled" and "settled, but not by a send" from sharing one ``null``.
    settled_at: datetime | None
    created_at: datetime


class BroadcastRecipientsPage(ApiModel):
    items: list[BroadcastRecipientView]
    meta: PageMeta


def to_body_view(record: BroadcastBodyRecord) -> BroadcastBodyView:
    """Project one body, rendering it exactly as the sender will.

    The rendering is recomputed rather than stored, so the preview an operator approves cannot
    drift from the message that goes out: there is one renderer and it runs on the same column
    both times.

    The argument is the READ LAYER's view and not the ORM row, like every other projection in
    this package: ``media_file_id`` has already been reduced to a boolean by
    :func:`~bayram.db.admin.broadcasts.broadcast_body_view`, one layer below, so the live handle
    into our bot's file storage never travels as far as this module.
    """
    rendered = render_body_html(record.text)
    return BroadcastBodyView(
        language=record.language,
        text=record.text,
        rendered_text=rendered,
        rendered_length=len(rendered),
        has_media=record.media_storage_key is not None,
        media_storage_key=record.media_storage_key,
        is_media_cached=record.has_media_file_id,
        button_label=record.button_label,
        button_url=record.button_url,
    )


def to_broadcast_view(item: BroadcastListItem) -> BroadcastView:
    """Project one campaign. Every counter comes from the campaign row's own rollup.

    Not from the recipient ledger — that recount is :attr:`BroadcastDetailView.counted_progress`
    and it costs a ``GROUP BY`` this list must not pay per row. The two are allowed to
    disagree and the detail screen shows both; see :class:`BroadcastDetailView`.
    """
    return BroadcastView(
        id=item.id,
        title=item.title,
        kind=item.kind,
        state=item.state,
        is_terminal=item.state in TERMINAL_STATES,
        segment_hash=item.segment_hash,
        audience_evaluated_at=item.audience_evaluated_at,
        scheduled_for=item.scheduled_for,
        started_at=item.started_at,
        finished_at=item.finished_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        created_by_admin_id=item.created_by_admin_id,
        created_by_username=item.created_by_username,
        scheduled_by_admin_id=item.scheduled_by_admin_id,
        scheduled_by_username=item.scheduled_by_username,
        reason_code=item.reason_code,
        reason_ref=item.reason_ref,
        error_code=item.error_code,
        progress=_progress(item),
    )


def to_broadcast_stats_view(stats: BroadcastStats) -> BroadcastStatsView:
    """Project the strip. Nothing is computed here that the read layer did not already count.

    In particular no rate is formed: the two integers cross as they were counted and the panel
    divides them, which is this repo's rule for every quotient it publishes. The ``total`` is
    the read layer's own property rather than a second sum over the same list — one place to
    be wrong about what "every campaign in this filter set" means.
    """
    return BroadcastStatsView(
        counts=[
            BroadcastStateTotalView(state=item.state, count=item.count) for item in stats.by_state
        ],
        total=stats.total,
        reached_recipients=stats.settled_recipients,
        audience_total=stats.audience_total,
        last_send_at=stats.last_send_at,
    )


def to_broadcast_detail_view(detail: BroadcastDetail) -> BroadcastDetailView:
    """The campaign, its bodies, its stored filter and the ledger's own count.

    One argument rather than a row and a keyword sequence:
    :class:`~bayram.db.admin.views.BroadcastDetail` is assembled by one function from one campaign
    id, so there is no call site that could hand this another campaign's bodies — a mistake the
    two-argument shape type-checked and rendered.
    """
    segment = _readable_segment(detail.segment)
    return BroadcastDetailView(
        broadcast=to_broadcast_view(detail.broadcast),
        bodies=[to_body_view(body) for body in detail.bodies],
        segment=segment,
        is_segment_readable=segment is not None,
        counted_progress=_counted_progress(detail.broadcast, detail.progress),
    )


def to_recipient_view(item: BroadcastRecipientItem) -> BroadcastRecipientView:
    """Project one recipient. This function is the only reader of ``telegram_user_id``.

    Every path to this wire goes through here, which is what makes "no raw Telegram id on the
    recipient wire" a property of one function rather than a habit spread over the handlers.
    """
    telegram_user_id = item.telegram_user_id
    return BroadcastRecipientView(
        id=item.id,
        telegram_user_id_masked=(
            None if telegram_user_id is None else mask_telegram_user_id(telegram_user_id)
        ),
        is_erased=item.is_erased,
        language=item.language,
        state=item.state,
        attempts=item.attempts,
        error_code=item.error_code,
        settled_at=item.settled_at,
        created_at=item.created_at,
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _progress(item: BroadcastListItem) -> BroadcastProgressView:
    """The funnel as the campaign row's own counters report it — the worker's rollup."""
    settled = (
        item.sent_count
        + item.failed_count
        + item.skipped_count
        + item.undeliverable_count
        + item.unknown_count
    )
    return BroadcastProgressView(
        audience_size=item.audience_size,
        recipient_count=item.recipient_count,
        is_audience_complete=item.recipient_count >= item.audience_size,
        sent_count=item.sent_count,
        failed_count=item.failed_count,
        skipped_count=item.skipped_count,
        undeliverable_count=item.undeliverable_count,
        unknown_count=item.unknown_count,
        settled_count=settled,
        unsettled_count=max(0, item.recipient_count - settled),
    )


def _counted_progress(item: BroadcastListItem, counted: BroadcastProgress) -> BroadcastProgressView:
    """The same funnel, counted from ``broadcast_recipients`` instead of read off the campaign.

    ``recipientCount`` here is the number of rows that actually exist, not the rollup's copy of
    it, which is the whole point of publishing this beside :attr:`BroadcastView.progress`: a
    rollup that has not caught up is a state an operator watches a send during, and the two
    numbers disagreeing is how they see it rather than something to hide by picking one.

    ``audienceSize`` is the campaign's, because it is a decision recorded at creation and not
    a count of anything that could be recomputed.
    """
    return BroadcastProgressView(
        audience_size=item.audience_size,
        recipient_count=counted.total,
        is_audience_complete=counted.total >= item.audience_size,
        sent_count=counted.sent,
        failed_count=counted.failed,
        skipped_count=counted.skipped_blocked,
        undeliverable_count=counted.undeliverable,
        unknown_count=counted.unknown,
        settled_count=counted.settled,
        unsettled_count=counted.pending + counted.sending,
    )


def _readable_segment(document: dict[str, Any]) -> SegmentModel | None:
    """The stored filter as a model, or ``None`` when this build no longer speaks it.

    Only ``ValidationError`` is caught, and only around the one call that can raise it: a
    document from an older schema version is a state, and any other failure here is a defect
    that must keep travelling.
    """
    try:
        return SegmentModel.model_validate(document)
    except ValidationError:
        return None
