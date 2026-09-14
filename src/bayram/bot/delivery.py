"""Sending the finished kit. The last hundred metres, where a container mistake shows.

Three rules, each of which is a product bug if broken:

* the song goes out with ``sendAudio`` so it gets a player, a title and a duration;
* every greeting goes out with ``sendVoice``, which **requires OGG/Opus** — hand it an MP3
  and Telegram renders a grey file attachment instead of a voice note, so a greeting whose
  mime is wrong is refused the voice path and logged loudly rather than shipped ugly;
* the lyric sheet goes out as TEXT, typeset by us, carrying the DISPLAY spelling with its
  ``ʻ`` intact — it is the one artefact where the orthography is visible.

Delivery is best-effort per asset: a greeting that fails does not cost the customer the
song. Every failure is collected and returned as one ``Err`` after everything sendable has
been sent.

Two further rules the ARQ retry ladder forced into this module.

**A redelivery sends what is MISSING, not the kit again.** That ``Err`` becomes a job
retry, the orchestrator's replay hands the retry the *same* kit rather than making a new
one, and without a record of what already landed the customer receives their song, their
greetings and their lyric sheet a second time because one greeting was rate-limited the
first time round. :class:`DeliveryLedger` is that record. Read its docstring before
trusting it: it is process-local, and it says why.

**The closing message is the payoff, not a receipt.** It is the last thing the customer
reads, so it carries a keyboard rather than leaving them on a typed command, it quotes an
order reference support can act on, and it says plainly when the run left holes — *before*
it celebrates. The order the assets go out in is deliberate too: the song is sent FIRST so
the audio the whole product exists for is never buried under paragraphs of text, and
forwarding that one message is this product's only distribution — there is no link.

**And because forwarding is the only distribution, every message that leaves here is
watermarked.** That last sentence is the whole reason: a song that arrives in a third
person's chat with nothing on it advertises nobody. So the audio caption carries
``watermark.song``, the greeting captions and every part of the lyric sheet carry
``watermark.invite``, ``sendAudio`` goes out with ``performer`` set to the handle and the
generated cover as its thumbnail, and the two localised lines are computed ONCE per
delivery rather than per asset so a multi-part sheet cannot end up half-marked.

The watermark is composed onto the templates **in code**, never interpolated into them.
``delivery.song_caption``, ``delivery.greeting_caption`` and the two lyric-sheet keys keep
their placeholder sets exactly as they were, because ``tests/test_bot/test_i18n.py`` asserts
placeholder-set equality across four catalogues in both directions and moving seven keys at
once to gain a ``{handle}`` nobody translates buys nothing. It also keeps
:func:`_split_for_telegram` a pure function of the lyric body, which is load-bearing: the
part number it produces is the redelivery dedup key.

The handle itself is :data:`bayram.watermark.WATERMARK_HANDLE`, a module constant rather than a
setting, which is precisely what lets this module stay watermarked without ``deliver_kit``
growing a ``Settings`` parameter that ``bayram.runtime.jobs`` would then have to thread through.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile

from bayram.bot.i18n import escape_html, translate
from bayram.bot.keyboards import post_delivery_keyboard
from bayram.contracts import GeneratedAsset, Kit, Language, Result, err, ok
from bayram.errors import DeliveryError
from bayram.logging import get_logger
from bayram.pipeline.events import PipelineStage
from bayram.pipeline.outcome import PipelineGap
from bayram.watermark import WATERMARK_HANDLE

__all__ = [
    "deliver_kit",
    "DeliveryLedger",
    "is_blocked_by_customer",
    "BLOCKED_BY_CUSTOMER_KEY",
    "gap_message_key",
    "order_reference",
    "ORDER_REFERENCE_CHARS",
    "VOICE_NOTE_MIMES",
    "MAX_CAPTION_CHARS",
    "MAX_MESSAGE_CHARS",
]

_LOG = get_logger(__name__)

#: The key :func:`deliver_kit` reports a customer's block under, in ``DeliveryError.context``.
#: Named rather than spelled at both ends because the writer is here and the reader is in
#: ``bayram.runtime.jobs``, and a typo in either would be a churn source that silently records
#: nothing.
BLOCKED_BY_CUSTOMER_KEY: Final[str] = "is_blocked_by_customer"

#: What Telegram says in the ``Forbidden:`` description when the customer blocked the bot.
#: Compared case-folded, and as a SUBSTRING because the description is prefixed.
_BLOCKED_BY_USER_MESSAGE: Final[str] = "bot was blocked by the user"

#: ``sendVoice`` accepts exactly these. Anything else becomes a file attachment.
VOICE_NOTE_MIMES: Final[frozenset[str]] = frozenset(
    {"audio/ogg", "audio/opus", "audio/ogg; codecs=opus"}
)

#: Telegram's per-message limit. The lyric sheet is split on blank lines below it.
MAX_MESSAGE_CHARS: Final[int] = 4_096

#: Telegram's per-CAPTION limit, which is a quarter of the message limit above and is a
#: different number for a different endpoint — ``sendAudio`` and ``sendVoice`` take a caption,
#: not a message. Captions were never measured in this module at all before the watermark,
#: and they got away with it: the only variable a caption carried was ``LyricDraft.title``,
#: bounded at 120 characters by the contract, so the longest caption this module could
#: produce was a couple of hundred characters and the ceiling was unreachable. Appending a
#: localised watermark line is the first thing that added an unbudgeted term to that sum, so
#: the first thing that made measuring it worth doing. It is a guard, not a working path.
MAX_CAPTION_CHARS: Final[int] = 1_024

#: How much of the order id the customer is asked to quote. Eight hex characters is short
#: enough to read down a phone line and long enough that support can prefix-match one order
#: in a table this product will never fill past a few million rows.
ORDER_REFERENCE_CHARS: Final[int] = 8

#: How many orders the default ledger remembers. Delivery state is worth kilobytes and a
#: worker that has been up for a month must not carry every order it ever sent.
MAX_TRACKED_ORDERS: Final[int] = 1_024

#: The stages whose gaps the customer can actually HEAR the consequence of, and the
#: sentence that admits it. Keyed by stage, not by ``ErrorCode``: what the customer lost is
#: decided by which stage fell over, never by which vendor symptom took it down, and a
#: stage that is absent here is an operator concern with nothing to say to a customer —
#: PERSISTING, for instance, is an archival failure, and the file was still delivered.
_GAP_KEYS: Final[Mapping[PipelineStage, str]] = {
    PipelineStage.VERIFYING_NAME: "gap.name_best_effort",
    PipelineStage.RENDERING_GREETINGS: "gap.greeting_missing",
    # The only gap ``assembly`` records here is a greeting that failed to transcode, which
    # the customer experiences as exactly the same hole as one that failed to render.
    PipelineStage.POST_PROCESSING: "gap.greeting_missing",
}


def order_reference(order_id: UUID) -> str:
    """The short reference the closing message asks the customer to quote.

    The leading characters of the order id as it is printed everywhere else — in logs, in
    ``order_id`` context on every error, in the database — so support reproduces it by
    reading, never by computing. Kept in one function for exactly that reason.
    """
    return str(order_id)[:ORDER_REFERENCE_CHARS]


def gap_message_key(gap: PipelineGap) -> str | None:
    """The success-safe sentence for one gap, or ``None`` when it has none.

    Deliberately NOT ``gap.user_message_key``. Those keys were written for a failure
    screen and every one of them ends in some variant of "please try again in a moment" —
    an instruction that is nonsense stapled underneath a message announcing a delivered
    song, and that invites the customer to burn a second generation for nothing.

    Total by construction: a gap from a stage nobody mapped returns ``None`` and is logged
    rather than guessed at. The closing message still leads with ``delivery.done_degraded``
    whenever any gap exists, so an unmapped gap costs the customer a detail, never the
    disclosure itself.
    """
    key = _GAP_KEYS.get(gap.stage)
    if key is None:
        _LOG.info(
            "gap has no customer-facing sentence; disclosed as degraded without a detail",
            extra={
                "stage": gap.stage.value,
                "error_code": gap.error_code.value,
                "detail": gap.detail,
            },
        )
    return key


class DeliveryLedger:
    """Which of an order's assets have already reached the chat.

    ARQ retries the whole job when ``deliver_kit`` returns an ``Err``, and the
    orchestrator's replay short-circuit hands that retry the kit it already built. Without
    this, one rate-limited greeting costs the customer a second copy of everything.

    **Process-local, and deliberately so.** Nothing in the schema records per-asset
    delivery: ``orders.state`` carries a single ``DELIVERED`` flag for the whole kit, and
    the assets table has no sent column. Adding one is a migration, and a migration is not
    this module's to write. So a retry that lands in the same worker process is
    deduplicated exactly, and a retry that lands in a *different* process — a redeploy, a
    second worker — degrades to the old behaviour of sending a duplicate rather than to
    the new behaviour of sending nothing. Losing the song is far worse than sending it
    twice, so that is the direction this failure mode is pointed.

    Append-only per order, and bounded: the oldest order is evicted once
    ``max_orders`` is exceeded. It is an accumulator the delivery layer owns, in the same
    shape as ``RunLedger``, and it hands back frozensets.
    """

    def __init__(self, *, max_orders: int = MAX_TRACKED_ORDERS) -> None:
        self._sent: OrderedDict[UUID, set[str]] = OrderedDict()
        self._max_orders = max(1, max_orders)

    def is_sent(self, order_id: UUID, key: str) -> bool:
        return key in self._sent.get(order_id, frozenset())

    def mark_sent(self, order_id: UUID, key: str) -> None:
        keys = self._sent.get(order_id)
        if keys is None:
            keys = set()
            self._sent[order_id] = keys
        keys.add(key)
        self._sent.move_to_end(order_id)
        self._evict()

    def sent_for(self, order_id: UUID) -> frozenset[str]:
        return frozenset(self._sent.get(order_id, frozenset()))

    def forget(self, order_id: UUID) -> None:
        """Drop an order's state. Called by nobody today; eviction is automatic."""
        self._sent.pop(order_id, None)

    def _evict(self) -> None:
        while len(self._sent) > self._max_orders:
            order_id, _keys = self._sent.popitem(last=False)
            _LOG.info(
                "delivery ledger evicted an order; a later retry of it would resend",
                extra={"order_id": str(order_id), "max_orders": self._max_orders},
            )


#: The ledger used when a caller does not bring one. One per process, which is what the
#: ARQ worker wants: every job in that process shares it.
_DEFAULT_LEDGER: Final[DeliveryLedger] = DeliveryLedger()


def is_blocked_by_customer(exc: TelegramAPIError) -> bool:
    """Whether this failure means the CUSTOMER blocked the bot, as opposed to anything else.

    A structured fact, not a substring test on a log line. ``_log_failure`` builds
    ``f"{label}:{type(exc).__name__}"``, which is a human-readable artefact for an operator
    reading a log; a caller that parsed it for meaning would stop working silently the day
    somebody reformats it. This function is the one place the classification lives, it has
    its own test, and its answer travels in ``DeliveryError.context`` under
    :data:`BLOCKED_BY_CUSTOMER_KEY`.

    **``"user is deactivated"`` is the carve-out, and it is the whole point of the
    predicate.** That is Telegram's other ``Forbidden``: a DELETED account. It is
    undeliverable for a completely different reason, it is not churn anybody can ever win
    back, and Telegram sends no ``my_chat_member`` update for it — so counting it as a block
    would put a number on the Churn card that no second source would ever corroborate. The
    honest answer there is to record nothing, and this returns ``False``.

    The dependency on Telegram's wording is real and is accepted deliberately. If that string
    is reworded, this source stops recording and the ``my_chat_member`` source keeps working
    — so churn does not go to zero, it goes quietly incomplete for the blocks that happen
    during a deploy window. The failure direction is "record nothing" rather than "record a
    wrong fact", which is the only direction worth having. Do NOT widen this to every
    ``TelegramForbiddenError`` to make it robust; that trades a known gap for an unknown lie.
    """
    if not isinstance(exc, TelegramForbiddenError):
        return False
    return _BLOCKED_BY_USER_MESSAGE in (exc.message or "").casefold()


@dataclass(slots=True)
class _Outbox:
    """One order's view of a ledger, so the send helpers take two words instead of four.

    Mutable — deliberately, and it is the only mutable thing in this module. It already
    threads every send helper, so it is the one place a fact observed at the bottom of the
    call tree can be carried back up to :func:`deliver_kit` without giving four helpers a
    second return value. :attr:`is_blocked_by_customer` is the only such fact, it is
    write-once-true (nothing ever clears it), and this module still stores nothing anywhere
    else: it REPORTS the block, and ``bayram.runtime.jobs`` is what writes it down.
    """

    ledger: DeliveryLedger
    order_id: UUID
    #: Set when any send was refused because the customer blocked the bot. Sticky: one
    #: refused asset out of five is enough, and the four that were never attempted say
    #: nothing to the contrary.
    is_blocked_by_customer: bool = False

    def is_sent(self, key: str) -> bool:
        return self.ledger.is_sent(self.order_id, key)

    def mark(self, key: str) -> None:
        self.ledger.mark_sent(self.order_id, key)

    def note_failure(self, exc: TelegramAPIError) -> None:
        """Classify one send failure. Only ever raises the flag, never lowers it."""
        if is_blocked_by_customer(exc):
            self.is_blocked_by_customer = True


async def deliver_kit(
    bot: Bot,
    *,
    chat_id: int,
    kit: Kit,
    language: Language,
    gaps: Sequence[PipelineGap] = (),
    ledger: DeliveryLedger | None = None,
) -> Result[None]:
    """Send song, greetings, lyric sheet and the closing message. Never raises.

    Anything ``ledger`` says already landed is skipped, so a retried job fills the holes
    the first pass left instead of sending the kit twice.

    The two watermark lines are translated HERE, once, and handed down to the senders. Not
    because it is cheaper — ``translate`` is a dict lookup — but because a multi-part lyric
    sheet renders one of them four or five times, and a line each sender looked up for
    itself is a line each sender can be edited to look up differently. One customer must
    never receive a sheet whose first part invites them in English and whose third does not
    invite them at all.
    """
    outbox = _Outbox(
        ledger=ledger if ledger is not None else _DEFAULT_LEDGER, order_id=kit.order_id
    )
    already_sent = len(outbox.ledger.sent_for(kit.order_id))
    failures: list[str] = []
    song_mark = translate("watermark.song", language, handle=WATERMARK_HANDLE)
    invite = translate("watermark.invite", language, handle=WATERMARK_HANDLE)

    failures.extend(
        await _send_song(
            bot, chat_id=chat_id, kit=kit, language=language, mark=song_mark, out=outbox
        )
    )
    failures.extend(
        await _send_greetings(
            bot, chat_id=chat_id, kit=kit, language=language, mark=invite, out=outbox
        )
    )
    failures.extend(
        await _send_lyric_sheet(
            bot, chat_id=chat_id, kit=kit, language=language, mark=invite, out=outbox
        )
    )
    failures.extend(
        await _send_closing(bot, chat_id=chat_id, kit=kit, language=language, gaps=gaps, out=outbox)
    )

    if failures:
        return err(
            DeliveryError(
                "one or more kit assets could not be delivered",
                context={
                    "order_id": str(kit.order_id),
                    "chat_id": chat_id,
                    "failures": failures,
                    "already_delivered": already_sent,
                    # The one piece of this context a CALLER branches on rather than logs.
                    # ``bayram.runtime.jobs._send_kit`` reads it to record the churn, which is
                    # why it is a boolean under a named key and not a substring of
                    # ``failures`` — those tokens are a log artefact and would break the
                    # moment anybody reformatted them. This module still stores nothing: it
                    # reports the fact and the worker writes it down.
                    BLOCKED_BY_CUSTOMER_KEY: outbox.is_blocked_by_customer,
                },
            )
        )
    if already_sent:
        _LOG.info(
            "redelivery completed the parts that were still missing",
            extra={"order_id": str(kit.order_id), "already_delivered": already_sent},
        )
    return ok(None)


async def _send_song(
    bot: Bot, *, chat_id: int, kit: Kit, language: Language, mark: str, out: _Outbox
) -> tuple[str, ...]:
    """The one message the whole product turns on, sent branded and — if refused — plain.

    **The retry is the only defence here that actually runs in production.** ``performer``
    and ``thumbnail`` are the two fields whose validity Telegram decides at SEND time and
    nowhere else: a thumbnail that is not JPEG, is over 200 kB or is larger than 320 px on
    a side comes back as a 400 ``TelegramBadRequest`` with the picture named in the
    description, and the same call without it would have succeeded. Nothing in this process
    can predict that — the cover is generated by a best-effort Pillow pass in another
    package, ``FSInputFile`` reads the file lazily inside aiogram, and no in-process test
    double raises the shape the real API returns. So the branded send is attempted once, and
    on that 400 it is attempted again with both fields dropped. Losing a watermark is a
    marketing cost; losing the song is the product.

    **The retry is narrowed to ``TelegramBadRequest`` on purpose, and the shape of that
    guard is a fixed defect.** It first read ``if failure is not None and branding``, which
    is *always* true — :func:`_song_branding` never returns an empty mapping, ``performer``
    is unconditional — so every hard failure cost two identical ``sendAudio`` calls where
    the pre-watermark code made exactly one. A ``TelegramForbiddenError`` (the customer
    blocked the bot) and a ``TelegramRetryAfter`` are the two that hurt: neither is caused
    by the branding, so dropping it cannot help, and under a 429 the second call is the one
    most likely to deepen the wait. Only a 400 describes a request Telegram parsed and
    rejected on its contents, which is the only failure the stripped call can answer; every
    other error is reported immediately, as it was before the branding existed.

    Both attempts share the ledger key ``"song"``, and it is marked only after one of them
    lands, so a retried ARQ job sees one delivered song rather than a second copy.
    """
    key = "song"
    if out.is_sent(key):
        return ()
    # A nameless kit gets the sibling key rather than the word "None" under its song.
    name = kit.lyrics.name_display
    caption = (
        translate("delivery.song_caption", language, title=kit.lyrics.title, name=name)
        if name is not None
        else translate("delivery.song_caption_noname", language, title=kit.lyrics.title)
    )
    caption = _fit_caption(f"{caption}\n\n{mark}")
    missing = _missing_file(kit.song)
    if missing is not None:
        return (missing,)
    branding = _song_branding(kit)
    failure = await _send_song_once(bot, chat_id=chat_id, kit=kit, caption=caption, extra=branding)
    if isinstance(failure, TelegramBadRequest):
        _LOG.warning(
            "Telegram rejected the branded song with a 400; retrying without the branding",
            extra={
                "order_id": str(kit.order_id),
                "branding": sorted(branding),
                "failure": repr(failure),
            },
        )
        failure = await _send_song_once(bot, chat_id=chat_id, kit=kit, caption=caption, extra={})
    if failure is not None:
        return (_log_failure("song", kit, failure, out=out),)
    out.mark(key)
    return ()


def _song_branding(kit: Kit) -> dict[str, Any]:
    """The ``sendAudio`` fields that carry the watermark, omitted rather than passed as None.

    ``performer`` is unconditional: aiogram has accepted it since 3.x and it is what a phone's
    lock screen and every forwarded-audio preview show under the title, so it is the carrier
    that survives the song leaving Telegram entirely.

    ``thumbnail`` is conditional twice over. ``Kit.cover`` is optional because the cover is
    generated best-effort and a render failure degrades to no picture; and even when the
    asset exists the FILE may not, because ``FSInputFile`` opens it lazily inside aiogram's
    multipart writer — long after this function returned — so a cover whose workspace was
    swept between assembly and delivery would raise from the middle of the send rather than
    return an ``Err``. Checking ``exists()`` here turns that into a plain unbranded song.

    Built as a mapping of only the keys that apply rather than passing ``thumbnail=None``,
    so the retry above can drop the whole thing by passing an empty one and the two call
    sites stay identical in every other respect.

    What it is NOT is a signal that there is anything to retry: this mapping is never empty,
    because ``performer`` is unconditional. The retry guard once read ``and branding`` and
    was therefore always true, which is how a blocked bot came to cost two ``sendAudio``
    calls. Whether to retry is decided by the failure's shape, never by this return value.
    """
    branding: dict[str, Any] = {"performer": WATERMARK_HANDLE}
    cover = kit.cover
    if cover is not None and cover.path.exists():
        branding["thumbnail"] = FSInputFile(cover.path)
    return branding


async def _send_song_once(
    bot: Bot, *, chat_id: int, kit: Kit, caption: str, extra: Mapping[str, Any]
) -> TelegramAPIError | None:
    """One ``sendAudio`` attempt, returning the rejection instead of raising it.

    Split out so the branded attempt and the plain retry are literally the same call with a
    different ``extra``, and so the retry is not a second ``try`` nested inside an ``except``
    where the original exception is still in scope and easy to log by accident.
    """
    try:
        await bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(kit.song.path),
            caption=caption,
            title=kit.lyrics.title,
            duration=int(kit.song.duration_s),
            **extra,
        )
    except TelegramAPIError as exc:
        return exc
    return None


async def _send_greetings(
    bot: Bot, *, chat_id: int, kit: Kit, language: Language, mark: str, out: _Outbox
) -> tuple[str, ...]:
    """Every greeting, each marked in its caption because a voice note has nowhere else.

    ``sendVoice`` takes no ``title``, no ``performer`` and no ``thumbnail`` — the fields the
    song is branded with do not exist on this endpoint — so the caption is the only carrier
    a greeting has, and a greeting is exactly as forwardable as the song.
    """
    failures: list[str] = []
    total = len(kit.greetings)
    for index, greeting in enumerate(kit.greetings, start=1):
        key = f"greeting:{index}:{greeting.persona_id or ''}"
        if out.is_sent(key):
            continue
        caption = translate("delivery.greeting_caption", language, index=index, total=total)
        caption = _fit_caption(f"{caption}\n\n{mark}")
        failure = await _send_one_greeting(
            bot, chat_id=chat_id, kit=kit, greeting=greeting, caption=caption, out=out
        )
        if failure is not None:
            failures.append(failure)
            continue
        out.mark(key)
    return tuple(failures)


async def _send_one_greeting(
    bot: Bot, *, chat_id: int, kit: Kit, greeting: GeneratedAsset, caption: str, out: _Outbox
) -> str | None:
    missing = _missing_file(greeting)
    if missing is not None:
        return missing
    if greeting.mime not in VOICE_NOTE_MIMES:
        _LOG.error(
            "greeting is not OGG/Opus; sendVoice would render it as a file attachment",
            extra={
                "order_id": str(kit.order_id),
                "persona_id": greeting.persona_id,
                "mime": greeting.mime,
                "path": str(greeting.path),
                "accepted": sorted(VOICE_NOTE_MIMES),
            },
        )
        return f"greeting:{greeting.persona_id}:wrong-container:{greeting.mime}"
    try:
        await bot.send_voice(
            chat_id=chat_id,
            voice=FSInputFile(greeting.path),
            caption=caption,
            duration=int(greeting.duration_s),
        )
    except TelegramAPIError as exc:
        return _log_failure(f"greeting:{greeting.persona_id}", kit, exc, out=out)
    return None


async def _send_lyric_sheet(
    bot: Bot, *, chat_id: int, kit: Kit, language: Language, mark: str, out: _Outbox
) -> tuple[str, ...]:
    """The lyric sheet is text, not a file: it must be readable in the chat itself.

    A sheet that does not fit one Telegram message is numbered. Without the numbering each
    chunk arrived under an identical ``📄 <b>Title</b>`` heading, which reads as the bot
    having sent the same message twice rather than as one sheet in two parts — and a pasted
    lyric only has to pass about 2 050 escaped characters to split, well inside the 3 000
    ``lyrics_entry.MAX_LYRIC_CHARS`` allows. A single-part sheet keeps the plain heading:
    "1/1" on a message with nothing to compare it to is noise.

    The mark goes above the heading AND below the body of EVERY part, not once on the first.
    Parts are separate Telegram messages and a customer forwards messages, not sheets: the
    third verse of somebody's song travels on its own, and if the invitation only rode on
    part one then the part that actually got forwarded advertises nobody.

    Composed after the template rather than inside :func:`_split_for_telegram`, which is left
    alone on purpose. That function's budget is ``MAX_MESSAGE_CHARS // 2``, with the other
    half reserved for the escaped heading it cannot see; two forty-character lines spend a
    rounding error of that reserve. Far more importantly it must stay a pure function of the
    lyric body, because the part number it produces is the ``lyric_sheet:{part}`` redelivery
    key — change the budget and a retry after a deploy renumbers the parts, finds a key it
    has not seen and sends a chunk the customer already has.
    """
    body = kit.lyrics.as_plain_text()
    chunks = _split_for_telegram(body)
    total = len(chunks)
    failures: list[str] = []
    for part, chunk in enumerate(chunks, start=1):
        key = f"lyric_sheet:{part}"
        if out.is_sent(key):
            continue
        text = (
            translate("delivery.lyric_sheet", language, title=kit.lyrics.title, body=chunk)
            if total == 1
            else translate(
                "delivery.lyric_sheet_part",
                language,
                title=kit.lyrics.title,
                body=chunk,
                part=part,
                total=total,
            )
        )
        text = f"{mark}\n\n{text}\n\n{mark}"
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except TelegramAPIError as exc:
            failures.append(_log_failure(f"lyric_sheet:part-{part}", kit, exc, out=out))
            continue
        out.mark(key)
    return tuple(failures)


async def _send_closing(
    bot: Bot,
    *,
    chat_id: int,
    kit: Kit,
    language: Language,
    gaps: Sequence[PipelineGap],
    out: _Outbox,
) -> tuple[str, ...]:
    """The last message: what they got, and what to do next.

    **It no longer says what they did NOT get, and that reverses a decision this docstring
    used to argue for.** The old text read: *"A run with holes leads with
    ``delivery.done_degraded`` rather than burying the admission under a celebration — the
    product did not do what it promised, and the sentence that says so goes first."* The owner
    withdrew it on 2026-09-14: *"I should not be getting this kind of messages! It is enough we
    track them in the admin panel, user should not see the internal problems of our platform."*

    So every delivered run now closes on ``delivery.done``. ``delivery.done_degraded`` and the
    ``gap.*`` sentences stay in all four locale files — they are a decision away from being
    wanted again, and deleting the copy would make the reversal a translation job rather than
    a one-line one.

    **What this costs, stated rather than discovered.** A customer whose name came out
    approximated is no longer told, so they cannot know the difference between "this is how the
    model heard it" and "this song is wrong". The support path is also gone from the degraded
    case: the closing message still prints the order reference, but the *invitation* to send
    ``/support`` with it did not survive, because it lived only in the degraded lead. The gap
    itself is unaffected — it is recorded exactly as before (below) — so the loss is the
    customer's visibility, not ours.

    The keyboard is ``post_delivery_keyboard``, which now also carries 🏠 Back to menu — this
    is one of the places a flow ends, and until that row existed the only exits were a next
    order and a complaint. What it deliberately does NOT do is re-send the main-menu reply
    keyboard. That keyboard is ``is_persistent=True`` and therefore chat-level state that is
    still on screen; and this function runs in the WORKER, whose ``language`` is
    ``order.brief.ui_language`` (``runtime.jobs``) — the interface language captured when the
    order was CONFIRMED. A customer who changed it in ⚙️ Settings while the song was being
    made would have their menu silently re-pinned in the language they left, with no event
    anywhere to explain it. The one place that keyboard is re-sent is the language change
    itself, which is the only place its labels can go stale.
    """
    key = "closing"
    if out.is_sent(key):
        return ()
    name = kit.lyrics.name_display
    # One lead, whatever happened. `gaps` is still taken, still logged below, and still the
    # thing the admin panel's attempt ledger and name verdicts are built from — it simply no
    # longer reaches the customer. See the docstring for whose decision that was.
    lead = "delivery.done" if name is not None else "delivery.done_noname"
    reference = order_reference(kit.order_id)
    if gaps:
        _LOG.info(
            "a run delivered with gaps the customer was not told about",
            extra={
                "order_id": str(kit.order_id),
                "gaps": [gap.stage.value for gap in gaps],
                "error_codes": [gap.error_code.value for gap in gaps],
            },
        )
    lines = [
        translate(lead, language, order_ref=reference)
        if name is None
        else translate(lead, language, name=name, order_ref=reference),
    ]
    try:
        await bot.send_message(
            chat_id=chat_id,
            text="\n\n".join(lines),
            reply_markup=post_delivery_keyboard(language),
        )
    except TelegramAPIError as exc:
        return (_log_failure("closing", kit, exc, out=out),)
    out.mark(key)
    return ()


def _gap_lines(gaps: Sequence[PipelineGap], language: Language) -> tuple[str, ...]:
    """One sentence per DISTINCT gap kind, in the order the run hit them.

    Three greetings that failed for three different vendor reasons are one hole from where
    the customer sits, and ``dict.fromkeys`` is what keeps the closing message from saying
    so three times.
    """
    keys = dict.fromkeys(key for gap in gaps if (key := gap_message_key(gap)) is not None)
    return tuple(translate(key, language) for key in keys)


def _missing_file(asset: GeneratedAsset) -> str | None:
    path: Path = asset.path
    if path.exists():
        return None
    _LOG.error(
        "asset file is missing at delivery time",
        extra={"kind": asset.kind.value, "path": str(path), "persona_id": asset.persona_id},
    )
    return f"{asset.kind.value}:missing-file"


def _log_failure(label: str, kit: Kit, exc: TelegramAPIError, *, out: _Outbox) -> str:
    """Log one rejected asset and return its failure token.

    ``out`` is keyword-only and required so that no future send path can log a failure
    without classifying it: every refusal in this module passes through here, which is what
    makes ``out.is_blocked_by_customer`` complete rather than best-effort.
    """
    out.note_failure(exc)
    _LOG.error(
        "Telegram rejected an asset",
        extra={
            "order_id": str(kit.order_id),
            "asset": label,
            "failure": repr(exc),
            BLOCKED_BY_CUSTOMER_KEY: is_blocked_by_customer(exc),
        },
    )
    return f"{label}:{type(exc).__name__}"


def _escaped_len(text: str) -> int:
    """How many characters Telegram will actually count for ``text``.

    ``translate`` HTML-escapes every parameter, so the string on the wire is not the string
    we measured: ``&`` costs five characters there and one here, ``<`` and ``>`` cost four.
    A lyric the customer pasted can be almost all ampersands, and budgeting the raw text
    is how a sheet well inside the paste limit still arrives over Telegram's ceiling.
    """
    return len(escape_html(text))


def _clip_to_escaped(text: str, budget: int) -> str:
    """Longest prefix of ``text`` whose ESCAPED form fits ``budget``.

    Counted one source character at a time rather than by slicing the escaped string,
    because a slice can land inside ``&amp;`` and hand Telegram a broken entity — the same
    rejected message this exists to avoid, arrived at from the other side. ``budget`` is
    assumed to be at least the width of one escaped character, which the only caller's
    constant satisfies by three orders of magnitude. Text that already fits comes back
    unchanged, so there is no early return to keep in step with the loop.
    """
    kept: list[str] = []
    spent = 0
    for char in text:
        spent += _escaped_len(char)
        if spent > budget:
            break
        kept.append(char)
    return "".join(kept)


def _fit_caption(text: str) -> str:
    """A composed caption, clipped at a LINE boundary if it would overrun the ceiling.

    **Measured with plain ``len``, and deliberately NOT with :func:`_escaped_len`.** That
    helper measures RAW text that ``translate`` has yet to escape, which is the sheet
    splitter's problem and the exact opposite of this one: ``text`` here is already-rendered
    HTML, so escaping it a second time charges ``&amp;amp;`` for an ampersand the customer
    typed once. A 120-character title of ampersands — the contract's own ceiling — measures
    3 000 that way and 660 truthfully, so the un-reachable guard fires on a caption that fits
    five times over, and the character-level clip it then applies lands inside an ``&amp;``
    and hands Telegram the broken entity the whole escaping apparatus exists to avoid. This
    was found by the test below it, not by reasoning, which is why it is written down here.

    ``len`` is itself an over-count, in the safe direction: Telegram applies the ceiling to
    the caption AFTER parsing its entities away, so ``<b>`` costs three here and nothing
    there. An over-count clips early; an under-count is a 400 that costs the customer the
    song.

    Whole lines and never mid-line, because every caption template in the four catalogues
    keeps its markup inside one line — ``🎵 <b>{title}</b>``, then prose on the next — so a
    line boundary is the coarsest cut that cannot orphan a ``<b>`` from its ``</b>`` and get
    the message rejected for broken markup instead of for length.

    Nothing reaches this today: the only variable a caption carries is a title the contract
    bounds at 120 characters, and the paragraph above is what that bound is worth. It is here
    because the watermark line is the first term in the sum that this module does not itself
    bound, and because a caption Telegram rejects is indistinguishable, from the customer's
    side, from one that was never written.
    """
    if len(text) <= MAX_CAPTION_CHARS:
        return text
    kept: list[str] = []
    spent = 0
    for line in text.split("\n"):
        spent += len(line) + 1
        if spent > MAX_CAPTION_CHARS:
            break
        kept.append(line)
    if kept:
        return "\n".join(kept)
    # Not one whole line fits, so there is nothing to keep that is not a fragment. The LAST
    # line is the watermark this function was added for: composed by us, plain, short, and
    # the only part of a caption that is worth more than the part it advertises.
    return text.rsplit("\n", maxsplit=1)[-1][:MAX_CAPTION_CHARS]


def _split_for_telegram(body: str) -> tuple[str, ...]:
    """Split on blank lines so a verse is never cut in half. Never returns empty.

    The budget is half of Telegram's ceiling, and the other half pays for the sheet's
    heading — an escaped title inside ``<b>`` tags — which is added by the caller and
    therefore cannot be measured here. A block too big even on its own is cut across
    consecutive parts rather than truncated: a lyric sheet is the artefact that shows the
    customer the words they approved, so losing its tail is not an acceptable saving.

    The part numbering this produces is also the redelivery key for each chunk, so it must
    stay a pure function of the lyric: the same sheet split twice has to number the same.
    """
    budget = MAX_MESSAGE_CHARS // 2
    parts: list[str] = []
    current = ""
    for block in body.split("\n\n") if body else [""]:
        candidate = f"{current}\n\n{block}" if current else block
        if _escaped_len(candidate) <= budget:
            current = candidate
            continue
        if current:
            parts.append(current)
        remainder = block
        while _escaped_len(remainder) > budget:
            head = _clip_to_escaped(remainder, budget)
            parts.append(head)
            remainder = remainder[len(head) :]
        current = remainder
    parts.append(current)
    return tuple(parts)
