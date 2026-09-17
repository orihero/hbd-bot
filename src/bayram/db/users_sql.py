"""The ONE writer of the ``users`` row's identity, liveness and interface language.

This module exists because the moment a ``users`` row is born moved. It used to be born in
``repository._ensure_user`` from ``_create_order`` — the only writer, several screens after
the customer first said hello — and everything downstream was written against that fact:
``credits.set_blocked`` upserts precisely because "most people the bot has spoken to have no
row", and ``models/user.py``'s own docstring said the row appears at first order. Onboarding
answers the language question long before an order exists and has to persist the answer, so
the writer moves OUT of the kit repository into a module both callers reach without the bot
importing ``SqlKitRepository`` — which would hand the bot ``create_order`` and hand the
worker a customer write, the coupling :class:`bayram.db.user_profiles.SqlUserProfiles` and
``KitRepository`` are kept apart to avoid.

**Why an UPSERT and not the SELECT-then-INSERT it replaces.** ``credits.touch`` writes this
same row from ``bayram.bot.gate.TouchDrain``, which runs on its own task OFF the per-chat FSM
isolation lock. A ``SELECT`` that finds nothing followed by an ``INSERT`` therefore has a
real interleaving — the drain inserts between the two statements — and the loser gets an
``IntegrityError``, which ``bayram.db.guard.run_guarded`` classifies as TERMINAL and never
retries. That failure would land at the exact moment a first-contact customer is answering
the language question, i.e. the one write in the system that has no second chance to be
made. Behaviour is otherwise identical to what it replaces: an existing row has its
``last_seen_at`` moved and its ``ui_language`` left alone; a missing row is inserted with the
language it was given.

The shape is the module-level half of the split :mod:`bayram.db.credits` and
:mod:`bayram.db.lyric_budget` both make: session first and positional, ``now`` as a parameter,
exceptions allowed to propagate, and **never a commit** — so a caller composes this into the
transaction it already owns rather than nesting one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.contracts import Language
from bayram.db.credit_sql import upsert_statement
from bayram.db.models.user import UserRow
from bayram.errors import ValidationError

__all__ = ["ensure_user", "DEFAULT_UI_LANGUAGE"]

#: The language a ``users`` row is born with when the update that created it said nothing
#: about a language. It MUST equal ``UserRow.ui_language``'s column default
#: (``models/user.py:37-39``), which is ``nullable=False``: an INSERT that omitted the
#: column — or, worse, sent ``None`` into it — violates the constraint, ``run_guarded``
#: turns that into an ``Err``, and NO ``users`` row is ever created for a pre-onboarding
#: account. The block gate would then silently stop covering exactly the population
#: ``tests/test_bot/test_gate_middleware.py:138-158`` exists to cover. Named rather than
#: left to the ORM/Core default so that "the language a row is born with" has one spelling
#: a reader can find; :mod:`bayram.db.credits` declares the same value for the same reason and
#: the two are deliberately independent of each other's import order.
DEFAULT_UI_LANGUAGE: Final[Language] = Language.UZ_LATN


async def ensure_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    ui_language: Language | None,
    now: datetime,
    is_language_authoritative: bool,
) -> UUID:
    """Find or create this account's ``users`` row, stamp its liveness, return its id.

    **``is_language_authoritative`` is the whole point of the signature.** An order is
    evidence that an account is alive; it is not evidence about which language its owner
    READS in. ``repository._create_order`` therefore passes ``False`` and a brief's
    ``ui_language`` can never stamp over a settings choice — which is byte-for-byte the
    behaviour of the function this replaces, whose existing-row branch touched only
    ``last_seen_at`` and which ``bayram.bot.gate`` cites out loud at ``gate.py:124-128``.
    ``SqlUserProfiles.record_language`` passes ``True``, because a customer choosing a
    language in Settings is the authoritative event and the only one. Without the flag this
    function would be the same defect ``bayram.db.credits.touch`` was fixed for, wearing a
    second hat: every confirmed order silently re-writing the interface language from a
    field the wizard filled in with a fallback.

    **``ui_language`` is ``Language | None`` because some callers honestly know nothing
    about it.** ``record_contact`` shares a phone number and has no opinion on language;
    inventing one there would be the same clobber wearing a third hat. ``None`` means "this
    call knows nothing about the language": on INSERT the column takes
    :data:`DEFAULT_UI_LANGUAGE`, and on UPDATE the column is left exactly as it was.

    ``is_language_authoritative=True`` with ``ui_language=None`` is meaningless — it claims
    authority over a value it does not have — so it raises :class:`bayram.errors.ValidationError`
    instead of quietly writing nothing. A miswired call site must be loud: the silent version
    of this bug is "the settings screen saves nothing", which nobody notices until a customer
    complains, and ``run_guarded`` turns the raise into a named, terminal ``Err`` at the store
    boundary rather than letting it escape a never-throw facade.

    ``is_blocked`` is absent from the update clause for the reason ``credits.touch`` states:
    this runs on ordinary traffic, and an upsert that reset the flag would unblock an abuser
    on their next message.

    Returns the row's ``id`` — read back with a ``SELECT`` rather than ``RETURNING`` because
    the id in the values dict is discarded on conflict, exactly as ``credits.set_blocked``
    and ``credits.touch`` discard theirs, and because a second read inside one transaction is
    portable across both drivers where ``RETURNING`` on an upsert is not.
    """
    if is_language_authoritative and ui_language is None:
        raise ValidationError(
            "ensure_user was told the language is authoritative but given no language",
            context={"telegram_user_id": telegram_user_id},
        )
    set_: dict[str, Any] = {"last_seen_at": now, "updated_at": now}
    if is_language_authoritative and ui_language is not None:
        set_["ui_language"] = ui_language
    await session.execute(
        upsert_statement(
            session,
            UserRow,
            {
                # Discarded on conflict; the row that already exists keeps its own id.
                "id": uuid4(),
                "telegram_user_id": telegram_user_id,
                "ui_language": (ui_language if ui_language is not None else DEFAULT_UI_LANGUAGE),
                "is_blocked": False,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            },
            index_elements=["telegram_user_id"],
            set_=set_,
        )
    )
    user_id = await session.scalar(
        sa.select(UserRow.id).where(UserRow.telegram_user_id == telegram_user_id)
    )
    if user_id is None:  # pragma: no cover - the upsert above guarantees the row exists
        raise ValidationError(
            "the users row vanished between its upsert and its read-back",
            context={"telegram_user_id": telegram_user_id},
        )
    return user_id
