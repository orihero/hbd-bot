"""An ``LlmProvider`` that answers from templates. No key, no network, no spend.

This is what ``HBD_USE_FAKE_PROVIDERS=1`` installs, and it exists so the whole application
— wizard, queue, pipeline, ffmpeg, delivery — can be run and demonstrated on a laptop with
nothing configured.

It dispatches on the *shape* of the requested response model, never on its name or module.
That matters: two packages define lyric payloads (``hbd.pipeline.content`` and
``hbd.providers.llm.schemas``) and this file must not import either, or the fake would drag
the pipeline into the provider layer to satisfy a demo.

A model it cannot recognise gets a typed ``Err``, never an exception and never a silently
empty object — a fake that quietly returns nothing teaches the pipeline the wrong lesson
about what a bad payload looks like.

It also RECORDS its calls, which sounds odd for something that spends nothing and is the
point: a demo run that wrote no ``vendor_usage`` rows at all would be indistinguishable
from a production deployment nobody instrumented, and "vendor usage is not recorded here"
is a sentence the panel must only ever say when it is true. So a fake call is measured
like any other, stamped ``is_fake`` and ``Vendor.FAKE``, and visibly excluded from spend
rather than invisible. It carries no cost and no HTTP status, because there was no vendor
and no request — inventing either would be the fabricated number this system refuses.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Final

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from hbd.contracts import (
    Err,
    HealthState,
    Language,
    LlmRequest,
    ProviderHealth,
    Result,
    Vendor,
    VendorOperation,
    err,
    ok,
)
from hbd.errors import HbdError, LlmParseError
from hbd.logging import get_logger
from hbd.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = ["FakeLlmProvider", "FAKE_LLM_NAME"]

_LOG = get_logger(__name__)

FAKE_LLM_NAME: Final[str] = "fake_llm"

#: The prompt builders quote the recipient and the cast; the fake reads them back out so
#: its answers are about the right person rather than a placeholder.
_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'recipient(?: is)? name[d]?:?\s*"([^"]+)"', re.IGNORECASE
)
_PERSONA_PATTERN: Final[re.Pattern[str]] = re.compile(r'persona_id "([^"]+)"')
_TITLE_PATTERN: Final[re.Pattern[str]] = re.compile(r'titled "([^"]+)"')

#: Keyed by the language phrase the prompt builder writes into the brief.
_LANGUAGE_MARKERS: Final[tuple[tuple[str, Language], ...]] = (
    ("Latin alphabet", Language.UZ_LATN),
    ("Cyrillic alphabet", Language.UZ_CYRL),
    ("Russian", Language.RU),
    ("English", Language.EN),
)

_TITLES: Final[dict[Language, str]] = {
    Language.UZ_LATN: "Tugʻilgan kuning muborak",
    Language.UZ_CYRL: "Туғилган кунинг муборак",
    Language.RU: "С днём рождения",
    Language.EN: "Happy Birthday To You",
}

#: Four ordinary lines per language. The name gets its own section, always.
_VERSES: Final[dict[Language, tuple[str, ...]]] = {
    Language.UZ_LATN: (
        "Bugun quyosh boshqacha porlaydi",
        "Doʻstlaring yoningda kulib turibdi",
        "Yillar oʻtsa ham bu qoʻshiq yangraydi",
        "Baxting doim shu uyda boʻlsin",
    ),
    Language.UZ_CYRL: (
        "Бугун қуёш бошқача порлайди",
        "Дўстларинг ёнингда кулиб турибди",
        "Йиллар ўтса ҳам бу қўшиқ янграйди",
        "Бахтинг доим шу уйда бўлсин",
    ),
    Language.RU: (
        "Сегодня солнце светит по-другому",
        "Друзья с тобой и все они смеются",
        "Пусть эта песня в сердце остаётся",
        "И счастье не уходит из дома",
    ),
    Language.EN: (
        "The morning light is different today",
        "Your friends are here and nobody is leaving",
        "This song will find you every single year",
        "And happiness will know your address",
    ),
}

_GREETINGS: Final[dict[Language, str]] = {
    Language.UZ_LATN: (
        "Assalomu alaykum, {name}! Tugʻilgan kuning muborak boʻlsin. "
        "Sogʻliging joyida, uying doim toʻkin, yuraging doim shod boʻlsin. "
        "Yangi yoshing senga faqat yaxshilik olib kelsin, {name}."
    ),
    Language.UZ_CYRL: (
        "Ассалому алайкум, {name}! Туғилган кунинг муборак бўлсин. "
        "Соғлигинг жойида, уйинг доим тўкин, юрагинг доим шод бўлсин. "
        "Янги ёшинг сенга фақат яхшилик олиб келсин, {name}."
    ),
    Language.RU: (
        "Здравствуй, {name}! С днём рождения тебя. "
        "Пусть здоровье будет крепким, дом полным, а сердце спокойным. "
        "Пусть новый год жизни принесёт тебе только хорошее, {name}."
    ),
    Language.EN: (
        "Hello, {name}! Happy birthday to you. "
        "May your health hold, your house stay full and your heart stay light. "
        "May this new year bring you nothing but good things, {name}."
    ),
}

_FALLBACK_NAME: Final[str] = "Doʻstim"
_HOOK_LABEL: Final[str] = "hook"

_MS_PER_S: Final[float] = 1_000.0


def _elapsed_ms(started: float) -> int:
    """Whole milliseconds since ``started``. The unit ``vendor_usage.latency_ms`` stores."""
    return int((perf_counter() - started) * _MS_PER_S)


def _language_of(prompt: str) -> Language:
    for marker, language in _LANGUAGE_MARKERS:
        if marker in prompt:
            return language
    return Language.UZ_LATN


def _name_in(prompt: str) -> str:
    found = _NAME_PATTERN.search(prompt)
    return found.group(1) if found else _FALLBACK_NAME


def _lyrics_payload(prompt: str) -> dict[str, Any]:
    language = _language_of(prompt)
    name = _name_in(prompt)
    verses = _VERSES[language]
    return {
        "title": _TITLES[language],
        "sections": [
            {"label": "verse-1", "lines": [verses[0], verses[1]], "is_name_hook": False},
            {"label": _HOOK_LABEL, "lines": [name], "is_name_hook": True},
            {"label": "chorus", "lines": [verses[2], verses[3]], "is_name_hook": False},
        ],
    }


def _greetings_payload(prompt: str) -> dict[str, Any]:
    language = _language_of(prompt)
    name = _name_in(prompt)
    personas = _PERSONA_PATTERN.findall(prompt) or ["persona-1"]
    template = _GREETINGS[language]
    return {
        "greetings": [
            {"persona_id": persona, "text": template.format(name=name)} for persona in personas
        ]
    }


def _moderation_payload(_: str) -> dict[str, Any]:
    return {"is_allowed": True, "reason": ""}


def _kit_payload(prompt: str) -> dict[str, Any]:
    """The one-shot writer's combined shape, assembled from the two above."""
    lyrics = _lyrics_payload(prompt)
    title = _TITLE_PATTERN.search(prompt)
    if title is not None:
        lyrics["title"] = title.group(1)
    return {
        **lyrics,
        **_greetings_payload(prompt),
        "name_line": _name_in(prompt),
        "respellings": [],
    }


#: Shape probes, most specific first. A response model is matched by the fields it
#: declares, so neither payload package has to be imported here.
_ANSWERS: Final[tuple[tuple[frozenset[str], Any], ...]] = (
    (frozenset({"sections", "greetings"}), _kit_payload),
    (frozenset({"is_allowed"}), _moderation_payload),
    (frozenset({"greetings"}), _greetings_payload),
    (frozenset({"sections"}), _lyrics_payload),
)


def _answer_for(fields: frozenset[str], prompt: str) -> dict[str, Any] | None:
    for required, build in _ANSWERS:
        if required <= fields:
            payload: dict[str, Any] = build(prompt)
            return payload
    return None


class FakeLlmProvider:
    """Deterministic ``LlmProvider``. Structurally satisfies the protocol; never raises."""

    name: str = FAKE_LLM_NAME

    def __init__(self, *, usage: UsageSink = LOGGING_USAGE_SINK) -> None:
        self._usage = usage

    async def generate_json[M: BaseModel](
        self, request: LlmRequest, response_model: type[M], *, timeout_s: float
    ) -> Result[M]:
        started = perf_counter()
        result = self._answer(request, response_model)
        await self._record(
            operation=VendorOperation.CHAT_COMPLETION,
            error=result.error if isinstance(result, Err) else None,
            latency_ms=_elapsed_ms(started),
        )
        return result

    async def health(self) -> Result[ProviderHealth]:
        started = perf_counter()
        await self._record(
            operation=VendorOperation.HEALTH, error=None, latency_ms=_elapsed_ms(started)
        )
        return ok(
            ProviderHealth(
                name=self.name,
                state=HealthState.HEALTHY,
                as_of=datetime.now(tz=UTC),
                detail="fake provider; no vendor contacted",
            )
        )

    # -- internals ----------------------------------------------------------
    def _answer[M: BaseModel](self, request: LlmRequest, response_model: type[M]) -> Result[M]:
        """The template lookup and validation. Unchanged behaviour, lifted out to measure."""
        prompt = f"{request.system_prompt}\n{request.user_prompt}"
        fields = frozenset(response_model.model_fields)
        payload = _answer_for(fields, prompt)
        if payload is None:
            return err(
                LlmParseError(
                    "the fake LLM has no template for this response shape",
                    provider=self.name,
                    context={"model": response_model.__name__, "fields": sorted(fields)},
                )
            )
        try:
            return ok(response_model.model_validate(payload))
        except PydanticValidationError as exc:
            _LOG.error(
                "fake LLM template did not satisfy the requested model",
                extra={"model": response_model.__name__, "detail": str(exc)},
            )
            return err(
                LlmParseError(
                    "the fake LLM template did not validate against the requested model",
                    provider=self.name,
                    context={"model": response_model.__name__},
                    cause=exc,
                )
            )

    async def _record(
        self, *, operation: VendorOperation, error: HbdError | None, latency_ms: int
    ) -> None:
        """One row per call, flagged fake. Every quantity absent, because there was none.

        ``model_id`` and ``http_status`` stay ``None`` on purpose: no vendor model
        answered and no request was sent, so there is nothing measured to put in either.
        ``latency_ms`` is the exception — it is a real measurement of real local work.
        """
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.FAKE,
                operation=operation,
                provider=self.name,
                is_success=error is None,
                is_fake=True,
                error_code=error.error_code.value if error is not None else None,
                latency_ms=latency_ms,
            )
        )
