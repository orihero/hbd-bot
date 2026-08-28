"""Pydantic -> vendor schema. The two dialects differ, and the differences matter."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from hbd.providers.llm.json_schema import to_gemini_schema, to_openai_strict_schema
from hbd.providers.llm.schemas import IntakePayload, KitPlanPayload


class Inner(BaseModel):
    label: str
    weight: float = 1.0


class Outer(BaseModel):
    name: str = Field(description="who it is for")
    items: tuple[Inner, ...] = ()
    flag: bool = False


def walk(node: Any) -> list[dict[str, Any]]:
    """Every *schema node* in the tree — not the ``properties`` maps, whose keys are
    field names rather than schema keywords.
    """
    if not isinstance(node, dict):
        return []
    found = [node]
    for child in node.get("properties", {}).values():
        found.extend(walk(child))
    for key in ("items", "anyOf"):
        value = node.get(key)
        if isinstance(value, list):
            for item in value:
                found.extend(walk(item))
        else:
            found.extend(walk(value))
    return found


# ---------------------------------------------------------------------------
# Shared behaviour
# ---------------------------------------------------------------------------
def test_inlines_nested_model_definitions_so_no_ref_survives() -> None:
    # Arrange / Act
    schema = to_gemini_schema(Outer)

    # Assert
    assert all("$ref" not in node and "$defs" not in node for node in walk(schema))
    assert schema["properties"]["items"]["items"]["properties"]["label"]["type"] == "string"


def test_keeps_field_descriptions_because_they_steer_the_model() -> None:
    schema = to_gemini_schema(Outer)

    assert schema["properties"]["name"]["description"] == "who it is for"


def test_maps_a_tuple_field_to_an_array_of_its_item_type() -> None:
    schema = to_gemini_schema(KitPlanPayload)

    sections = schema["properties"]["sections"]
    assert sections["type"] == "array"
    assert sections["items"]["properties"]["lines"]["type"] == "array"


# ---------------------------------------------------------------------------
# Gemini dialect: an unknown key is a 400, not a warning
# ---------------------------------------------------------------------------
def test_gemini_schema_drops_every_key_outside_the_openapi_subset() -> None:
    allowed = {"type", "properties", "items", "required", "enum", "description", "format", "anyOf"}

    schema = to_gemini_schema(KitPlanPayload)

    assert all(set(node) <= allowed for node in walk(schema))


def test_gemini_schema_never_emits_additional_properties() -> None:
    schema = to_gemini_schema(IntakePayload)

    assert all("additionalProperties" not in node for node in walk(schema))


def test_gemini_schema_drops_a_format_the_vendor_does_not_publish() -> None:
    class WithFormat(BaseModel):
        ratio: float = Field(json_schema_extra={"format": "double"})
        odd: str = Field(json_schema_extra={"format": "uuid"})

    schema = to_gemini_schema(WithFormat)

    assert schema["properties"]["ratio"]["format"] == "double"
    assert "format" not in schema["properties"]["odd"]


# ---------------------------------------------------------------------------
# OpenAI strict dialect: the exact opposite demands
# ---------------------------------------------------------------------------
def test_openai_strict_schema_closes_every_object() -> None:
    schema = to_openai_strict_schema(KitPlanPayload)

    objects = [node for node in walk(schema) if node.get("type") == "object"]
    assert objects
    assert all(node["additionalProperties"] is False for node in objects)


def test_openai_strict_schema_requires_every_property_including_defaulted_ones() -> None:
    # `flag` has a default, so pydantic leaves it out of `required`; strict mode does not
    # allow that, and a missing entry is a hard 400 at request time.
    schema = to_openai_strict_schema(Outer)

    assert set(schema["required"]) == set(schema["properties"])
    assert "flag" in schema["required"]


def test_openai_strict_schema_requires_nested_object_properties_too() -> None:
    schema = to_openai_strict_schema(Outer)

    inner = schema["properties"]["items"]["items"]
    assert set(inner["required"]) == {"label", "weight"}


def test_both_dialects_survive_the_real_response_models() -> None:
    for model in (KitPlanPayload, IntakePayload):
        assert to_gemini_schema(model)["type"] == "object"
        assert to_openai_strict_schema(model)["type"] == "object"
