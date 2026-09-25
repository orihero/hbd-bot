"""The media output reveal — IMAGE_VIDEO_SPEC §8 ("Reveal"), §6.7, M5.1.

The song stream's gate and range handling, over a ``media_outputs`` row: a delivered image
streams by range after a step-up scoped to THAT output, one audit row names it as a
``media_output`` subject, and the three things that are never revealable — intermediates,
legal-hold items and bytes already deleted — are 404 whatever grant the operator holds. The
streaming itself is ``Storage.open_range``'s bounded chunks, shared with the song route; the
large-object case is asserted on a multi-chunk object rather than a 200 MB one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa

from bayram.admin.routers.assets import MEDIA_OUTPUT_STREAM_PATH
from bayram.contracts import Language
from bayram.db.enums import (
    AuditAction,
    MediaAspect,
    MediaJobState,
    MediaKind,
    MediaOutputRole,
    MediaSku,
)
from bayram.db.media import create_job
from bayram.db.models.media_input import MediaOutputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.order import OrderRow
from bayram.db.retention import RetentionClass
from bayram.storage import RANGE_CHUNK_BYTES, media_key
from tests.test_admin import test_asset_stream as stream_suite
from tests.test_admin.test_asset_stream import (
    NOW,
    Panel,
    audit_rows,
    seed_order,
    signed_in,
    step_up,
)

#: The song stream's fixtures, reused: the real panel over a temporary archive.
panel = stream_suite.panel

#: More than one ``open_range`` chunk, so the response is genuinely streamed in pieces.
IMAGE_BYTES: Final[bytes] = bytes(range(256)) * ((RANGE_CHUNK_BYTES * 2) // 256 + 3)


def stream_path(output_id: object) -> str:
    return MEDIA_OUTPUT_STREAM_PATH.format(output_id=output_id)


async def seed_output(
    panel: Panel,
    *,
    role: MediaOutputRole = MediaOutputRole.IMAGE,
    retention_class: RetentionClass = RetentionClass.MEDIA_OUTPUT,
    is_deleted: bool = False,
    mime: str = "image/jpeg",
    order: OrderRow | None = None,
) -> UUID:
    if order is None:
        order = await seed_order(panel.container)
    async with panel.container.session_factory.begin() as db:
        job_id = await create_job(
            db,
            user_id=order.user_id,
            telegram_user_id=order.telegram_user_id,
            kind=MediaKind.IMAGE,
            sku=MediaSku.IMAGE,
            state=MediaJobState.SCREENING,
            chat_id=order.telegram_user_id,
            outputs_requested=2,
            aspect=MediaAspect.PORTRAIT,
            language=Language.EN,
            prompt="a courtyard at dusk",
            price_minor=500_000,
            currency="UZS",
            now=NOW,
            quote_ttl=timedelta(hours=24),
        )
        # One account has one open request per kind: each seeded output gets a finished job.
        await db.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(state=MediaJobState.DELIVERED)
        )
        key = media_key(job_id, is_output=True, filename="image-0.jpg")
        output_id = uuid4()
        db.add(
            MediaOutputRow(
                id=output_id,
                job_id=job_id,
                role=role,
                variant=0,
                storage_key=key,
                mime=mime,
                retention_class=retention_class,
                legal_hold_expires_at=(
                    NOW + timedelta(hours=72)
                    if retention_class is RetentionClass.LEGAL_HOLD
                    else None
                ),
                expires_at=NOW + timedelta(days=30),
                deleted_at=NOW if is_deleted else None,
                created_at=NOW,
            )
        )
    target = panel.archive / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(IMAGE_BYTES)
    return output_id


async def test_a_delivered_image_streams_by_range_after_a_scoped_step_up(panel: Panel) -> None:
    # Arrange
    output_id = await seed_output(panel)
    await signed_in(panel)
    assert (await step_up(panel, output_id)).status_code == 200

    # Act
    ranged = await panel.client.get(stream_path(output_id), headers={"Range": "bytes=0-99"})
    whole = await panel.client.get(stream_path(output_id))

    # Assert
    assert ranged.status_code == 206
    assert ranged.headers["content-range"] == f"bytes 0-99/{len(IMAGE_BYTES)}"
    assert ranged.headers["content-type"].startswith("image/jpeg")
    assert ranged.content == IMAGE_BYTES[:100]
    assert whole.status_code == 200 and whole.content == IMAGE_BYTES
    (row,) = await audit_rows(panel.container, AuditAction.ASSET_STREAM)
    assert (row.subject_type, row.subject_id) == ("media_output", str(output_id))


async def test_without_a_step_up_on_this_output_nothing_is_streamed(panel: Panel) -> None:
    output_id = await seed_output(panel)
    await signed_in(panel)
    assert (await step_up(panel, uuid4())).status_code == 200  # a grant for another subject

    response = await panel.client.get(stream_path(output_id))

    assert response.status_code == 403
    assert await audit_rows(panel.container, AuditAction.ASSET_STREAM) == []


async def test_legal_hold_intermediates_and_deleted_bytes_are_never_revealable(
    panel: Panel,
) -> None:
    order = await seed_order(panel.container)
    held = await seed_output(panel, retention_class=RetentionClass.LEGAL_HOLD, order=order)
    intermediate = await seed_output(
        panel, role=MediaOutputRole.NARRATION, mime="audio/ogg", order=order
    )
    gone = await seed_output(panel, is_deleted=True, order=order)
    await signed_in(panel)

    for output_id in (held, intermediate, gone):
        assert (await step_up(panel, output_id)).status_code == 200
        response = await panel.client.get(stream_path(output_id))
        assert response.status_code == 404, output_id
    assert await audit_rows(panel.container, AuditAction.ASSET_STREAM) == []


async def test_a_key_that_is_not_the_one_media_key_spells_is_refused(panel: Panel) -> None:
    output_id = await seed_output(panel)
    async with panel.container.session_factory.begin() as db:
        await db.execute(
            sa.update(MediaOutputRow)
            .where(MediaOutputRow.id == output_id)
            .values(storage_key="orders/elsewhere/image-0.jpg")
        )
    await signed_in(panel)
    assert (await step_up(panel, output_id)).status_code == 200

    response = await panel.client.get(stream_path(output_id))

    assert response.status_code == 404
