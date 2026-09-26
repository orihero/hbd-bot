"""``present`` on a callback: when an edit that changes nothing must NOT become a send.

``handlers.common._edit_or_send`` has exactly one ``except TelegramBadRequest``, and for most
of this product's life it answered two completely different refusals with the same action.
Telegram says 400 both when a message is too old (or no longer ours) to edit and when the
edit would change nothing at all, and aiogram flattens every 400 that is not a
``retry_after``/``migrate_to_chat_id`` case onto a bare ``TelegramBadRequest`` carrying only
a description string — so the two arrive indistinguishable unless something reads the prose.

Nothing did, and the cost was not theoretical. On the redirect checkout's pending branch the
redraw is a provably identical edit — that branch grants nothing, so the meter has not moved
and the paywall renders byte for byte as it already reads — so EVERY press of 💳 took the
"too old to edit" path, cloned the paywall into a NEW message, and then edited the original
into the payment link. The customer was handed a link with a live price button sitting
underneath it: one press, two screens, and the lower one still offering to charge them.

**The first two tests are a PAIR and neither is meaningful alone.** One asserts the clone is
gone; the other asserts the genuine fallback — a message Telegram will not let us edit — is
still a send. A change that satisfied only the first would silently stop redrawing every
screen the customer has scrolled past, which is the failure the fallback exists to prevent.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery

from bayram.bot.handlers.common import present
from bayram.bot.screens import Screen
from tests.test_bot.conftest import RecordingSession, make_callback

#: Telegram's real answer, quoted in full rather than trimmed to the substring the predicate
#: matches. A test that fed it only ``"message is not modified"`` would keep passing if the
#: predicate were tightened to an equality check against that exact phrase, which the real
#: API would then never satisfy.
NOT_MODIFIED = (
    "Bad Request: message is not modified: specified new message content and reply markup "
    "are exactly the same as a current content and reply markup of the message"
)

#: The other 400 the same ``except`` catches, and the reason the fallback may not simply be
#: deleted.
CANNOT_EDIT = "Bad Request: message can't be edited"


def refusal(description: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=EditMessageText(chat_id=1, text="x"), message=description)


def pressed(bot: Bot, data: str = "nav:back") -> CallbackQuery:
    """A callback whose ``message`` is mounted too.

    ``as_`` binds the bot to the object it is called on and not to anything nested inside it,
    and ``_edit_or_send`` calls ``callback.message.edit_text`` — so a callback mounted the
    obvious way raises "this method is not mounted to any bot instance" from inside the very
    ``try`` these tests are about, which would make every one of them pass for the wrong
    reason. Both halves are mounted here, once, rather than in four places.
    """
    callback = make_callback(data)
    assert callback.message is not None
    return callback.model_copy(update={"message": callback.message.as_(bot)}).as_(bot)


def sends(session: RecordingSession) -> list[SendMessage]:
    return [call for call in session.calls if isinstance(call, SendMessage)]


def edits(session: RecordingSession) -> list[EditMessageText]:
    return [call for call in session.calls if isinstance(call, EditMessageText)]


async def test_an_edit_that_would_change_nothing_sends_no_second_message(
    bot: Bot, session: RecordingSession
) -> None:
    """The clone that put a live price button under a payment link.

    One edit is attempted and refused; nothing else is sent. Asserting ``sends == []`` rather
    than a count of total calls is deliberate — it is the SEND that reached the customer's
    chat, and the swallowed edit costs nothing but a round trip.
    """
    # Arrange
    session.failures["EditMessageText"] = refusal(NOT_MODIFIED)
    callback = pressed(bot, "nav:pay")

    # Act
    await present(callback, Screen("the screen it already reads as", None))

    # Assert
    assert len(edits(session)) == 1
    assert sends(session) == []


async def test_a_message_too_old_to_edit_is_still_re_sent(
    bot: Bot, session: RecordingSession
) -> None:
    """The half of the old behaviour that must NOT regress.

    A customer who has scrolled past the screen we are redrawing gets a new one. Without
    this, splitting the ``except`` would turn every stale-message redraw into silence.
    """
    # Arrange
    session.failures["EditMessageText"] = refusal(CANNOT_EDIT)
    callback = pressed(bot)

    # Act
    await present(callback, Screen("a screen the old message cannot hold", None))

    # Assert
    assert len(edits(session)) == 1
    assert [call.text for call in sends(session)] == ["a screen the old message cannot hold"]


async def test_an_unrecognised_refusal_still_falls_back_to_sending(
    bot: Bot, session: RecordingSession
) -> None:
    """The documented failure DIRECTION of matching on prose, pinned as behaviour.

    ``_is_unchanged`` matches English written by a third party. If Telegram ever rewords the
    not-modified description, this is what happens: the predicate answers ``False`` and we
    degrade to the behaviour that shipped before the split — one duplicate message — never to
    a crash and never to a screen that failed to draw. That is the trade the docstring on
    ``_UNCHANGED_MESSAGE`` claims, and this test is the only place it is checked.
    """
    # Arrange
    session.failures["EditMessageText"] = refusal("Bad Request: some wording nobody predicted")
    callback = pressed(bot)

    # Act
    await present(callback, Screen("a screen", None))

    # Assert
    assert [call.text for call in sends(session)] == ["a screen"]


async def test_an_idempotent_redraw_draws_nothing_at_all(
    bot: Bot, session: RecordingSession
) -> None:
    """Drawing the same screen twice leaves one screen in the chat, not two.

    The product-wide half of the change: every Back-to-the-same-step, every refusal that
    redraws the screen it refused on, and both surfaces of the checkout share this path.
    """
    # Arrange
    callback = pressed(bot)
    screen = Screen("an unchanged screen", None)
    await present(callback, screen)
    session.failures["EditMessageText"] = refusal(NOT_MODIFIED)

    # Act
    await present(callback, screen)

    # Assert
    assert sends(session) == []
