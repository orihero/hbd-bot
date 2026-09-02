"""The one secret on ``AdminSettings`` is a ``SecretStr``, not a bare string.

§12.4 lists ``admin_audit_hmac_key`` under "never logged", and before this pass the only
thing enforcing that was that nobody had written the offending line yet: ``repr(settings)``,
``model_dump()`` and ``model_dump_json()`` all emitted it verbatim. ``hbd.logging.redact``
masks it only when the field NAME is passed alongside the value, and a settings repr is
exactly a bare value. A boot diagnostic, an unhandled-exception frame dump, or the config
editor arriving in slice 1c would each have printed the one thing standing between an
attacker with table write access and a forged chain.
"""

from __future__ import annotations

from tests.test_admin.conftest import HMAC_KEY, make_settings


def test_the_audit_hmac_key_is_not_rendered_by_a_repr_or_a_dump() -> None:
    # Arrange
    settings = make_settings()

    # Act
    rendered = (
        repr(settings),
        str(settings),
        str(settings.model_dump()),
        settings.model_dump_json(),
    )

    # Assert — the key is the one thing standing between an attacker with table write
    # access and a forged chain (§12.4).
    for text in rendered:
        assert HMAC_KEY not in text


def test_the_key_is_still_readable_where_it_is_actually_used() -> None:
    # Arrange / Act
    settings = make_settings()

    # Assert — hiding it from a repr must not hide it from ``verify_chain``.
    assert settings.admin_audit_hmac_key.get_secret_value() == HMAC_KEY
