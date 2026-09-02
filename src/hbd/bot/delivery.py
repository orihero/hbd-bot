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
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from hbd.bot.i18n import escape_html, translate
from hbd.bot.keyboards import post_delivery_keyboard
from hbd.contracts import GeneratedAsset, Kit, Language, Result, err, ok
from hbd.errors import DeliveryError
from hbd.logging import get_logger
from hbd.pipeline.events import PipelineStage
from hbd.pipeline.outcome import PipelineGap

__all__ = [
    "deliver_kit",
    "DeliveryLedger",
    "gap_message_key",
    "order_reference",
    "ORDER_REFERENCE_CHARS",
    "VOICE_NOTE_MIMES",
    "MAX_MESSAGE_CHARS",
]

_LOG = get_logger(__name__)

#: ``sendVoice`` accepts exactly these. Anything else becomes a file attachment.
VOICE_NOTE_MIMES: Final[frozenset[str]] = frozenset(
    {"audio/ogg", "audio/opus", "audio/ogg; codecs=opus"}
)

#: Telegram's per-message limit. The lyric sheet is split on blank lines below it.
MAX_MESSAGE_CHARS: Final[int] = 4_096

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


@dataclass(frozen=True, slots=True)
class _Outbox:
    """One order's view of a ledger, so the send helpers take two words instead of four."""

    ledger: DeliveryLedger
    order_id: UUID

    def is_sent(self, key: str) -> bool:
        return self.ledger.is_sent(self.order_id, key)

    def mark(self, key: str) -> None:
        self.ledger.mark_sent(self.order_id, key)


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
    """
    outbox = _Outbox(
        ledger=ledger if ledger is not None else _DEFAULT_LEDGER, order_id=kit.order_id
    )
    already_sent = len(outbox.ledger.sent_for(kit.order_id))
    failures: list[str] = []

    failures.extend(await _send_song(bot, chat_id=chat_id, kit=kit, language=language, out=outbox))
    failures.extend(
        await _send_greetings(bot, chat_id=chat_id, kit=kit, language=language, out=outbox)
    )
    failures.extend(
        await _send_lyric_sheet(bot, chat_id=chat_id, kit=kit, language=language, out=outbox)
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
    bot: Bot, *, chat_id: int, kit: Kit, language: Language, out: _Outbox
) -> tuple[str, ...]:
    key = "song"
    if out.is_sent(key):
        return ()
    caption = translate(
        "delivery.song_caption", language, title=kit.lyrics.title, name=kit.lyrics.name_display
    )
    missing = _missing_file(kit.song)
    if missing is not None:
        return (missing,)
    try:
        await bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(kit.song.path),
            caption=caption,
            title=kit.lyrics.title,
            duration=int(kit.song.duration_s),
        )
    except TelegramAPIError as exc:
        return (_log_failure("song", kit, exc),)
    out.mark(key)
    return ()


async def _send_greetings(
    bot: Bot, *, chat_id: int, kit: Kit, language: Language, out: _Outbox
) -> tuple[str, ...]:
    failures: list[str] = []
    total = len(kit.greetings)
    for index, greeting in enumerate(kit.greetings, start=1):
        key = f"greeting:{index}:{greeting.persona_id or ''}"
        if out.is_sent(key):
            continue
        caption = translate("delivery.greeting_caption", language, index=index, total=total)
        failure = await _send_one_greeting(
            bot, chat_id=chat_id, kit=kit, greeting=greeting, caption=caption
        )
        if failure is not None:
            failures.append(failure)
            continue
        out.mark(key)
    return tuple(failures)


async def _send_one_greeting(
    bot: Bot, *, chat_id: int, kit: Kit, greeting: GeneratedAsset, caption: str
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
        return _log_failure(f"greeting:{greeting.persona_id}", kit, exc)
    return None


async def _send_lyric_sheet(
    bot: Bot, *, chat_id: int, kit: Kit, language: Language, out: _Outbox
) -> tuple[str, ...]:
    """The lyric sheet is text, not a file: it must be readable in the chat itself.

    A sheet that does not fit one Telegram message is numbered. Without the numbering each
    chunk arrived under an identical ``📄 <b>Title</b>`` heading, which reads as the bot
    having sent the same message twice rather than as one sheet in two parts — and a pasted
    lyric only has to pass about 2 050 escaped characters to split, well inside the 3 000
    ``lyrics_entry.MAX_LYRIC_CHARS`` allows. A single-part sheet keeps the plain heading:
    "1/1" on a message with nothing to compare it to is noise.
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
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except TelegramAPIError as exc:
            failures.append(_log_failure(f"lyric_sheet:part-{part}", kit, exc))
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
    """The last message: what they got, what they did not, and what to do next.

    A run with holes leads with ``delivery.done_degraded`` rather than burying the
    admission under a celebration — the product did not do what it promised, and the
    sentence that says so goes first.
    """
    key = "closing"
    if out.is_sent(key):
        return ()
    lead = "delivery.done_degraded" if gaps else "delivery.done"
    lines = [
        translate(
            lead,
            language,
            name=kit.lyrics.name_display,
            order_ref=order_reference(kit.order_id),
        ),
        *_gap_lines(gaps, language),
    ]
    try:
        await bot.send_message(
            chat_id=chat_id,
            text="\n\n".join(lines),
            reply_markup=post_delivery_keyboard(language),
        )
    except TelegramAPIError as exc:
        return (_log_failure("closing", kit, exc),)
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


def _log_failure(label: str, kit: Kit, exc: TelegramAPIError) -> str:
    _LOG.error(
        "Telegram rejected an asset",
        extra={"order_id": str(kit.order_id), "asset": label, "failure": repr(exc)},
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
