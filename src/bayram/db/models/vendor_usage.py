"""``vendor_usage`` — append-only, so "what did we ask each vendor to do, and what did it
cost" is a query rather than an argument.

Nothing in this schema could answer that question before. ``generation_attempts`` is the
table it looks like it should live on and it is the wrong home twice over:

* **Its clocks would erase the spend history.** That table sits on two retention clocks —
  identity at 90 days, free text at 30 — because it holds the recipient's name and the STT
  transcript. Spend has to survive a year-over-year comparison, and a billing question
  arrives long after the personal data on that row is lawfully gone.
* **Its quantity columns default to zero.** ``cost_usd`` defaults to ``0.0`` and
  ``latency_ms`` to ``0``, so every one of its rows carries a cost that was never measured
  and reads as "free". That is precisely why ``src/bayram/admin/routers/dashboard.py`` refuses
  to draw a cost figure at all today, and it is the single defect this table exists not to
  repeat. **Every quantity column below is NULLABLE with no default.** A group nobody
  measured comes back from ``SUM()`` as ``NULL``, the panel renders "not priced", and the
  null-never-zero rule costs no application code anywhere.

It also holds facts no existing column can: tokens, billed characters, billed milliseconds,
an HTTP status and a per-call vendor model id.

**Cost carries its provenance, enforced by the database.** ``cost_usd`` and ``cost_source``
are both null or both set (``cost_carries_its_source``); there is no such thing here as a
dollar figure whose trust level is unknown. Provenance is honest per leg: OpenRouter's own
``usage.cost`` is ``VENDOR_REPORTED``, token-rate arithmetic is ``DERIVED``, a music render
is ``ESTIMATED`` (our rate against the duration we ASKED for, not a vendor-confirmed render
length), and transcription gets no cost at all because nothing in this system measures
audio duration and bytes times a guessed bitrate is a fabricated number.

**There is no foreign key to ``orders``**, following ``credit_ledger`` exactly. Spend
outlives the order it belongs to — an abandoned draft is deleted at 14 days and the money
was still spent — and the wizard's lyric-preview call happens BEFORE an order row exists,
so a constraint here would either reject a true row or force the bot to invent an order id.
``order_id`` is indexed because "what did this order cost" is a real question. So is
``cost_usd``, for a question with no rows in it: ``has_priced_vendor_usage`` asks
``WHERE cost_usd IS NOT NULL LIMIT 1`` on every ``/api/ops/pulse``, which the Live screen
polls every five seconds, and a ``LIMIT 1`` only stops early when there is something to stop
at — unindexed, a deployment that prices nothing pays for a full scan of the largest table
here twelve times a minute, forever.

**Not personal data, and deliberately on no personal-data clock.** Every column is a closed
enum, an integer, a machine id or a bounded error code — no name, no note, no transcript,
no telegram id, no free text of any kind — so the table belongs in NEITHER
``tables_with_personal_data`` nor ``tables_erased_on_request`` in
``tests/test_db/test_privacy_constraints.py``, and that omission is recorded there in a
comment rather than left silent. Bounded growth is still handled, on the ``purge_runs``
precedent: ``bayram.db.purge.VENDOR_USAGE_RETENTION_DAYS`` deletes rows past 400 days, a
cutoff and not an expiry. No column here is named ``*_expires_at`` — that suffix obliges a
sweep BY NAME in ``tests/test_db/test_audit_retention.py``, and this table's clock is a
retention cutoff on ``created_at``, not a per-row expiry stamped by a writer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import CostSource, UsageTask, Vendor, VendorOperation
from bayram.db.base import Base, UtcDateTime, enum_type, utc_now

__all__ = ["VendorUsageRow", "PROVIDER_LENGTH", "MODEL_ID_LENGTH", "ERROR_CODE_LENGTH"]

#: Adapter names are ours and short: ``elevenlabs_music``, ``openai-compat``, ``fake_stt``.
PROVIDER_LENGTH: Final[int] = 64
#: A vendor model id is theirs and can be a slug with a vendor prefix and a variant suffix
#: (``google/gemma-4-31b-it:free``), so it gets twice the room an adapter name needs.
MODEL_ID_LENGTH: Final[int] = 128
#: Mirrors ``purge_runs.error_code``: ``BayramError.error_code`` is a short symbolic name from
#: a closed taxonomy, never a message and never a response-body excerpt.
ERROR_CODE_LENGTH: Final[int] = 48

#: The one composite index this table gets, and the whole index budget beside the three
#: templated ones (``created_at``, ``order_id``, ``cost_usd``). The rollup filters
#: ``created_at`` and groups by vendor, so leading with
#: ``vendor`` and carrying ``id`` makes the window scan index-only. Hand-named, exactly like
#: revision 0015's ``_USER_ENDS_INDEX``: ``NAMING_CONVENTION``'s ``ix`` template would
#: render ``ix_vendor_usage_vendor_created_at_id``, which the migration does not create, so
#: ``test_the_migrated_indexes_match_the_model_metadata`` would report it missing.
_VENDOR_CREATED_INDEX: Final[str] = "ix_vendor_usage_vendor_created_at"


class VendorUsageRow(Base):
    """One vendor call: what was asked, what came back, what it cost, and how we know.

    ``TimestampMixin`` is deliberately not used, following ``credit_ledger`` and
    ``purge_runs``. This row is a measurement of a moment that has already passed; an
    ``updated_at`` could never be true, and offering one would invite a writer to amend a
    record whose whole value is that nobody amends it. ``created_at`` is declared here
    instead, indexed, because every read of this table is bounded by a window.
    """

    __tablename__ = "vendor_usage"
    __table_args__ = (
        # A dollar figure with no provenance is unreadable: nobody can tell a number the
        # vendor billed us from arithmetic over our own rate card, and the panel renders the
        # two differently on purpose. The pairing is enforced here rather than trusted to
        # five call sites in four adapters.
        sa.CheckConstraint(
            "(cost_usd IS NULL AND cost_source IS NULL)"
            " OR (cost_usd IS NOT NULL AND cost_source IS NOT NULL)",
            name="cost_carries_its_source",
        ),
        # Deliberately NO constraint tying ``error_code`` to ``is_success``. Over-constraining
        # a telemetry table loses rows, and a lost row is a hole in the spend record; a
        # nonsensical pairing is at worst a confusing one.
        sa.Index(_VENDOR_CREATED_INDEX, "vendor", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: Who bills us. Coarser than ``provider``: two ElevenLabs adapters, one invoice.
    vendor: Mapped[Vendor] = mapped_column(enum_type(Vendor), nullable=False)
    #: What they were asked to do — the unit their rate card is quoted in.
    operation: Mapped[VendorOperation] = mapped_column(enum_type(VendorOperation), nullable=False)
    #: The adapter that made the call: ``elevenlabs_music`` | ``elevenlabs_tts`` |
    #: ``elevenlabs_scribe`` | ``openai-compat`` | ``gemini`` | ``fake_music`` | ``fake_tts``
    #: | ``fake_llm`` | ``fake_stt``.
    provider: Mapped[str] = mapped_column(sa.String(PROVIDER_LENGTH), nullable=False)
    #: The vendor's model id (``music_v2``, ``eleven_v3``, ``google/gemma-4-31b-it:free``).
    #: Nullable because a transport error can happen before a model is ever named.
    model_id: Mapped[str | None] = mapped_column(sa.String(MODEL_ID_LENGTH), nullable=True)
    #: True for the second OpenRouter account. Today both LLM adapters report the same
    #: ``name="openai-compat"``, so this flag is the only thing that tells the fallback's
    #: spend apart from the primary's.
    is_fallback: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    #: True under ``BAYRAM_USE_FAKE_PROVIDERS``. A demo run is RECORDED and visibly excluded
    #: rather than invisible: no rows at all cannot be told from an uninstrumented deploy.
    is_fake: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    #: What the call was for, from ``usage_scope()``. Nullable: a health probe is for nothing.
    task: Mapped[UsageTask | None] = mapped_column(enum_type(UsageTask), nullable=True)
    #: Which order the spend belongs to. **No foreign key** — see the module docstring.
    #: ``NULL`` is a true answer, not a missing one: the wizard's lyric preview runs before
    #: any order exists.
    order_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True, index=True)
    #: The request's correlation id, so one line of the log and one row here can be joined.
    #: ``NULL`` when nothing was bound — the unbound ``"-"`` is never stored as a value.
    correlation_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    is_success: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    #: ``NULL`` for a transport failure, where no response ever arrived to carry a status.
    http_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: From the closed ``bayram.errors`` taxonomy, never a body excerpt: a vendor error body
    #: can quote the prompt back, and the prompt names a real person.
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)

    # -- quantities. Every one nullable, none defaulted. -----------------------
    # A default of 0 here is what made ``generation_attempts`` unreadable: it turns "nobody
    # measured this" into "this cost nothing", and no reader downstream can undo that.
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: TTS only. From the vendor's ``character-cost`` header when it sent one, and from
    #: ``len(text)`` when it did not — which is what makes that leg's cost ``ESTIMATED``
    #: rather than ``DERIVED``.
    billed_characters: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Music only, and it is the duration we ASKED for. Transcription leaves it ``NULL``:
    #: this system measures audio in bytes, and bytes times an assumed bitrate is invented.
    audio_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    request_bytes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    response_bytes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: **NO DEFAULT.** ``NULL`` means "not priced here" and never "free". Out of the box the
    #: music leg alone carries a figure — ``music_usd_per_minute`` ships at a placeholder
    #: ``0.15`` and its rows say ``ESTIMATED`` — while speech
    #: (``BAYRAM_ELEVENLABS_USD_PER_CHARACTER=0``), both LLM legs and transcription write ``NULL``
    #: until a rate is configured, or forever in Scribe's case. A fresh deployment therefore
    #: holds priced and unpriced rows side by side, which is why no reader may sum this column
    #: without ``count(cost_usd IS NOT NULL)`` beside it, and why ``$0.00`` is never written
    #: here: it would be a lie with a dollar sign on it.
    #: Indexed for ``has_priced_vendor_usage`` — see the module docstring.
    cost_usd: Mapped[float | None] = mapped_column(sa.Float, nullable=True, index=True)
    #: How that figure was arrived at. Bound to ``cost_usd`` by the CHECK above.
    cost_source: Mapped[CostSource | None] = mapped_column(enum_type(CostSource), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
