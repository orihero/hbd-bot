"""The one UUID5 that names a render, and the fingerprint it is taken over.

This lived inside ``handlers.confirm`` while the Confirm button was the only thing that
could start a render, and that was the right place for it: the id was minted a few lines
from where it was used, by the handler that owned the decision.

**It has a SECOND producer now, in a different process.** When a redirect payment settles,
``runtime.render_resume`` starts the render the customer already paid for, and to do that it
must arrive at the same id the bot would have minted — the id was recorded on the payment
intent at the moment the link was built (``DECISIONS.md D17``). Two spellings of that UUID5
would be two different order ids for one draft, which is the exact collision
``WizardDraft.session_id`` was added to prevent, only in reverse: instead of one id standing
for two runs, two ids would stand for one. The customer's own 🎬 press and the settlement's
resume would then both succeed, and they would each render, deliver and bill a song.

So the function moved here, to a leaf module — ``json``, ``uuid5`` and ``WizardDraft``, and
nothing else, so either process can import it without dragging a dispatcher or a container
along with it. ``handlers.confirm`` re-exports both names, because the argument for the
namespace constant and the argument for ``session_id`` are cross-referenced from there and
from ``tests/test_bot/test_submitting.py``.
"""

from __future__ import annotations

import json
from typing import Final
from uuid import UUID, uuid5

from bayram.bot.draft import WizardDraft

__all__ = ["ORDER_NAMESPACE", "order_fingerprint", "order_id_for"]

#: Namespace for :func:`order_id_for`. An arbitrary constant whose only requirement is
#: that it never changes: a new namespace would mint a second id for a draft that has
#: already been queued under the old one, which is precisely the collision this exists to
#: cause. Not a secret and not a key — a UUID5 namespace is public by construction.
#:
#: It is now also what makes the BOT and the WORKER agree. A namespace changed in one
#: process and not the other would put a settlement's resume and the customer's own press on
#: two different ids, and both would render.
ORDER_NAMESPACE: Final[UUID] = UUID("aa9941d0-85de-4c03-9e82-059b15b28fb7")


def order_fingerprint(telegram_user_id: int, draft: WizardDraft) -> str:
    """A canonical string standing for "this person's answers, exactly as they are now".

    Sorted keys and no whitespace, so two dumps of one draft are byte-identical; the whole
    draft rather than a chosen subset, so a field added to ``WizardDraft`` cannot silently
    stop distinguishing two orders that differ only by it.

    The "whole draft" property is what lets ``runtime.render_resume`` use a single equality
    check to decide whether the draft it found parked in the FSM is still the draft that was
    paid for: the fingerprint covers the approved lyric and every answer, so an edit of any
    kind moves the id.
    """
    return json.dumps(
        {"telegram_user_id": telegram_user_id, "draft": draft.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def order_id_for(telegram_user_id: int, draft: WizardDraft) -> UUID:
    """The id this draft always gets, so a second submission of it is a duplicate.

    ``uuid4()`` made every tap a new order, which is why two taps bought two songs: nothing
    downstream could tell them apart. A UUID5 over the fingerprint pushes the decision to
    the one place equipped to make it — the submitter derives the ARQ job id from the order
    id, and ARQ declines an id it is already running. Changing one answer and confirming
    again is a genuinely different draft and therefore a genuinely different order, which is
    the behaviour a customer expects.

    The fingerprint carries ``WizardDraft.session_id``, so "the same draft" means the same
    RUN through the wizard and not the same answers for all time. Without it a customer who
    wanted a second copy of a song — same recipient, same four answers, same lyric — minted
    the id their first order already holds, collided with the ``orders`` primary key, and
    was told "I could not hand this to the studio" with no reason and no way out, forever.
    Determinism is meant to survive a double tap, not to make a purchase unrepeatable.

    **Determinism is now load-bearing ACROSS PROCESSES too.** The bot records this id on the
    payment intent when it hands a customer a payment link, and the worker recomputes it from
    the parked draft when the payment settles. If the two agree, the draft has not moved and
    the render may start; if they disagree, the customer edited something after paying and
    the resume declines rather than rendering answers they have since changed. A racing 🎬
    press computes this same value, so the ``orders`` primary key, the ARQ job id and
    ``credits.charge``'s already-paid probe all collide on it and only one song is made.
    """
    return uuid5(ORDER_NAMESPACE, order_fingerprint(telegram_user_id, draft))
