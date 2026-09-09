"""The campaign wire — what an operator may compose, and what the panel is allowed to see.

Three properties are asserted here and nowhere else, because no other layer can see them.

* **A body that reaches the database is a body Telegram will accept.** The send is the one
  action in this API that cannot be corrected one record at a time: an unclosed ``<b>`` is a
  ``TelegramBadRequest`` for every recipient identically. So every refusal is tested at the
  model, where it is a 422, rather than left to be discovered forty thousand times.
* **The length that matters is the RENDERED one.** A body of ampersands fits the column and
  overruns Telegram fivefold, so the two bounds are asserted separately and against each
  other — a test that only checked ``len(text)`` would pass on exactly the campaign that dies.
* **No recipient row puts a raw Telegram id on the wire.** ``/users`` publishes the id beside
  its mask by design; this surface must not, and the assertion is made against the SERIALISED
  bytes rather than against the field list, because "the model has no such field" is a
  weaker claim than "the digits are not in the response".

The markup rules are exercised through :class:`BroadcastBodyInput` rather than through
:func:`render_body_html` alone wherever the refusal is the point, so what is tested is what a
request actually meets.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from hbd.admin.schemas.broadcasts import (
    MAX_BODIES,
    TELEGRAM_TAGS,
    BroadcastBodyInput,
    BroadcastCreateRequest,
    BroadcastReviseRequest,
    BroadcastSendRequest,
    render_body_html,
    to_body_view,
    to_broadcast_detail_view,
    to_broadcast_view,
    to_recipient_view,
)
from hbd.contracts import BroadcastKind, BroadcastRecipientState, BroadcastState, Language
from hbd.db.admin.broadcasts import broadcast_body_view
from hbd.db.admin.views import BroadcastBodyView as BroadcastBodyRecord
from hbd.db.admin.views import (
    BroadcastDetail,
    BroadcastListItem,
    BroadcastProgress,
    BroadcastRecipientItem,
)
from hbd.db.enums import AuditReasonCode
from hbd.db.models.broadcast import BROADCAST_TITLE_LENGTH
from hbd.db.models.broadcast_body import (
    BROADCAST_BODY_LENGTH,
    BROADCAST_CAPTION_LENGTH,
    BroadcastBodyRow,
)

#: One clock for the whole file. Nothing under test reads a wall clock — the "is this instant
#: in the past" question belongs to the handler — so this is the only "now" anything needs.
_NOW: Final[datetime] = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)

#: A Telegram id whose digits are searched for in serialised output. Distinctive enough that
#: a substring hit is a leak and not a coincidence.
_TELEGRAM_USER_ID: Final[int] = 987654321

#: An object-store key of the shape the panel's uploader writes.
_MEDIA_KEY: Final[str] = "broadcasts/2026/09/poster.jpg"

#: A file id only Telegram can mint. Planted on a row so the assertion that it never reaches
#: the wire is made against bytes rather than against a field list.
_FILE_ID: Final[str] = "AgACAgIAAxkBAAIEXAAB-worker-minted-handle"

#: The smallest legal segment document, so a create request can be built without restating
#: the segment schema's own tests.
_SEGMENT: Final[dict[str, Any]] = {"v": 1, "match": "all", "rules": []}


def _body(**overrides: object) -> dict[str, object]:
    """A legal body, by wire name, with anything a test wants replaced."""
    payload: dict[str, object] = {"language": "ru", "text": "Salom!"}
    payload.update(overrides)
    return payload


def _refusal(model: type[Any], payload: dict[str, object]) -> str:
    """Validate something expected to be refused, and hand back the first message.

    The message never reaches a client — ``errors._handle_validation`` publishes field
    locations only — so it is asserted here, where it is the one place a rule can be told
    apart from its neighbour.
    """
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)
    return caught.value.errors()[0]["msg"]


_BROADCAST_ID: Final[UUID] = UUID("11111111-1111-1111-1111-111111111111")


def _item(**overrides: object) -> BroadcastListItem:
    """A campaign as the READ LAYER hands it over, with every field set.

    The projections take :mod:`hbd.db.admin.views` dataclasses and not ORM rows — the
    convention every other list in this package follows — so this is the value a handler
    actually has. Nothing is left out, because a field omitted here is a field the projection
    under test would read as ``None`` for a column the database never leaves null.
    """
    values: dict[str, object] = {
        "id": _BROADCAST_ID,
        "title": "September outage notice",
        "kind": BroadcastKind.SERVICE,
        "state": BroadcastState.SENDING,
        "segment_hash": "a" * 64,
        "audience_size": 100,
        "audience_evaluated_at": _NOW,
        "recipient_count": 100,
        "sent_count": 90,
        "failed_count": 3,
        "skipped_count": 2,
        "undeliverable_count": 1,
        "unknown_count": 1,
        "scheduled_for": None,
        "started_at": _NOW,
        "finished_at": None,
        "created_by_admin_id": UUID("22222222-2222-2222-2222-222222222222"),
        "created_by_username": "operator",
        "scheduled_by_admin_id": None,
        "scheduled_by_username": None,
        "reason_code": AuditReasonCode.ROUTINE_OPS,
        "reason_ref": "OPS-14",
        "error_code": None,
        "body_count": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return BroadcastListItem(**values)  # type: ignore[arg-type]


def _body_row(**overrides: object) -> BroadcastBodyRow:
    """The ORM row, for the tests that need the column the read layer drops."""
    values: dict[str, object] = {
        "id": uuid4(),
        "broadcast_id": _BROADCAST_ID,
        "language": Language.RU,
        "text": "Tom & Jerry <b>tonight</b>",
        "media_storage_key": None,
        "media_file_id": None,
        "button_label": None,
        "button_url": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return BroadcastBodyRow(**values)


def _body_record(**overrides: object) -> BroadcastBodyRecord:
    """One body as the read layer publishes it — through the real projection, not by hand."""
    return broadcast_body_view(_body_row(**overrides))


def _recipient_item(**overrides: object) -> BroadcastRecipientItem:
    values: dict[str, object] = {
        "id": UUID("33333333-3333-3333-3333-333333333333"),
        "broadcast_id": _BROADCAST_ID,
        "telegram_user_id": _TELEGRAM_USER_ID,
        "language": Language.RU,
        "state": BroadcastRecipientState.SENT,
        "attempts": 1,
        "error_code": None,
        "settled_at": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return BroadcastRecipientItem(**values)  # type: ignore[arg-type]


def _detail(
    *,
    segment: dict[str, Any] | None = None,
    bodies: tuple[BroadcastBodyRecord, ...] = (),
    progress: BroadcastProgress | None = None,
    **overrides: object,
) -> BroadcastDetail:
    """A campaign detail exactly as :func:`~hbd.db.admin.broadcasts.get_broadcast` assembles it."""
    return BroadcastDetail(
        broadcast=_item(**overrides),
        bodies=bodies,
        segment=_SEGMENT if segment is None else segment,
        progress=progress
        or BroadcastProgress(
            pending=3,
            sending=0,
            sent=90,
            failed=3,
            skipped_blocked=2,
            undeliverable=1,
            unknown=1,
        ),
    )


def _wire(model: Any) -> str:
    """A response model as the bytes a browser receives. Assertions about absence read this."""
    return json.dumps(model.model_dump(mode="json", by_alias=True))


# ---------------------------------------------------------------------------
# rendering: what the sender will actually hand Telegram
# ---------------------------------------------------------------------------
def test_literal_text_is_escaped_and_markup_is_not() -> None:
    rendered = render_body_html('Tom & Jerry <b>5 < 6</b> <a href="https://example.com/x">go</a>')

    assert rendered == ('Tom &amp; Jerry <b>5 &lt; 6</b> <a href="https://example.com/x">go</a>')


def test_rendering_is_idempotent_on_its_own_output() -> None:
    """``&`` and ``&amp;`` are one message, so the measured length cannot depend on which
    spelling an operator typed."""
    once = render_body_html("Tom & Jerry")
    assert once == "Tom &amp; Jerry"
    assert render_body_html(once) == once


@pytest.mark.parametrize("tag", sorted(TELEGRAM_TAGS - {"a"}))
def test_every_allowlisted_tag_survives_rendering(tag: str) -> None:
    assert render_body_html(f"<{tag}>x</{tag}>") == f"<{tag}>x</{tag}>"


def test_an_uppercase_tag_is_canonicalised_and_the_words_are_not() -> None:
    """Markup is a parse, so its case is ours; the text between the tags is the operator's."""
    assert render_body_html("<B>Salom</B>") == "<b>Salom</b>"


def test_a_bare_less_than_is_text_and_needs_no_escaping_by_the_operator() -> None:
    assert render_body_html("5 < 6 and 7 > 6") == "5 &lt; 6 and 7 &gt; 6"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Salom <b", id="an-unterminated-open-tag"),
        pytest.param("Salom</b", id="an-unterminated-close-tag"),
        pytest.param('Salom <a href="https://example.com/"', id="an-unterminated-attribute"),
    ],
)
def test_an_unterminated_tag_is_refused_because_the_parser_would_eat_the_tail(text: str) -> None:
    """``HTMLParser`` discards an unterminated tag AND everything after it, so accepting one
    would delete the end of a message with nothing on the screen to say so."""
    assert _refusal(BroadcastBodyInput, _body(text=text)) == (
        "Value error, an HTML tag is missing its closing '>'"
    )


# ---------------------------------------------------------------------------
# the markup allowlist
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        pytest.param("<script>alert(1)</script>", id="script"),
        pytest.param("<img src='x'>", id="img"),
        pytest.param("<div>x</div>", id="div"),
        pytest.param("<marquee>x</marquee>", id="marquee"),
        pytest.param('<span class="tg-spoiler">x</span>', id="span-spoiler"),
        pytest.param('<tg-emoji emoji-id="5368324">x</tg-emoji>', id="tg-emoji"),
    ],
)
def test_a_tag_telegram_does_not_take_is_refused_rather_than_stripped(text: str) -> None:
    assert _refusal(BroadcastBodyInput, _body(text=text)) == (
        "Value error, the text uses an HTML tag Telegram does not accept"
    )


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("<b foo='bar'>x</b>", id="an-attribute-on-bold"),
        pytest.param('<pre class="language-python">x</pre>', id="a-language-on-pre"),
        pytest.param("<blockquote expandable>x</blockquote>", id="expandable-blockquote"),
        pytest.param('<a href="https://example.com/" rel="nofollow">x</a>', id="a-second-attr"),
        pytest.param("<a>x</a>", id="an-anchor-with-no-href"),
    ],
)
def test_an_attribute_outside_the_allowlist_is_refused(text: str) -> None:
    assert _refusal(BroadcastBodyInput, _body(text=text)) == (
        "Value error, an HTML tag carries an attribute that is not allowed"
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            "<b>x", "an HTML tag is not closed, or closes one that was never opened", id="unclosed"
        ),
        pytest.param(
            "x</b>",
            "an HTML tag is not closed, or closes one that was never opened",
            id="a-stray-close",
        ),
        pytest.param(
            "<b><i>x</b></i>",
            "an HTML tag is not closed, or closes one that was never opened",
            id="crossed-spans",
        ),
        pytest.param("<b/>x", "a self-closing HTML tag is not Telegram markup", id="self-closing"),
        pytest.param(
            "<!-- hidden -->x",
            "the text contains a comment or declaration, which is not markup",
            id="a-comment",
        ),
        pytest.param(
            "<!DOCTYPE html>x",
            "the text contains a comment or declaration, which is not markup",
            id="a-doctype",
        ),
        pytest.param(
            "<?php echo 1; ?>x",
            "the text contains a comment or declaration, which is not markup",
            id="a-processing-instruction",
        ),
    ],
)
def test_markup_that_telegram_would_reject_at_send_time_is_refused_at_compose(
    text: str, message: str
) -> None:
    assert _refusal(BroadcastBodyInput, _body(text=text)) == f"Value error, {message}"


def test_a_link_inside_a_link_is_refused() -> None:
    text = '<a href="https://a.example/"><a href="https://b.example/">x</a></a>'

    assert _refusal(BroadcastBodyInput, _body(text=text)) == (
        "Value error, a link may not contain another link"
    )


@pytest.mark.parametrize(
    "href",
    [
        pytest.param("/relative", id="relative"),
        pytest.param("javascript:alert(1)", id="javascript"),
        pytest.param("tg://resolve?domain=x", id="tg-scheme"),
        pytest.param("https://localhost/x", id="no-dot-in-the-host"),
        pytest.param("https://user:pw@example.com/", id="userinfo"),
    ],
)
def test_a_link_href_must_be_an_absolute_public_http_url(href: str) -> None:
    assert _refusal(BroadcastBodyInput, _body(text=f'<a href="{href}">x</a>')) == (
        "Value error, a link's href is not an absolute http(s) URL"
    )


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("   \n  ", id="whitespace"),
        pytest.param("<b></b>", id="markup-with-no-words"),
    ],
)
def test_a_body_with_no_words_is_refused(text: str) -> None:
    """A blank message is a ``TelegramBadRequest`` for everybody, and a message an operator
    cannot have meant to send."""
    assert _refusal(BroadcastBodyInput, _body(text=text)) == (
        "Value error, the message has no text once its markup is parsed away"
    )


# ---------------------------------------------------------------------------
# length, measured where it counts
# ---------------------------------------------------------------------------
def test_a_body_that_fits_the_column_and_not_telegram_is_refused() -> None:
    """The whole argument for measuring the rendered form: 2 000 ampersands are 2 000
    characters in the editor, 10 000 on the wire, and a dead campaign."""
    text = "&" * 2_000

    assert len(text) <= BROADCAST_BODY_LENGTH
    assert len(render_body_html(text)) > BROADCAST_BODY_LENGTH
    assert _refusal(BroadcastBodyInput, _body(text=text)) == (
        "Value error, the message is longer than Telegram accepts"
    )


def test_a_plain_body_at_the_message_ceiling_is_accepted() -> None:
    """The bound is a ceiling, not a fence one character inside it."""
    body = BroadcastBodyInput.model_validate(_body(text="x" * BROADCAST_BODY_LENGTH))

    assert len(render_body_html(body.text)) == BROADCAST_BODY_LENGTH


def test_a_body_with_media_is_held_to_the_caption_ceiling() -> None:
    """``ck_broadcast_bodies_caption_length`` restated where it is still a 422 — the database
    would otherwise refuse the same pair with an IntegrityError mid-transaction."""
    at_the_ceiling = _body(text="x" * BROADCAST_CAPTION_LENGTH, mediaStorageKey=_MEDIA_KEY)
    over_it = _body(text="x" * (BROADCAST_CAPTION_LENGTH + 1), mediaStorageKey=_MEDIA_KEY)

    assert BroadcastBodyInput.model_validate(at_the_ceiling).media_storage_key == _MEDIA_KEY
    assert _refusal(BroadcastBodyInput, over_it) == (
        "Value error, the message is longer than Telegram accepts"
    )


def test_a_caption_within_the_column_can_still_overrun_telegram() -> None:
    """One ampersand inside a caption at the ceiling is four characters Telegram counts and
    the column does not."""
    text = "&" + "x" * (BROADCAST_CAPTION_LENGTH - 1)

    assert len(text) == BROADCAST_CAPTION_LENGTH
    assert _refusal(BroadcastBodyInput, _body(text=text, mediaStorageKey=_MEDIA_KEY)) == (
        "Value error, the message is longer than Telegram accepts"
    )


def test_a_body_over_the_column_width_is_refused_before_anything_renders_it() -> None:
    assert "at most" in _refusal(BroadcastBodyInput, _body(text="x" * (BROADCAST_BODY_LENGTH + 1)))


# ---------------------------------------------------------------------------
# the stored text is the typed text
# ---------------------------------------------------------------------------
def test_the_text_is_stored_byte_for_byte_as_it_was_typed() -> None:
    """Validation reads and never rewrites: the copy an auditor reads a year from now is the
    copy the operator approved, and the rendering is recomputed at send time."""
    text = "  Tom &amp; Jerry  <b>bold</b>\n"

    assert BroadcastBodyInput.model_validate(_body(text=text)).text == text


# ---------------------------------------------------------------------------
# the button
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://example.com/promo?a=1#top", id="https-with-query"),
        pytest.param("http://example.com/", id="http"),
        pytest.param("https://t.me/hbd_bot", id="a-telegram-link"),
    ],
)
def test_a_real_absolute_url_is_accepted(url: str) -> None:
    body = BroadcastBodyInput.model_validate(_body(buttonLabel="Open", buttonUrl=url))

    assert body.button_url == url


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("example.com", id="no-scheme"),
        pytest.param("/promo", id="relative"),
        pytest.param("javascript:alert(1)", id="javascript"),
        pytest.param("tg://resolve?domain=x", id="tg-scheme"),
        pytest.param("https://", id="no-host"),
        pytest.param("https://localhost/", id="no-dot-in-the-host"),
        pytest.param("https://user:pw@example.com/", id="userinfo"),
        pytest.param("https://exa mple.com/", id="a-space"),
        pytest.param("https://example.com/\nx", id="a-newline"),
    ],
)
def test_a_button_url_that_is_not_an_absolute_http_url_is_refused(url: str) -> None:
    assert _refusal(BroadcastBodyInput, _body(buttonLabel="Open", buttonUrl=url)) == (
        "Value error, the button URL is not an absolute http(s) URL"
    )


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"buttonLabel": "Open"}, id="a-label-with-no-url"),
        pytest.param({"buttonUrl": "https://example.com/"}, id="a-url-with-no-label"),
    ],
)
def test_a_half_written_button_is_refused(payload: dict[str, object]) -> None:
    assert _refusal(BroadcastBodyInput, _body(**payload)) == (
        "Value error, a button needs both a label and a URL, or neither"
    )


# ---------------------------------------------------------------------------
# media
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "key",
    [
        pytest.param("../../etc/passwd", id="traversal"),
        pytest.param("/absolute/key.jpg", id="absolute"),
        pytest.param("broadcasts/../secrets.jpg", id="traversal-mid-path"),
        pytest.param("broadcasts/poster .jpg", id="a-space"),
        pytest.param("broadcasts//poster.jpg", id="an-empty-segment"),
    ],
)
def test_a_media_key_that_is_not_a_storage_key_is_refused(key: str) -> None:
    assert _refusal(BroadcastBodyInput, _body(mediaStorageKey=key)) == (
        "Value error, the media key is not a storage key this deployment wrote"
    )


def test_a_media_file_id_cannot_be_supplied_on_the_wire() -> None:
    """It is minted by Telegram and written by the worker. A client that could send one could
    address a file this deployment never uploaded."""
    assert "extra" in _refusal(BroadcastBodyInput, _body(mediaFileId=_FILE_ID)).lower()


# ---------------------------------------------------------------------------
# the create / revise envelopes
# ---------------------------------------------------------------------------
def _create(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "September outage notice",
        "kind": "service",
        "segment": _SEGMENT,
        "bodies": [_body()],
    }
    payload.update(overrides)
    return payload


def test_a_create_request_carries_the_frozen_audience_s_safety_catch() -> None:
    request = BroadcastCreateRequest.model_validate(_create(expectedAudienceSize=1_200))

    assert request.kind is BroadcastKind.SERVICE
    assert request.expected_audience_size == 1_200
    assert request.segment.v == 1
    assert len(request.bodies) == 1


def test_a_create_request_without_an_expected_size_is_legal() -> None:
    """The wizard renders a preview; a script does not, and must not have to invent a number."""
    assert BroadcastCreateRequest.model_validate(_create()).expected_audience_size is None


def _composed(model: type[Any], bodies: list[dict[str, object]]) -> dict[str, object]:
    """The envelope each of the two composing requests takes, with the same set of bodies.

    Create carries the audience and revise deliberately does not, so a shared payload would
    fail on a missing ``segment`` before it ever reached the rule under test.
    """
    if model is BroadcastReviseRequest:
        return {"title": "September outage notice", "bodies": bodies}
    return _create(bodies=bodies)


@pytest.mark.parametrize("model", [BroadcastCreateRequest, BroadcastReviseRequest])
def test_two_bodies_in_one_language_are_refused(model: type[Any]) -> None:
    """``uq_broadcast_bodies_broadcast_id_language``, restated where it is still a 422."""
    payload = _composed(model, [_body(), _body(text="Snova")])

    assert _refusal(model, payload) == "Value error, two bodies claim the same language"


@pytest.mark.parametrize("model", [BroadcastCreateRequest, BroadcastReviseRequest])
def test_a_campaign_with_no_body_is_refused(model: type[Any]) -> None:
    payload = _composed(model, [])

    assert _refusal(model, payload) == "Value error, a campaign needs at least one body"


def test_more_bodies_than_there_are_languages_is_refused() -> None:
    bodies = [_body(language=language.value) for language in Language]
    bodies.append(_body(language=Language.RU.value, text="again"))

    assert len(bodies) == MAX_BODIES + 1
    assert _refusal(BroadcastCreateRequest, _create(bodies=bodies)) == (
        "Value error, a campaign has at most one body per language"
    )


def test_one_body_per_language_is_accepted() -> None:
    bodies = [_body(language=language.value) for language in Language]

    assert len(BroadcastCreateRequest.model_validate(_create(bodies=bodies)).bodies) == MAX_BODIES


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        pytest.param("   ", "Value error, a campaign needs a title", id="whitespace"),
        pytest.param("x" * (BROADCAST_TITLE_LENGTH + 1), "at most", id="over-the-column"),
    ],
)
def test_a_title_that_says_nothing_or_will_not_fit_is_refused(title: str, expected: str) -> None:
    assert expected in _refusal(BroadcastCreateRequest, _create(title=title))


def test_a_revise_request_cannot_re_point_a_frozen_audience() -> None:
    """The recipient rows exist from creation. A new segment here would describe an audience
    nobody is going to receive this, so the field does not exist and ``extra="forbid"`` says
    so rather than accepting it and ignoring it."""
    payload: dict[str, object] = {"title": "Revised", "bodies": [_body()], "segment": _SEGMENT}

    assert "extra" in _refusal(BroadcastReviseRequest, payload).lower()


# ---------------------------------------------------------------------------
# the send envelope
# ---------------------------------------------------------------------------
def _send(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"reasonCode": AuditReasonCode.ROUTINE_OPS.value}
    payload.update(overrides)
    return payload


def test_sending_now_is_the_absence_of_an_instant() -> None:
    request = BroadcastSendRequest.model_validate(_send(reasonRef="OPS-14"))

    assert request.scheduled_for is None
    assert request.reason_code is AuditReasonCode.ROUTINE_OPS


def test_a_scheduled_instant_must_carry_a_utc_offset() -> None:
    """One spelling of this rule for the whole panel — ``admin.window.require_aware``'s."""
    assert _refusal(BroadcastSendRequest, _send(scheduledFor="2026-09-10T09:00:00")) == (
        "Value error, scheduledFor must carry a UTC offset, e.g. 2026-08-30T12:00:00Z"
    )


def test_an_aware_instant_is_accepted_whether_or_not_it_has_passed() -> None:
    """Whether an instant is in the future is a question about a clock, and no schema in this
    package reads one: the handler refuses the past against the ``now`` it stamps the row with."""
    past = BroadcastSendRequest.model_validate(_send(scheduledFor="2020-01-01T00:00:00Z"))

    assert past.scheduled_for == datetime(2020, 1, 1, tzinfo=UTC)


def test_a_send_without_a_reason_is_refused() -> None:
    """Inherited from ``ReasonedRequest``, asserted here because a subclass could lose it."""
    assert _refusal(BroadcastSendRequest, {}) != ""


# ---------------------------------------------------------------------------
# projections
# ---------------------------------------------------------------------------
def test_the_recipient_projection_never_puts_a_raw_telegram_id_on_the_wire() -> None:
    view = to_recipient_view(_recipient_item())

    rendered = _wire(view)
    assert str(_TELEGRAM_USER_ID) not in rendered
    # The quotes matter: ``telegramUserId`` is a prefix of the masked field's own name, and an
    # unquoted substring check would pass on a response that carried both.
    assert '"telegramUserId"' not in rendered
    assert view.telegram_user_id_masked == "•••••321"
    assert view.is_erased is False


def test_an_erased_recipient_is_a_state_and_not_a_mask() -> None:
    """``/forget`` nulls the column; the row survives as evidence a message was sent."""
    view = to_recipient_view(_recipient_item(telegram_user_id=None))

    assert view.telegram_user_id_masked is None
    assert view.is_erased is True


def test_a_recipient_row_reports_its_own_settlement() -> None:
    view = to_recipient_view(
        _recipient_item(
            state=BroadcastRecipientState.SKIPPED_BLOCKED, attempts=0, error_code="blocked"
        )
    )

    assert view.state is BroadcastRecipientState.SKIPPED_BLOCKED
    assert view.settled_at == _NOW
    assert view.error_code == "blocked"


def test_the_progress_view_is_arithmetic_over_the_row_s_own_counters() -> None:
    view = to_broadcast_view(_item())

    progress = view.progress
    assert progress.settled_count == 90 + 3 + 2 + 1 + 1
    assert progress.unsettled_count == 3
    assert progress.is_audience_complete is True
    assert view.is_terminal is False


def test_a_half_expanded_campaign_is_visible_as_one() -> None:
    """``audienceSize`` and ``recipientCount`` are two numbers precisely so this state cannot
    hide behind one that looks right."""
    progress = to_broadcast_view(
        _item(
            state=BroadcastState.EXPANDING,
            recipient_count=40,
            sent_count=0,
            failed_count=0,
            skipped_count=0,
            undeliverable_count=0,
            unknown_count=0,
        )
    ).progress

    assert progress.audience_size == 100
    assert progress.recipient_count == 40
    assert progress.is_audience_complete is False
    assert progress.unsettled_count == 40


def test_a_finished_campaign_reports_itself_terminal() -> None:
    view = to_broadcast_view(_item(state=BroadcastState.COMPLETED, finished_at=_NOW))

    assert view.is_terminal is True


def test_the_body_projection_publishes_the_rendered_message_and_never_the_file_id() -> None:
    """Driven from the ORM ROW through both projections, because that is the whole path.

    ``media_file_id`` is dropped a layer below this one — the read layer publishes a boolean —
    so a test that started from the read layer's own value could not see the column at all and
    would assert the absence of something it never had.
    """
    view = to_body_view(_body_record(media_storage_key=_MEDIA_KEY, media_file_id=_FILE_ID))

    assert view.rendered_text == "Tom &amp; Jerry <b>tonight</b>"
    assert view.rendered_length == len(view.rendered_text)
    assert view.has_media is True
    assert view.is_media_cached is True
    assert _FILE_ID not in _wire(view)


def test_the_detail_view_carries_the_bodies_and_the_stored_filter() -> None:
    view = to_broadcast_detail_view(_detail(bodies=(_body_record(),)))

    assert view.is_segment_readable is True
    assert view.segment is not None
    assert view.segment.v == 1
    assert [body.language for body in view.bodies] == [Language.RU]


def test_the_detail_publishes_the_ledger_s_own_count_beside_the_row_s_rollup() -> None:
    """Both, deliberately. A rollup that has not caught up is the state a send is watched in,
    and picking one number would hide it behind one that keeps looking right."""
    view = to_broadcast_detail_view(_detail(recipient_count=100))

    assert view.broadcast.progress.recipient_count == 100
    assert view.counted_progress.recipient_count == 3 + 90 + 3 + 2 + 1 + 1
    assert view.counted_progress.unsettled_count == 3
    assert view.counted_progress.settled_count == 90 + 3 + 2 + 1 + 1


def test_a_stored_filter_this_build_no_longer_speaks_is_a_state_and_not_a_failure() -> None:
    """The campaign has already gone out; refusing to render the record would hide the whole
    of it behind a filter nobody can change anyway."""
    view = to_broadcast_detail_view(_detail(segment={"v": 99, "match": "all", "rules": []}))

    assert view.segment is None
    assert view.is_segment_readable is False
    assert view.broadcast.segment_hash == "a" * 64
