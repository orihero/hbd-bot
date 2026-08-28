"""Prompt loading and rendering. No prompt text lives in Python in this package.

Templates are plain UTF-8 files in ``prompts/`` and use ``{{placeholder}}`` rather than
``str.format``: the prompts talk about JSON, and ``{`` is not an escape problem we want
to have. Rendering is a literal substitution — a missing placeholder is a ``ConfigError``
at call time, not a silently half-rendered prompt shipped to a paid model.
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files
from typing import Final

from hbd.contracts import Language
from hbd.errors import ConfigError

__all__ = ["load_prompt", "render_prompt", "language_guide", "PROMPTS_PACKAGE"]

PROMPTS_PACKAGE: Final[str] = "hbd.providers.llm.prompts"

_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")

_LANGUAGE_PROMPTS: Final[dict[Language, str]] = {
    Language.UZ_LATN: "lang_uz_latn",
    Language.UZ_CYRL: "lang_uz_cyrl",
    Language.RU: "lang_ru",
    Language.EN: "lang_en",
}


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """Read ``prompts/<name>.txt``. Cached: templates never change at runtime."""
    try:
        return (files(PROMPTS_PACKAGE) / f"{name}.txt").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, ModuleNotFoundError) as exc:
        raise ConfigError(
            f"prompt template {name!r} is missing from {PROMPTS_PACKAGE}",
            context={"prompt": name},
            cause=exc,
        ) from exc


def language_guide(language: Language) -> str:
    """The per-language orthography and register block injected into every system prompt."""
    return load_prompt(_LANGUAGE_PROMPTS[language])


def render_prompt(name: str, values: dict[str, str]) -> str:
    """Substitute every ``{{key}}``. Raises ``ConfigError`` if the template wants a key
    that was not supplied — a half-rendered prompt is a defect, not a degraded mode.
    """
    template = load_prompt(name)
    missing = sorted({key for key in _PLACEHOLDER.findall(template) if key not in values})
    if missing:
        raise ConfigError(
            f"prompt template {name!r} needs placeholders that were not supplied: {missing}",
            context={"prompt": name, "missing": missing},
        )
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
