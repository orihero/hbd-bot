"""The triage card: one ticket, rendered for the staff group, in plain English.

**Nothing in this module is translated, and that is the decision it exists to keep.** The
four customer catalogues are held in exact key and placeholder parity by
``tests/test_i18n/test_catalog_files.py`` and by
``tests/test_bot/test_locale_contract.py::test_every_key_the_code_renders_is_defined_in_every_catalogue``,
and ``translate`` falls back across all four locales — so a single staff-facing string put
there would oblige four translations of an internal triage message, forever, and would make
the copy on an operator's card a translation job. The support group is one room with one
working language. Its strings are literals here.

**It is imported by the bot AND by the worker**, which is why it holds no ``Settings``, no
store and no ``Bot``: it takes a :class:`~bayram.support.TicketSnapshot` and returns text and
markup. ``bayram.bot.delivery`` is the precedent for a module under ``bot/`` that runs inside
the ARQ worker; this one is narrower still, because it performs no I/O at all. Keeping it
pure is what lets the panel's ``support:card_sync`` job re-render a card from an id without
importing a single handler.

**Every message this bot sends is ``parse_mode=HTML``** (``bot/app.py::build_bot``), so the
card is HTML and obeys the same two rules the catalogues do: only tags Telegram documents —
this file uses ``b``, ``i``, ``code`` and ``blockquote``, all four of them in
``test_locale_contract.SUPPORTED_TAGS`` — and every value that came from a person goes
through :func:`~bayram.bot.i18n.escape_html` first. An unescaped ``<`` in a complaint is a
400 at send time, and a 400 at send time means the ticket never reaches the group at all,
which is the one failure this whole feature exists to prevent. The customer's body and the
staffer's display name are the two values that can contain one; both are escaped below,
individually, at the point of interpolation rather than by a caller who might forget.

**The card is re-rendered on every change rather than appended to.** A claim, a status move
and a panel-side note all edit the same message, so the card is always the current truth and
a staffer scrolling the group sees one row per ticket instead of a thread of state changes.
That is why :func:`render_card` is a total function of the snapshot and takes no "what
happened" argument: given the same row it produces the same text, so an edit that would
change nothing is detectable (and Telegram refuses it — see
``handlers.common._is_unchanged``) instead of silently doubling the group's message rate.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Final
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bayram.bot.callbacks import SupportAction, SupportCB, pack_reference
from bayram.bot.i18n import escape_html
from bayram.contracts import Language, SupportTicketSource, SupportTicketStatus
from bayram.support import TicketSnapshot, legal_moves_from

__all__ = [
    "render_card",
    "card_keyboard",
    "panel_url_for",
    "STATUS_BADGES",
    "SOURCE_LABELS",
    "LANGUAGE_BADGES",
    "MAX_CARD_BODY_CHARS",
    "CARD_RULE",
]

#: How much of a complaint the card shows before it is cut.
#:
#: The body column is 4096 — Telegram's own single-message ceiling, so a complaint that was
#: physically sendable can always be stored whole — and the card carries a header, a rule, a
#: footer and sometimes an assignment line above it. Rendering the body at full length would
#: therefore make the CARD longer than a message may be, and the failure mode is the worst one
#: available: a 400 at send time, the card never posted, and the latch left unclaimed on a
#: ticket whose customer has already been told it is in.
#:
#: 3000 leaves about a thousand characters of headroom for the rest of the card, which is four
#: times what it uses today. The full body is one tap away in the panel and the card says so,
#: so the truncation costs a reader a click and can never cost anybody the message.
MAX_CARD_BODY_CHARS: Final[int] = 3_000

#: What a truncated body ends with. A plain ellipsis rather than "… (truncated)" because the
#: line under it already tells the reader where the whole thing is.
_ELLIPSIS: Final[str] = "…"

#: The horizontal rule under the title. Box-drawing characters rather than ``<hr>``, which
#: Telegram does not support, and rather than hyphens, which its client renders at a different
#: weight from the text and makes the card look like a table that failed to draw.
CARD_RULE: Final[str] = "━━━━━━━━━━━━━━━━━━━━━"

#: One badge per column of the board, in the board's own order.
#:
#: The emoji is the fast half: a staffer scrolling a group of thirty cards reads the
#: pictograph and the colour before the word, which is the same argument
#: ``test_locale_contract.test_every_button_label_leads_with_an_emoji`` makes about buttons.
#: The words are Title Case and match the panel's column headings exactly, so "move it to
#: Waiting" means one thing in the group and in the panel.
#:
#: A ``Mapping`` with an explicit lookup helper rather than ``dict[...]`` indexing, because a
#: :class:`~bayram.contracts.SupportTicketStatus` member added later must not make the card
#: raise ``KeyError`` inside a send: ``enum_type`` renders a plain ``VARCHAR(32)`` with no
#: check constraint precisely so a new state needs no migration, and a renderer that crashed
#: on one would turn a cheap schema change into a support outage.
STATUS_BADGES: Final[Mapping[SupportTicketStatus, str]] = {
    SupportTicketStatus.NEW: "🆕 New",
    SupportTicketStatus.IN_PROGRESS: "🔧 In progress",
    SupportTicketStatus.WAITING: "⏳ Waiting on customer",
    SupportTicketStatus.RESOLVED: "✅ Resolved",
}

#: Which door the customer came through. Worth a line on the card rather than only a column in
#: the panel: a ticket opened from a delivered song's ⚠️ button has an order behind it and one
#: opened by ``/support`` may be about anything at all, and that changes the first question a
#: staffer asks.
SOURCE_LABELS: Final[Mapping[SupportTicketSource, str]] = {
    SupportTicketSource.DELIVERY_BUTTON: "⚠️ from a delivered song",
    SupportTicketSource.SUPPORT_COMMAND: "💬 /support",
}

#: The locale the ticket was opened in, as a staffer reads it.
#:
#: **This is the single most operationally important line on the card after the body**, which
#: is why it is on the customer row rather than buried: the relay answers in the language the
#: ticket was OPENED in, so a staffer typing a reply in Russian to a ``uz_latn`` ticket is
#: writing into a chat where it will not be understood. Both Uzbek scripts carry the same 🇺🇿
#: and are told apart by the script name beside it, exactly as the customer's own language
#: picker does it.
LANGUAGE_BADGES: Final[Mapping[Language, str]] = {
    Language.UZ_LATN: "🇺🇿 uz (latin)",
    Language.UZ_CYRL: "🇺🇿 uz (cyrillic)",
    Language.RU: "🇷🇺 ru",
    Language.EN: "🇬🇧 en",
}

#: The sentence that makes the group a two-way channel. It is the whole protocol: a staffer
#: does not learn a command, they reply to the message, and ``handlers.support`` resolves the
#: reply to the ticket through ``group_message_id``.
_REPLY_HINT: Final[str] = "Reply to this message to answer the customer."

#: What the two staff buttons say. Literals, not catalogue keys — see the module docstring.
#: Each leads with a distinct emoji for the reason every button in this product does, and the
#: three here (✋, ✅, 🔗) are distinct from one another because they sit on one card.
_CLAIM_LABEL: Final[str] = "✋ Claim"
_RESOLVE_LABEL: Final[str] = "✅ Resolve"
_PANEL_LABEL: Final[str] = "🔗 Open in panel"

#: Where the panel keeps one ticket, appended to ``Settings.support_panel_base_url``.
#:
#: Restated here rather than imported from ``bayram.admin`` or from the SPA's ``paths.ts``,
#: because this module is loaded by the bot and by the worker and neither may import the admin
#: package — ``bayram.admin`` is a separate process with a separate env file, and the test that
#: proves the seam can reach nothing that sends a message reads import statements. Two copies
#: of a URL path is the cost; a bot process that imports the admin app is not payable.
_PANEL_TICKET_PATH: Final[str] = "support"


def status_badge(status: SupportTicketStatus) -> str:
    """The badge for a status, falling back to the raw value for a member with no badge yet.

    Never raises. See :data:`STATUS_BADGES` for why that matters: the status column is an
    unconstrained ``VARCHAR`` on purpose, so the day a fifth column is added the card renders
    ``new_state`` rather than taking the group post down with a ``KeyError``.
    """
    return STATUS_BADGES.get(status, f"• {status.value}")


def _language_badge(language: Language) -> str:
    return LANGUAGE_BADGES.get(language, f"🏳️ {language.value}")


def _source_label(source: SupportTicketSource) -> str:
    return SOURCE_LABELS.get(source, source.value)


def _clock(moment: datetime) -> str:
    """One instant, in UTC, the way an operator quotes it back.

    UTC and labelled UTC, never the server's local zone and never the customer's: the group
    is read by people in more than one place, every other clock this system prints is UTC, and
    a timestamp whose zone is implicit is a timestamp two readers will disagree about while
    both believe they agree.
    """
    return moment.strftime("%d %b %Y, %H:%M UTC")


def _quoted(body: str) -> str:
    """The customer's own words, escaped and bounded, inside a ``blockquote``.

    ``blockquote`` rather than ``<i>`` because Telegram collapses a long one behind a "show
    more" in its own client, which is what keeps a three-paragraph complaint from pushing
    every other card off a staffer's screen — and it is in
    ``test_locale_contract.SUPPORTED_TAGS``, so it is a tag Telegram documents rather than one
    that produces a 400 the first time somebody writes at length.

    Escaped BEFORE truncation, deliberately. Cutting escaped text can split ``&amp;`` into
    ``&am`` — which Telegram rejects as a malformed entity — so the cut is taken on the raw
    string and the escape is applied to the result. The cost is that the printed length is the
    length of the customer's characters rather than of the markup, which is the number a human
    would have meant anyway.
    """
    cut = body if len(body) <= MAX_CARD_BODY_CHARS else body[:MAX_CARD_BODY_CHARS] + _ELLIPSIS
    return f"<blockquote>{escape_html(cut)}</blockquote>"


def render_card(ticket: TicketSnapshot, *, order_ref: str | None = None) -> str:
    """The whole card, as HTML, from one snapshot. Pure, total, and safe to send.

    ``order_ref`` is the SHORT reference the closing message printed —
    ``bayram.bot.delivery.order_reference(order_id)`` — and it is a parameter rather than
    something computed here on purpose. This module would otherwise have to import
    ``bayram.bot.delivery``, which pulls the pipeline's event and outcome types and the
    watermark into every process that renders a card, to re-derive a string its one caller
    already holds. Passing it in keeps exactly one definition of what an order reference is,
    in the module that prints it to the customer.

    ``None`` omits the order line entirely rather than printing "none": a ``/support`` ticket
    has no order, and a row of blanks on a triage card is a question ("did the lookup fail?")
    where an absent row is an answer.

    **Nothing here is conditional on the ticket being described.** A card is only ever posted
    after the body arrives — an undescribed ticket is a tap nobody followed up and is excluded
    from the board as well — so :attr:`~bayram.support.TicketSnapshot.body` being ``None``
    should be unreachable. It is rendered as a plain line rather than asserted against,
    because the one place this would be reached from is a panel-side re-render of a row
    somebody has since edited, and a card that says "no description yet" is a better answer
    than an exception inside an ARQ job that then retries for an hour.
    """
    lines = [
        f"🎫 <b>Ticket {escape_html(ticket.public_ref)}</b> · {status_badge(ticket.status)}",
        CARD_RULE,
        f"👤 Customer  <code>#{ticket.telegram_user_id}</code> · "
        f"{_language_badge(ticket.language)}",
    ]
    if order_ref is not None:
        lines.append(f"🎵 Order     <code>{escape_html(order_ref)}</code>")
    lines.append(f"🕒 Opened    {_clock(ticket.created_at)} · {_source_label(ticket.source)}")
    if ticket.assigned_admin_username is not None:
        lines.append(f"🙋 Claimed   {escape_html(ticket.assigned_admin_username)}")
    body = _quoted(ticket.body) if ticket.body else "<i>No description yet.</i>"
    lines.append("")
    lines.append(f"💬 {body}")
    lines.append("")
    lines.append(f"↩️ <i>{_REPLY_HINT}</i>")
    return "\n".join(lines)


def panel_url_for(base_url: str, ticket_id: UUID) -> str | None:
    """The panel's page for this ticket, or ``None`` when the panel is not configured.

    ``None`` — and therefore no button at all — is the whole point, and it is
    ``Settings.support_panel_base_url``'s own rule restated at the one place that consumes it:
    **Telegram validates a URL button at send time**, so a relative path, a bare hostname or a
    ``localhost`` link is not a dead button, it is a 400 that loses the ENTIRE card. A card
    lost to a half-configured convenience link is a complaint nobody in the group ever sees.

    The join is defensive because the setting carries no validator that normalises it: an
    operator may paste ``https://panel.example`` or ``https://panel.example/`` and both must
    produce one slash. Anything that is not plausibly absolute is refused rather than
    repaired — a value this function cannot recognise is a value it must not guess at, since
    the guess is what Telegram would reject.
    """
    trimmed = base_url.strip().rstrip("/")
    if not trimmed.startswith(("https://", "http://")):
        return None
    return f"{trimmed}/{_PANEL_TICKET_PATH}/{ticket_id}"


def card_keyboard(ticket: TicketSnapshot, *, panel_base_url: str = "") -> InlineKeyboardMarkup:
    """The card's buttons: the moves that are legal right now, then the panel link.

    **Only the moves :func:`~bayram.support.legal_moves_from` offers are drawn.** A resolved
    ticket shows no ``✅ Resolve``, because pressing it would be an illegal move — an ``Err``
    from ``move_status``, which the handler can only answer with a refusal — and a button
    guaranteed to refuse is a button that teaches a staffer the card is broken. It is the same
    rule the panel follows for the same reason, and it is read from the same table, so the
    group and the board cannot disagree about what is pressable.

    ``✋ Claim`` is drawn on the strength of ``IN_PROGRESS`` being reachable rather than on the
    assignment being empty: claiming is two writes — the assign and the move — and the move is
    the one that can be refused. A ticket already claimed by somebody else still offers it,
    because taking over a ticket is a real and common act in a support group, and the timeline
    records both claims.

    The panel button is LAST and on its own row: it leaves Telegram, and a link that leaves
    the app sitting beside two buttons that do not is the mis-tap this layout avoids. It is
    omitted entirely when the base URL is unset or unusable — see :func:`panel_url_for`.
    """
    builder = InlineKeyboardBuilder()
    moves = legal_moves_from(ticket.status)
    actions: list[InlineKeyboardButton] = []
    if SupportTicketStatus.IN_PROGRESS in moves:
        actions.append(_staff_button(_CLAIM_LABEL, SupportAction.CLAIM, ticket.id))
    if SupportTicketStatus.RESOLVED in moves:
        actions.append(_staff_button(_RESOLVE_LABEL, SupportAction.RESOLVE, ticket.id))
    if actions:
        builder.row(*actions)
    url = panel_url_for(panel_base_url, ticket.id)
    if url is not None:
        builder.row(InlineKeyboardButton(text=_PANEL_LABEL, url=url))
    return builder.as_markup()


def _staff_button(label: str, action: SupportAction, ticket_id: UUID) -> InlineKeyboardButton:
    """One staff button, carrying the TICKET id — see :class:`~bayram.bot.callbacks.SupportCB`.

    The group chat holds no FSM of ours and the card may be pressed weeks after it was posted,
    so the id has to be in the payload: there is nowhere else it could come from. ``ref``
    carries the ticket here and the order on the customer's ⚠️ button, which is the overload
    ``SupportCB`` documents and the reason both are 45 bytes rather than 78.
    """
    return InlineKeyboardButton(
        text=label,
        callback_data=SupportCB(action=action, ref=pack_reference(ticket_id)).pack(),
    )
