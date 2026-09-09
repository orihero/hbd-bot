"""``python -m hbd.tools.identity show|set`` — the bot's public face, from the token alone.

@BotFather is a chat window: what it changes it changes silently, for whoever happened to
be typing, with no record of the before state and no way to repeat the same change on a
second bot. Everything it can do to the profile — the picture, the name, the two
descriptions — the Bot API can also do with the token this process already holds
(``setMyProfilePhoto`` and friends), so this module exists to make those four values a
command an operator can read, review in a diff and run again against staging.

**Nothing is inferred.** Each field is written only when its flag is given, and
``--description ""`` clears the description rather than being treated as "unset" — the
distinction matters because an empty description is a legitimate state that BotFather can
produce and that ``show`` will report back. A ``set`` with no flags is refused: it would
otherwise look like it had done something.

**The picture must already be a JPEG.** ``InputProfilePhotoStatic`` takes ``.JPG`` and
nothing else, and Telegram's error for a PNG is a generic 400 that says nothing about the
format. Converting here would mean an image library in the dependency set for a command
run twice a year, so a non-JPEG is refused with the one-line ``sips`` invocation that fixes
it. ``brand/avatar-telegram.jpg`` is the flattened cut of the brand avatar, kept next to
its PNG for exactly this call.

**Every locale is separate, and this tool writes one.** ``setMyName`` and both description
setters take a ``language_code``; writing with none sets the DEFAULT text every client
falls back to, which is what an operator almost always means. ``--language-code ru`` writes
the Russian variant and leaves the default untouched — so ``show`` prints the locale it
read, or nobody can tell an empty translation from an empty default.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from aiogram import Bot
from aiogram.types import FSInputFile, InputProfilePhotoStatic

from hbd.config import build_settings
from hbd.errors import HbdError
from hbd.logging import configure_logging, get_logger

__all__ = [
    "main",
    "plan",
    "apply",
    "Show",
    "Change",
    "Request",
    "RefusedError",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_CONFIG",
]

_LOG = get_logger(__name__)

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1
EXIT_CONFIG: Final[int] = 2

#: Telegram's own caps. Refused here rather than at the API, because a 400 on the third of
#: four writes leaves the profile half-changed with no sentence explaining which half.
_MAX_NAME: Final[int] = 64
_MAX_DESCRIPTION: Final[int] = 512
_MAX_SHORT_DESCRIPTION: Final[int] = 120

#: The upload ceiling for a photo, and the magic bytes every JPEG starts with.
_MAX_PHOTO_BYTES: Final[int] = 10 * 1024 * 1024
_JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"


class RefusedError(Exception):
    """An operator-facing refusal. Its message is printed; nothing else is."""


@dataclass(frozen=True, slots=True)
class Show:
    """A read of the four values, in one locale."""

    language_code: str


@dataclass(frozen=True, slots=True)
class Change:
    """A validated ``set``. A ``None`` field is one the operator did not name."""

    language_code: str
    name: str | None = None
    description: str | None = None
    short_description: str | None = None
    photo: Path | None = None


type Request = Show | Change


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m hbd.tools.identity",
        description="Read or set the bot's picture, name and descriptions over the Bot API.",
    )
    sub = parser.add_subparsers(dest="verb", required=True)

    show = sub.add_parser("show", help="print the current name and descriptions")
    _add_language(show)

    change = sub.add_parser("set", help="write the fields named by the flags given")
    _add_language(change)
    change.add_argument(
        "--name",
        default=None,
        help=f"the bot's display name, up to {_MAX_NAME} characters",
    )
    change.add_argument(
        "--description",
        default=None,
        help=(f'the empty-chat blurb, up to {_MAX_DESCRIPTION} characters. Pass "" to clear it.'),
    )
    change.add_argument(
        "--short-description",
        default=None,
        help=(
            f"the profile-page line, up to {_MAX_SHORT_DESCRIPTION} characters. "
            'Pass "" to clear it.'
        ),
    )
    change.add_argument(
        "--photo",
        default=None,
        help="path to a square JPEG, e.g. brand/avatar-telegram.jpg. Not localisable.",
    )
    return parser.parse_args(argv)


def _add_language(parser: argparse.ArgumentParser) -> None:
    """The locale selector, defined once so both verbs describe it identically."""
    parser.add_argument(
        "--language-code",
        default="",
        help=(
            "the locale to read or write, e.g. ru. Omit for the default text, which is "
            "what clients fall back to and what an operator usually means."
        ),
    )


def _language_code(raw: str) -> str:
    """A locale tag, or the empty string meaning "the default"."""
    code = raw.strip()
    if not code:
        return ""
    if not (2 <= len(code) <= 5 and code.replace("-", "").isalpha()):
        raise RefusedError(
            f"Refusing --language-code {raw!r}: give a tag like ru or pt-BR, or omit it "
            "to write the default text."
        )
    return code.lower()


def _text(raw: str, *, flag: str, limit: int) -> str:
    """One profile string, refused rather than sent to be truncated by somebody else."""
    # Not stripped: a description is prose the operator wrote, and trailing whitespace is
    # theirs to keep. Only the length is ours to judge.
    if len(raw) > limit:
        raise RefusedError(f"Refusing {flag}: at most {limit} characters, and this is {len(raw)}.")
    return raw


def _name(raw: str) -> str:
    """The display name. Unlike the descriptions, it cannot be cleared."""
    if not raw.strip():
        raise RefusedError("Refusing --name: a bot with an empty name is not a state Telegram has.")
    return _text(raw, flag="--name", limit=_MAX_NAME)


def _photo(raw: str) -> Path:
    """The picture, checked for the one format ``setMyProfilePhoto`` accepts."""
    path = Path(raw).expanduser()
    if not path.is_file():
        raise RefusedError(f"Refusing --photo {raw!r}: no such file.")
    size = path.stat().st_size
    if size > _MAX_PHOTO_BYTES:
        raise RefusedError(
            f"Refusing --photo {raw!r}: {size} bytes, over Telegram's "
            f"{_MAX_PHOTO_BYTES}-byte upload limit."
        )
    with path.open("rb") as handle:
        if handle.read(len(_JPEG_MAGIC)) != _JPEG_MAGIC:
            raise RefusedError(
                f"Refusing --photo {raw!r}: a profile photo must be a JPEG, and this is "
                f"not one. Convert it first:\n"
                f"  sips -s format jpeg -s formatOptions best {raw} --out {path.stem}.jpg"
            )
    return path


def plan(argv: Sequence[str]) -> Request:
    """What this command line asks for, fully validated — or a :class:`RefusedError`.

    Split from :func:`main` so the deciding half needs no token and no network: every
    refusal below is a judgement about the operator's input alone.
    """
    args = _parse(argv)
    language_code = _language_code(str(args.language_code))
    if args.verb == "show":
        return Show(language_code=language_code)

    change = Change(
        language_code=language_code,
        name=None if args.name is None else _name(str(args.name)),
        description=(
            None
            if args.description is None
            else _text(str(args.description), flag="--description", limit=_MAX_DESCRIPTION)
        ),
        short_description=(
            None
            if args.short_description is None
            else _text(
                str(args.short_description),
                flag="--short-description",
                limit=_MAX_SHORT_DESCRIPTION,
            )
        ),
        photo=None if args.photo is None else _photo(str(args.photo)),
    )
    if not _fields(change):
        raise RefusedError(
            "Refusing a set with nothing to set: name at least one of --name, "
            "--description, --short-description or --photo."
        )
    if change.photo is not None and change.language_code:
        raise RefusedError(
            "Refusing --photo with --language-code: a bot has one picture for every "
            "locale. Run the photo and the text as two commands."
        )
    return change


def _fields(change: Change) -> tuple[str, ...]:
    """Which fields this change names, in the order they will be written."""
    named = ("name", "description", "short_description", "photo")
    return tuple(field for field in named if getattr(change, field) is not None)


async def apply(bot: Bot, request: Request) -> str:
    """Perform the request against Telegram and hand back what to print."""
    if isinstance(request, Show):
        return await _show(bot, request)
    return await _change(bot, request)


async def _show(bot: Bot, request: Show) -> str:
    locale = request.language_code
    me = await bot.get_me()
    name = await bot.get_my_name(language_code=locale)
    description = await bot.get_my_description(language_code=locale)
    short = await bot.get_my_short_description(language_code=locale)
    # The locale is printed even when it is the default, because an empty translation and
    # an empty default look identical in the output and mean different things.
    return "\n".join(
        (
            f"@{me.username} ({me.id}), locale: {locale or 'default'}",
            f"  name:              {name.name!r}",
            f"  short description: {short.short_description!r}",
            f"  description:       {description.description!r}",
            "  photo:             not readable over the Bot API — open the profile to see it",
        )
    )


async def _change(bot: Bot, request: Change) -> str:
    """Write each named field, in order, stopping at the first Telegram refuses.

    There is no transaction to be had here: four setters are four requests, and a failure
    on the third leaves the first two applied. So the report names what LANDED rather than
    what was asked for, and the exception carries the rest — an operator who sees "name,
    description" knows exactly which command to repeat.
    """
    locale = request.language_code
    written: list[str] = []
    try:
        if request.name is not None:
            await bot.set_my_name(name=request.name, language_code=locale)
            written.append("name")
        if request.description is not None:
            await bot.set_my_description(description=request.description, language_code=locale)
            written.append("description")
        if request.short_description is not None:
            await bot.set_my_short_description(
                short_description=request.short_description, language_code=locale
            )
            written.append("short description")
        if request.photo is not None:
            await bot.set_my_profile_photo(
                photo=InputProfilePhotoStatic(photo=FSInputFile(request.photo))
            )
            written.append(f"photo ({request.photo})")
    except Exception as exc:
        raise RefusedError(
            f"Telegram refused: {exc}\nApplied before it did: {', '.join(written) or 'nothing'}."
        ) from exc
    _LOG.info(
        "an operator changed the bot's profile",
        extra={"fields": _fields(request), "language_code": locale or "default"},
    )
    return f"Set for {locale or 'the default locale'}: {', '.join(written)}."


async def _run(request: Request) -> str:
    """Open a session for the one call and close it on every path.

    ``require_vendor_secrets=False``: renaming the bot must not require the ElevenLabs and
    Gemini keys to be present on the box the operator happens to be on.
    """
    settings = build_settings(require_vendor_secrets=False)
    if not settings.telegram_bot_token:
        raise RefusedError("HBD_TELEGRAM_BOT_TOKEN is empty; this tool is the token or nothing.")
    bot = Bot(token=settings.telegram_bot_token)
    try:
        return await apply(bot, request)
    finally:
        await bot.session.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point. Returns an exit code and never raises."""
    configure_logging()
    try:
        request = plan(sys.argv[1:] if argv is None else argv)
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    try:
        print(asyncio.run(_run(request)))
    except RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    except HbdError as exc:
        print(exc.operator_message)
        return EXIT_CONFIG
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
