"""The CSAM legal hold's bytes: sealed to the escalation owner (IMAGE_VIDEO_SPEC §6.7).

On a CSAM-class block the job's inputs and outputs are put under ``legal_hold`` **in the same
transaction as the block verdict** (``db.media.place_legal_hold``, called by the stage chain),
so ``media_cleanup``, ``/forget`` and both ordinary purge predicates skip them; the legal-hold
purge arm deletes them at ``legal_hold_expires_at`` (≤ 72 h) unless the escalation owner
decided otherwise. This module does the other half: **the held bytes are encrypted at rest
with a key only the escalation owner holds.**

The scheme is a sealed box built from standard primitives: an ephemeral X25519 key agreement
with the owner's public key (``media_legal_hold_recipient``), HKDF-SHA256 to a 256-bit key,
AES-256-GCM with the header as associated data. This host holds the PUBLIC key only — it can
seal and can never open. The owner opens a sealed object out of band with
``python -m bayram.tools.legal_hold open`` and the private key that never leaves them.

Each object is sealed **in place** (same storage key), so the held rows keep pointing at it;
the rows keep the ``sha256`` of the ORIGINAL bytes, which is what a report to the authorities
quotes. :func:`is_sealed` makes :func:`seal_held_objects` idempotent: the stage calls it right
after the hold commits and ``media_cleanup`` calls it again, so a worker killed in between
leaves nothing in the clear for longer than the next cleanup.

The admin panel never reveals held bytes (§6.7): it sees job id, category codes, sha256 and
time. Nothing here logs content.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Result, Storage, err, is_err, ok
from bayram.db.models.media_input import MediaInputRow, MediaOutputRow
from bayram.db.retention import RetentionClass
from bayram.errors import ValidationError
from bayram.logging import get_logger

__all__ = [
    "SEALED_MAGIC",
    "SEALED_CONTENT_TYPE",
    "SealReport",
    "generate_keypair",
    "parse_public_key",
    "seal",
    "open_sealed",
    "is_sealed",
    "seal_held_objects",
]

_LOG = get_logger(__name__)

#: Every sealed object starts with this; it is also the AEAD's associated data.
SEALED_MAGIC: Final[bytes] = b"BAYRAM-LEGAL-HOLD-1\n"
SEALED_CONTENT_TYPE: Final[str] = "application/octet-stream"
_KEY_BYTES: Final[int] = 32
_NONCE_BYTES: Final[int] = 12
_HKDF_INFO: Final[bytes] = b"bayram media legal hold v1"


def _raw(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def generate_keypair() -> tuple[str, str]:
    """``(private_b64, public_b64)`` for the escalation owner. Run on THEIR machine."""
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return (
        base64.b64encode(private_raw).decode("ascii"),
        base64.b64encode(_raw(private.public_key())).decode("ascii"),
    )


def parse_public_key(value: str) -> X25519PublicKey | None:
    """The configured public key, or ``None`` when it is not 32 base64 bytes."""
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) != _KEY_BYTES:
        return None
    return X25519PublicKey.from_public_bytes(raw)


def _derive(shared: bytes, ephemeral: bytes, recipient: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=ephemeral + recipient,
        info=_HKDF_INFO,
    ).derive(shared)


def seal(data: bytes, recipient: X25519PublicKey) -> bytes:
    """``MAGIC ‖ ephemeral public (32) ‖ nonce (12) ‖ AES-GCM(data)``."""
    ephemeral = X25519PrivateKey.generate()
    ephemeral_raw = _raw(ephemeral.public_key())
    key = _derive(ephemeral.exchange(recipient), ephemeral_raw, _raw(recipient))
    nonce = os.urandom(_NONCE_BYTES)
    return SEALED_MAGIC + ephemeral_raw + nonce + AESGCM(key).encrypt(nonce, data, SEALED_MAGIC)


def is_sealed(blob: bytes) -> bool:
    return blob.startswith(SEALED_MAGIC)


def open_sealed(blob: bytes, private_b64: str) -> Result[bytes]:
    """The escalation owner's side. Never called on the host."""
    try:
        private = X25519PrivateKey.from_private_bytes(base64.b64decode(private_b64.strip()))
    except (binascii.Error, ValueError) as exc:
        return err(ValidationError("the private key is not 32 base64 bytes", cause=exc))
    head = len(SEALED_MAGIC)
    if not is_sealed(blob) or len(blob) < head + _KEY_BYTES + _NONCE_BYTES:
        return err(ValidationError("not a sealed legal-hold object"))
    ephemeral_raw = blob[head : head + _KEY_BYTES]
    nonce = blob[head + _KEY_BYTES : head + _KEY_BYTES + _NONCE_BYTES]
    body = blob[head + _KEY_BYTES + _NONCE_BYTES :]
    ephemeral = X25519PublicKey.from_public_bytes(ephemeral_raw)
    key = _derive(private.exchange(ephemeral), ephemeral_raw, _raw(private.public_key()))
    try:
        return ok(AESGCM(key).decrypt(nonce, body, SEALED_MAGIC))
    except InvalidTag as exc:
        return err(ValidationError("wrong key, or the object was altered", cause=exc))


@dataclass(frozen=True, slots=True)
class SealReport:
    sealed: int
    already: int
    failed: int
    #: No usable public key: the objects stay as they are (boot refuses this with media
    #: offered, so only a development deployment can get here).
    keyless: bool = False


async def seal_held_objects(
    sessions: async_sessionmaker[AsyncSession],
    storage: Storage,
    job_id: UUID,
    *,
    public_key: str,
) -> SealReport:
    """Seal every held object of ``job_id`` in place. Idempotent; never raises on one object."""
    async with sessions() as session:
        keys: list[str] = []
        for model in (MediaInputRow, MediaOutputRow):
            rows = await session.execute(
                sa.select(model.storage_key).where(
                    model.job_id == job_id,
                    model.retention_class == RetentionClass.LEGAL_HOLD,
                    model.storage_key.is_not(None),
                )
            )
            keys.extend(key for (key,) in rows.all() if key)
    if not keys:
        return SealReport(sealed=0, already=0, failed=0)
    recipient = parse_public_key(public_key) if public_key.strip() else None
    if recipient is None:
        _LOG.error(
            "legal-hold bytes could not be sealed: no usable escalation-owner public key",
            extra={"media_job_id": str(job_id), "objects": len(keys)},
        )
        return SealReport(sealed=0, already=0, failed=len(keys), keyless=True)
    sealed = already = failed = 0
    for key in keys:
        found = await storage.get(key)
        if is_err(found):
            failed += 1
            continue
        if is_sealed(found.value):
            already += 1
            continue
        stored = await storage.put(
            key, seal(found.value, recipient), content_type=SEALED_CONTENT_TYPE
        )
        if is_err(stored):
            failed += 1
            continue
        sealed += 1
    if failed:
        _LOG.error(
            "some legal-hold objects could not be sealed",
            extra={"media_job_id": str(job_id), "failed": failed},
        )
    return SealReport(sealed=sealed, already=already, failed=failed)
