"""The Terms of Use + Privacy gate's seam: has this account accepted the current versions?

IMAGE_VIDEO_SPEC §2.1 and D26. Every customer accepts a versioned Terms of Use and Privacy
Notice before using the bot at all — new accounts as an onboarding step after the language
picker, the installed base on their next message. This module is what both of those ask, and
the one thing they write through.

**A leaf, like** :mod:`bayram.user_profiles`: it imports ``bayram.contracts``,
``bayram.errors`` and ``bayram.logging`` and nothing else from the tree — never ``bayram.db``,
never ``bayram.config``. The bot depends on :class:`TermsGate` and two narrow protocols;
``bayram.db.terms.SqlTermsLedger`` is the only thing that knows a ``terms_acceptances`` row
exists, and ``bayram.db`` imports this module rather than the reverse.

**The flag is the version.** ``BAYRAM_TERMS_VERSION`` and ``BAYRAM_PRIVACY_VERSION`` are
empty by default, and with them empty no :class:`TermsGate` is built and nothing anywhere
asks. That is the spec's default until counsel signs the text off (IMAGE_VIDEO_SPEC Q6, M1.3):
the gate goes live when the owner writes a version, and a version bump is what re-prompts
everyone. There is no second boolean to disagree with the versions.

**Reads fail OPEN for the song flow, and CLOSED for media.** :meth:`TermsGate.standing`
answers "accepted" when neither the cache nor the ledger can be read, logged at ERROR (so it
reaches alerting) and never cached. The posture is
``bot.gate.InboundGateMiddleware``'s and ``handlers.onboarding.load_identity``'s, for their
reason: a database blip must not stop the bot answering anyone. What the gate protects is the
lawful-basis RECORD, and the record is a write — :meth:`TermsGate.accept` is a ``Result`` and
a failed write is shown to the customer, never papered over.

That posture is bounded two ways. ``bayram.main`` probes the ledger once at boot and refuses to
start with a version pair set when the probe fails, so a missing revision 0030 or a missing
grant cannot leave the gate silently open for ever. And :meth:`TermsGate.require` is the
fail-CLOSED question: per D20/D26 the Terms are the only control for real people in uploaded
photos, so **every media path from M2 on — quote, submit, upload — must call it before an
upload is accepted or any provider or guard call is made**, and treat its ``Err`` as a refusal.
The bot's media handlers do, through ``bot.media_offer.is_terms_unconfirmed``: before a row is
frozen (image shape pick, video ✅ Done), at a video's last voice step (a note joins the row
there) and at each start press (💳 🎟 🎁). Every provider and guard call is the worker's, on a
row that exists only because one of those passed.

**The cache is ``terms:ok:{tg}``** (IMAGE_VIDEO_SPEC §2.1), valued with the version PAIR and
held a day. Only a positive answer is cached: a negative one would be stale the instant the
customer tapped ✅, and the accept path writes the positive entry itself. ``/forget`` deletes
the key in the same request that anonymises the rows (§9.3), so a forgotten account is asked
again on its next message rather than a day later.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal, Protocol, runtime_checkable

from bayram.contracts import Language, Result, err, is_ok, ok
from bayram.errors import StorageError, ValidationError
from bayram.logging import get_logger

__all__ = [
    "TERMS_CACHE_KEY_PREFIX",
    "TERMS_CACHE_TTL_S",
    "LEGAL_TEXT_FINGERPRINT",
    "LEGAL_TEXT_IS_DRAFT",
    "TermsSource",
    "TermsStanding",
    "TermsVersions",
    "TermsLedger",
    "TermsCache",
    "InMemoryTermsCache",
    "TermsGate",
    "forget_terms_cache",
    "terms_cache_key",
]

_LOG = get_logger(__name__)

#: The cache key's prefix. Spelled once, because the writer (accept), the reader (the gate
#: middleware) and the eraser (``/forget``) are three call sites in two modules.
TERMS_CACHE_KEY_PREFIX: Final[str] = "terms:ok:"

#: One day (IMAGE_VIDEO_SPEC §2.1). Long enough that an active customer costs one ledger read
#: a day, short enough that a row anonymised by hand in the database is honoured by tomorrow.
TERMS_CACHE_TTL_S: Final[int] = 86_400

#: THE TEXT IS A DRAFT (D26, O17, IMAGE_VIDEO_SPEC Appendix A). While this is true every
#: rendering of the Terms and of the Privacy Notice carries ``terms.draft_banner`` at its head.
#: M1.3 — the owner's and counsel's sign-off — flips it, in the same change that replaces the
#: catalogue text with the approved wording. It is a constant rather than a setting on purpose:
#: "this text is approved" is a fact about the text in this build, not about a deployment.
LEGAL_TEXT_IS_DRAFT: Final[bool] = True

#: A fingerprint of the legal text this build ships: ``terms.full`` and ``privacy.text`` in all
#: four catalogues (the recipe is in ``tests/test_bot/test_terms_gate.py``, which recomputes it
#: and fails when it drifts). The versions a customer accepts are owner-written settings while
#: the text ships in the wheel, so nothing else binds the two: a release that changed the text
#: without bumping ``BAYRAM_TERMS_VERSION``/``BAYRAM_PRIVACY_VERSION`` would re-prompt nobody
#: and leave rows claiming acceptance of a text that has since moved. Updating this constant is
#: the deliberate act that says "the text changed" — and the release that ships it must bump
#: the version pair. Not a boot check, because the env version cannot be derived from it.
LEGAL_TEXT_FINGERPRINT: Final[str] = "60a521e4cce7ab82"

#: The account :meth:`TermsGate.probe` asks about. Telegram ids start at 1.
_PROBE_ACCOUNT: Final[int] = 0

#: Which screen an acceptance happened on. The same two values as
#: ``bayram.db.enums.TermsAcceptanceSource``, spelled as a ``Literal`` because this module may
#: not import ``bayram.db``; the SQL ledger converts at its edge.
type TermsSource = Literal["onboarding", "gate"]


class TermsStanding(StrEnum):
    """Where one account stands against the current version pair."""

    #: Accepted exactly the current pair. The only standing that passes the gate.
    ACCEPTED = "accepted"
    #: Accepted an earlier pair and not this one: shown ``terms.updated``.
    OUTDATED = "outdated"
    #: Never accepted anything (or was forgotten): shown ``terms.gate``.
    NEVER = "never"


@dataclass(frozen=True, slots=True)
class TermsVersions:
    """The version pair in force. Both are owner-written strings, typically dates.

    A pair rather than one version because the two documents move independently (§3.2.1): a
    Privacy Notice change alone re-prompts exactly as a Terms change does.
    """

    terms: str
    privacy: str

    @property
    def cache_value(self) -> str:
        """What ``terms:ok:{tg}`` holds for an account that accepted this pair."""
        return f"{self.terms}|{self.privacy}"

    @property
    def stamp(self) -> str:
        """A short fingerprint of the pair, carried on the ✅ button (``TermsCB.v``).

        So that a ✅ drawn before a version bump is recognised as stale and answered with the
        current screen, rather than recording acceptance of a pair the customer never saw.
        Eight hex characters: the callback payload is capped at 64 bytes, and this only has to
        tell the pair in force from the handful that came before it.
        """
        return hashlib.sha256(self.cache_value.encode("utf-8")).hexdigest()[:8]

    @property
    def label(self) -> str:
        """How the pair is named to a customer: one version when both agree, else both."""
        return self.terms if self.terms == self.privacy else f"{self.terms} / {self.privacy}"


def terms_cache_key(telegram_user_id: int) -> str:
    """``terms:ok:{tg}``."""
    return f"{TERMS_CACHE_KEY_PREFIX}{telegram_user_id}"


async def forget_terms_cache(cache: TermsCache, telegram_user_id: int) -> Result[None]:
    """Delete ``terms:ok:{tg}`` (IMAGE_VIDEO_SPEC §9.3). An ``Err`` when Redis refused.

    A free function as well as :meth:`TermsGate.forget` because ``/forget`` must drop the key
    whether or not a gate is wired: an entry written while the gate was on outlives the gate
    being switched off, and switching it back on within the day would otherwise let a
    forgotten account through on an acceptance its anonymised row no longer names.
    """
    try:
        await cache.delete(terms_cache_key(telegram_user_id))
    except Exception as exc:
        _LOG.error("the terms cache entry could not be deleted", extra={"detail": repr(exc)})
        return err(
            StorageError(
                "the terms cache entry could not be deleted",
                context={"telegram_user_id": telegram_user_id},
                cause=exc,
            )
        )
    return ok(None)


@runtime_checkable
class TermsLedger(Protocol):
    """The durable record: ``terms_acceptances`` behind a ``Result`` seam."""

    async def standing(
        self, telegram_user_id: int, versions: TermsVersions
    ) -> Result[TermsStanding]:
        """Where this account stands against ``versions``. Reads only."""
        ...

    async def accept(
        self,
        telegram_user_id: int,
        versions: TermsVersions,
        *,
        language: Language,
        source: TermsSource,
    ) -> Result[None]:
        """Record the acceptance. Idempotent: a second tap of ✅ is ``Ok``.

        **Must not open a ``user_profiles`` row** (IMAGE_VIDEO_SPEC §0.3): onboarding reads
        "has chosen a language" off that table and the terms step sits before the contact
        screen.
        """
        ...


@runtime_checkable
class TermsCache(Protocol):
    """The three Redis commands the cache uses. ``redis.asyncio.Redis`` satisfies it as is.

    Narrow for the reason :class:`bayram.payme.pause.PauseSwitch` is: a test can make any one
    of them fail on demand, which is the only way the fail-open paragraphs can be asserted.
    """

    async def get(self, name: str) -> Any: ...

    async def set(self, name: str, value: str, *, ex: int) -> Any: ...

    async def delete(self, *names: str) -> Any: ...


class InMemoryTermsCache:
    """A process-local :class:`TermsCache` for the demo path and the test suite.

    Expiry is not modelled: nothing that runs against this lives for a day.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> bool:
        del ex
        self.values[name] = value
        return True

    async def delete(self, *names: str) -> int:
        return sum(1 for name in names if self.values.pop(name, None) is not None)


class TermsGate:
    """The ledger, the cache and the version pair, as the three questions the bot asks.

    Built only when a version pair is configured; ``BotDeps.terms is None`` is "no gate".
    """

    def __init__(
        self,
        ledger: TermsLedger,
        versions: TermsVersions,
        *,
        cache: TermsCache | None = None,
        url: str = "",
    ) -> None:
        self._ledger = ledger
        self._cache = cache if cache is not None else InMemoryTermsCache()
        #: The pair in force. Public: the screens name it and the accept handler records it.
        self.versions = versions
        #: Optional link to the full text on the web (``BAYRAM_TERMS_URL``). Empty: no link.
        self.url = url

    async def standing(self, telegram_user_id: int) -> TermsStanding:
        """Where this account stands. **Never raises; fails OPEN** — see the module docstring.

        Cache first: a hit on the current pair answers without the database. A miss asks the
        ledger, and only an ``ACCEPTED`` answer is written back.
        """
        key = terms_cache_key(telegram_user_id)
        try:
            cached = await self._cache.get(key)
        except Exception as exc:
            # Broad for PauseSwitch's reason: redis-py, asyncio and the socket layer all raise
            # their own types, and the answer owed is the same — ask the ledger instead.
            _LOG.warning("the terms cache could not be read", extra={"detail": repr(exc)})
            cached = None
        if _decoded(cached) == self.versions.cache_value:
            return TermsStanding.ACCEPTED
        result = await self._ledger.standing(telegram_user_id, self.versions)
        if not is_ok(result):
            # NOT cached, so the next update asks again rather than a blip becoming a day. ERROR,
            # not WARNING: an open gate nobody notices is the failure this line exists to stop.
            _LOG.error(
                "the terms ledger could not be read; treating the account as accepted",
                extra=result.error.to_log_dict(),
            )
            return TermsStanding.ACCEPTED
        if result.value is TermsStanding.ACCEPTED:
            await self._remember(key)
        return result.value

    async def probe(self) -> Result[None]:
        """One ledger read, for the boot check in ``bayram.main``: ``Err`` when it cannot be
        read at all — revision 0030 not applied, a role without grants on the table, no
        database. The account asked about is ``0``, which Telegram never issues; the answer
        is thrown away, only whether one came back matters."""
        result = await self._ledger.standing(_PROBE_ACCOUNT, self.versions)
        return ok(None) if is_ok(result) else err(result.error)

    async def require(self, telegram_user_id: int) -> Result[None]:
        """FAIL-CLOSED: ``Ok`` only when this account has accepted the pair in force.

        The media paths' question (D20, D26), where an open gate means a face photo processed
        with no lawful-basis record: ``NEVER``, ``OUTDATED`` and an unreadable ledger are all
        an ``Err``. A cache hit on the current pair answers without the database, as
        :meth:`standing` does; everything else asks the ledger, and only its answer counts.
        """
        key = terms_cache_key(telegram_user_id)
        try:
            cached = await self._cache.get(key)
        except Exception as exc:
            _LOG.warning("the terms cache could not be read", extra={"detail": repr(exc)})
            cached = None
        if _decoded(cached) == self.versions.cache_value:
            return ok(None)
        result = await self._ledger.standing(telegram_user_id, self.versions)
        if not is_ok(result):
            _LOG.error(
                "the terms ledger could not be read; refusing (fail closed)",
                extra=result.error.to_log_dict(),
            )
            return err(result.error)
        if result.value is not TermsStanding.ACCEPTED:
            return err(
                ValidationError(
                    "the terms in force have not been accepted",
                    context={
                        "telegram_user_id": telegram_user_id,
                        "standing": result.value.value,
                    },
                )
            )
        await self._remember(key)
        return ok(None)

    async def accept(
        self, telegram_user_id: int, *, language: Language, source: TermsSource
    ) -> Result[None]:
        """Record the acceptance, then cache it. A failed RECORD is an ``Err``; a failed cache
        write is not, because the next read simply asks the ledger again."""
        recorded = await self._ledger.accept(
            telegram_user_id, self.versions, language=language, source=source
        )
        if not is_ok(recorded):
            return recorded
        await self._remember(terms_cache_key(telegram_user_id))
        return ok(None)

    async def forget(self, telegram_user_id: int) -> Result[None]:
        """Delete ``terms:ok:{tg}`` (IMAGE_VIDEO_SPEC §9.3). An ``Err`` when Redis refused.

        Unlike the reads, a failed delete is reported: ``/forget`` promises the account is
        asked again, and a stale positive entry would skip it for up to a day.
        """
        return await forget_terms_cache(self._cache, telegram_user_id)

    async def _remember(self, key: str) -> None:
        try:
            await self._cache.set(key, self.versions.cache_value, ex=TERMS_CACHE_TTL_S)
        except Exception as exc:
            _LOG.warning("the terms cache could not be written", extra={"detail": repr(exc)})


def _decoded(value: object) -> str | None:
    """A cache value as text. redis-py answers ``bytes`` unless ``decode_responses`` is set."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else None
