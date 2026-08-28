"""Pydantic model -> vendor structured-output schema.

Both vendors accept "a JSON schema", and neither accepts the one pydantic emits:

* Gemini's ``responseSchema`` is an OpenAPI 3.0 subset. Unknown keys (``$defs``,
  ``$ref``, ``additionalProperties``, ``title``, ``default``) are a 400, not a warning.
* OpenAI-compatible ``json_schema`` with ``strict: true`` demands the opposite —
  ``additionalProperties: false`` on every object and *every* property listed in
  ``required``.

So one inliner, two thin dialects. This runs on our OWN models, never on vendor data,
but it is still depth-guarded: a self-referential model would otherwise recurse forever.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel

__all__ = ["to_gemini_schema", "to_openai_strict_schema", "MAX_SCHEMA_DEPTH"]

#: Deep enough for any response model in this package, shallow enough to stop a cycle.
MAX_SCHEMA_DEPTH: Final[int] = 12

#: Keys both dialects understand. Everything else is dropped rather than forwarded.
_PORTABLE_KEYS: Final[frozenset[str]] = frozenset(
    {"type", "properties", "items", "required", "enum", "description", "format", "anyOf"}
)

#: ``format`` values Gemini accepts. A pydantic ``float`` emits none, but a constrained
#: field can emit e.g. ``"uuid"``, which Gemini rejects outright.
_GEMINI_FORMATS: Final[frozenset[str]] = frozenset({"int32", "int64", "float", "double"})

_REF_PREFIX: Final[str] = "#/$defs/"


def _resolve_ref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Replace a ``$ref`` node with the definition it points at, keeping siblings."""
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
        return node
    target = defs.get(ref.removeprefix(_REF_PREFIX))
    if not isinstance(target, dict):
        return node
    merged = {key: value for key, value in node.items() if key != "$ref"}
    return {**target, **merged}


def _walk(node: Any, defs: dict[str, Any], *, depth: int, is_strict: bool) -> Any:
    if depth > MAX_SCHEMA_DEPTH or not isinstance(node, dict):
        return {"type": "string"} if depth > MAX_SCHEMA_DEPTH else node

    resolved = _resolve_ref(node, defs)
    out: dict[str, Any] = {}
    for key, value in resolved.items():
        if key not in _PORTABLE_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {
                name: _walk(child, defs, depth=depth + 1, is_strict=is_strict)
                for name, child in value.items()
            }
        elif key in ("items", "anyOf"):
            out[key] = _walk_child(value, defs, depth=depth + 1, is_strict=is_strict)
        else:
            out[key] = value

    if out.get("type") == "object":
        properties = out.get("properties", {})
        if is_strict:
            out["additionalProperties"] = False
            out["required"] = sorted(properties)
        elif "required" in out:
            out["required"] = sorted(out["required"])
    return out


def _walk_child(value: Any, defs: dict[str, Any], *, depth: int, is_strict: bool) -> Any:
    if isinstance(value, list):
        return [_walk(item, defs, depth=depth, is_strict=is_strict) for item in value]
    return _walk(value, defs, depth=depth, is_strict=is_strict)


def _prune_gemini_formats(node: Any) -> Any:
    """Drop ``format`` values Gemini does not publish. Returns a NEW structure."""
    if isinstance(node, list):
        return [_prune_gemini_formats(item) for item in node]
    if not isinstance(node, dict):
        return node
    return {
        key: _prune_gemini_formats(value)
        for key, value in node.items()
        if not (key == "format" and value not in _GEMINI_FORMATS)
    }


def _root(model: type[BaseModel], *, is_strict: bool) -> dict[str, Any]:
    raw = dict(model.model_json_schema(ref_template=f"{_REF_PREFIX}{{model}}"))
    defs_value = raw.pop("$defs", {})
    defs: dict[str, Any] = defs_value if isinstance(defs_value, dict) else {}
    walked = _walk(raw, defs, depth=0, is_strict=is_strict)
    return walked if isinstance(walked, dict) else {"type": "object"}


def to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """OpenAPI-subset schema for ``generationConfig.responseSchema``."""
    return dict(_prune_gemini_formats(_root(model, is_strict=False)))


def to_openai_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Schema for ``response_format.json_schema`` with ``strict: true``."""
    return _root(model, is_strict=True)
