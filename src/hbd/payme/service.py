"""The dispatcher: one inbound JSON-RPC call in, one rendered envelope and one journal row out.

This is the only place in the repository that turns a rail-side refusal into a number a third
party acts on, and it is deliberately the thinnest layer in the integration. It holds no
session, opens no transaction, reads no clock of its own and makes no decision about money.
Every business answer comes back from :class:`hbd.payme.ports.PaymeLedger` as a ``Result``;
this module's entire job is the translation, and keeping it a translation is what lets the
state machine be tested with no ASGI client and the wire be tested with no database.

**The mapping table, stated once, because a scattered one is how a certification slot gets
burned.** A ledger ``Err`` carrying a :class:`hbd.payme.errors.PaymeFault` renders that fault's
``rpc_code``; anything whose code falls in ``-31050..-31099`` additionally renders ``data``
(the account subfield name) and the mandatory three-key ``{ru, uz, en}`` message that PAYME's
own interface shows the customer. The envelope's shape is decided by the CODE'S RANGE and not
by the exception class, because one code in that family is settable at runtime — see
:meth:`PaymeService._fault`. An ``Err`` carrying anything else — a ``StorageError``, a
``ValidationError``, an ``HbdError`` nobody anticipated — renders ``-32400``, because "we
broke" is a different sentence from "your order cannot be paid" and Payme retries the first.

**Malformed method PARAMETERS are not envelope errors.** The envelope is ``method``/``params``/
``id`` and its failures are ``-32600``; what is inside ``params`` differs per method and its
failures have business codes:

* a missing or non-integer ``amount`` is ``-31001`` — an amount that is not an integer is
  certainly not the integer the intent was opened for, and re-pricing is never an option here;
* a missing ``account`` object, or an account with no value under the configured subfield, is
  ``-31050`` carrying ``data`` — this is the single most likely go-live defect, because the
  subfield name is typed by a human into the cabinet's «Настройка Аккаунт» form, so the log
  line for it names both the field we expected and the fields that actually arrived;
* a missing or non-string transaction ``id`` on Perform/Cancel/Check is ``-31003``: it names no
  transaction, and "not found" is both the honest answer and the documented code for those
  three methods;
* a missing or non-integer ``from``/``to`` on GetStatement is ``-32600``, because that method
  has no business code for a malformed window and inventing one would be worse than saying the
  request was not well formed.

``bool`` is rejected everywhere an integer is required. ``isinstance(True, int)`` is ``True``
in Python, so a ``"amount": true`` would otherwise be read as one tiyin.

**The notification is enqueued after the commit, and its failure is swallowed.** Payme's ``200``
is not negotiable: the money is recorded, the receipt and the grant are in the same committed
transaction, and a Redis outage must degrade to a customer told late rather than to a payment
the rail believes failed and retries. The sweep in ``hbd.runtime.payme_jobs`` re-enqueues
anything that fell on the floor here, which is the only reason swallowing is honest.

**Every dispatched call writes exactly one journal row and emits exactly one structured line**,
and neither ever carries a request body, a header, the ``Authorization`` value or a Telegram
id. That absence is what keeps ``payme_rpc_log`` out of ``tables_with_personal_data`` and off a
retention clock; it is also what makes the row safe to keep for ninety days. A journal write
that fails is logged and swallowed for the same reason the enqueue is: a failed INSERT into an
audit table must not turn a settled payment into a ``-32400`` and a retry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from time import perf_counter
from typing import Any, Final, Protocol, runtime_checkable

from hbd.contracts import Err
from hbd.errors import HbdError
from hbd.logging import get_logger
from hbd.payme.errors import PaymeAccountFault, PaymeFault
from hbd.payme.ports import PaymeLedger, PaymeStatementRow, PaymeTransactionView
from hbd.payme.protocol import (
    ACCOUNT_MESSAGES,
    CancelReason,
    PaymeErrorCode,
    PaymeMethod,
    RpcRequest,
    from_ms,
    localised,
    render_fault,
    render_success,
)
from hbd.payme.rules import wire_state, wire_time

__all__ = [
    "PaymeService",
    "RpcJournal",
    "NotifyEnqueue",
    "SUCCESS_REPLY_CODE",
    "MAX_JOURNALLED_METHOD",
    "MAX_RENDERED_MESSAGE",
    "ACCOUNT_CODE_RANGE",
    "CHANGE_PASSWORD_REFUSAL",
]

_LOGGER: Final = get_logger(__name__)

#: What ``payme_rpc_log.reply_code`` holds for a call that succeeded. Zero rather than ``NULL``
#: so "how many of yesterday's calls failed?" is a comparison and not a three-valued one.
SUCCESS_REPLY_CODE: Final[int] = 0

#: ``payme_rpc_log.method`` is ``String(32)``. The value comes off a hostile wire, so it is
#: truncated at the writer — an unknown method name is exactly the thing an incident needs
#: recorded, and losing the whole row to a length violation would lose it.
MAX_JOURNALLED_METHOD: Final[int] = 32

#: A refusal message is written by us and read by an operator on Payme's side. Bounded so a
#: long ``operator_message`` cannot bloat a reply the rail parses under a timeout budget.
MAX_RENDERED_MESSAGE: Final[int] = 200

#: ``-31099`` through ``-31050`` inclusive: the family whose replies Payme's own interface
#: renders to the customer. Every code in it MUST carry ``data`` (the account subfield name)
#: and a three-key message map. Expressed as a range rather than as the five allocated members
#: because the duplicate-transaction setting can point at an unallocated one — see
#: :meth:`PaymeService._fault`.
ACCOUNT_CODE_RANGE: Final[range] = range(-31099, -31049)

#: What ``ChangePassword`` is answered with. The method is DISPATCHED — so we are not a
#: ``-32601`` surprise to a caller that still remembers the 2017 specification — and refused,
#: because implementing it would require the one internet-facing process in this system to
#: rewrite its own credential on request. Rotation is stop, edit the dotenv, restart, and
#: ``docs/deployment/08-payme.md`` says so.
CHANGE_PASSWORD_REFUSAL: Final[str] = (
    "key rotation on this deployment is a redeploy: the endpoint does not rewrite its own "
    "credential, see the key-rotation runbook"
)

#: The parameter names, spelled once. They are Payme's, not ours, and a typo in one of them is
#: a method that silently never finds its argument.
_PARAM_ID: Final[str] = "id"
_PARAM_TIME: Final[str] = "time"
_PARAM_AMOUNT: Final[str] = "amount"
_PARAM_ACCOUNT: Final[str] = "account"
_PARAM_REASON: Final[str] = "reason"
_PARAM_FROM: Final[str] = "from"
_PARAM_TO: Final[str] = "to"

_METHOD_NAMES: Final[frozenset[str]] = frozenset(method.value for method in PaymeMethod)

#: ``(public_ref) -> None``. What the gateway can do about telling a customer: hand the
#: reference to the queue and let the process that holds the Telegram token write the sentence.
type NotifyEnqueue = Callable[[str], Awaitable[None]]


@runtime_checkable
class RpcJournal(Protocol):
    """Where one inbound call is recorded. Implemented in the composition root.

    A port rather than a direct call into ``hbd.db.payme_sql.insert_rpc_log`` for two reasons,
    and only the second is about layering.

    The first is the transaction boundary. The journal write must NOT share the settlement's
    transaction: a failed INSERT into an audit table would otherwise roll back a performed
    payment, turning a bookkeeping problem into a customer whose card was charged and whose
    receipt does not exist. So it runs afterwards, in its own session, and its failure is
    swallowed — which is only defensible because it cannot take anything down with it.

    The second is that :mod:`hbd.payme` may not import :mod:`hbd.db` (see the package
    docstring), so the implementation lives beside the engine that serves it, in
    :mod:`hbd.payme.container`.
    """

    async def record(
        self,
        *,
        at: datetime,
        method: str,
        payme_transaction_id: str | None,
        public_ref: str | None,
        reply_code: int,
        peer_ip: str | None,
        duration_ms: int,
    ) -> None:
        """Write one row. Never raises: the caller has already answered the rail."""
        ...


def _integer(params: Mapping[str, Any], name: str) -> int | None:
    """An integer parameter, or ``None`` when it is absent or the wrong type.

    ``bool`` is excluded explicitly. ``isinstance(True, int)`` is ``True`` in Python, so
    without the second clause a body carrying ``"amount": true`` would be read as one tiyin
    and compared against the intent — a refusal for the right reason by pure luck, and an
    acceptance the day somebody prices something at one tiyin.
    """
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _string(params: Mapping[str, Any], name: str) -> str | None:
    """A non-empty string parameter, or ``None``.

    Empty counts as absent: Payme's transaction id is a 24-character ObjectId and an empty
    string names no transaction, so treating it as present would put a lookup for ``""`` in
    front of the ``-31003`` that is already the right answer.
    """
    value = params.get(name)
    if not isinstance(value, str) or not value:
        return None
    return value


def _account(params: Mapping[str, Any]) -> Mapping[str, Any]:
    """The ``account`` object, or an empty mapping when it is missing or not an object.

    Total rather than optional so the two callers can each ask their own question of it — "is
    the configured subfield present?" and "which subfields DID arrive?" — without either of
    them having to handle the absent case a second time.
    """
    value = params.get(_PARAM_ACCOUNT)
    return value if isinstance(value, Mapping) else {}


def _received_account_fields(params: Mapping[str, Any]) -> tuple[str, ...]:
    """The subfield NAMES the caller sent, sorted. Names only — never their values.

    A value here would be an order reference, which is opaque, and a phone number, which is
    not; the names alone answer the only question this is for, which is whether the cabinet's
    «Настройка Аккаунт» form and ``HBD_PAYME_ACCOUNT_FIELD`` agree.
    """
    return tuple(sorted(str(name) for name in _account(params)))


def _reply_code(body: Mapping[str, object]) -> int:
    """The journal's ``reply_code``, read back off the envelope that is actually being sent.

    Derived rather than returned alongside each body on purpose: a handler that returned the
    code separately could drift from the envelope it rendered, and the row would then record an
    answer nobody received. There is exactly one envelope and this reads it.
    """
    error = body.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        if isinstance(code, int):
            return code
    return SUCCESS_REPLY_CODE


def _fault_message(error: HbdError) -> str:
    """The plain-string message for a non-account refusal, bounded.

    The operator message rather than a static sentence per code: these strings are read by a
    human on Payme's side reconciling a failed payment, and "transaction … is in state …" is
    the difference between a support ticket and a glance at a log. They carry no personal data
    — a state name, a rail-side id Payme already has, and our own opaque reference.
    """
    message = error.operator_message
    if len(message) <= MAX_RENDERED_MESSAGE:
        return message
    return f"{message[: MAX_RENDERED_MESSAGE - 1]}…"


class PaymeService:
    """Route one parsed request to the ledger, render the answer, journal the call.

    Built with everything it needs handed in, including the clock: this object is constructed
    by a composition root that also builds the ledger, and a dispatcher that reached for a
    module-level ``utc_now`` would be one whose expiry branch could not be driven in a test.

    ``account_field`` and ``duplicate_code`` are held here as well as inside the ledger, and
    that is not duplication of a decision — it is the same value reaching two layers that use
    it for different things. The ledger RAISES with them (it is inside the transaction, where
    no settings object is in scope); this object RENDERS with them, on the paths that never
    reach the ledger at all: a missing account object is a ``-31050`` that no database call
    was ever made for.
    """

    __slots__ = ("_account_field", "_clock", "_duplicate_code", "_journal", "_ledger", "_notify")

    def __init__(
        self,
        ledger: PaymeLedger,
        *,
        clock: Callable[[], datetime],
        journal: RpcJournal,
        notify: NotifyEnqueue,
        account_field: str,
        duplicate_code: int,
    ) -> None:
        self._ledger = ledger
        self._clock = clock
        self._journal = journal
        self._notify = notify
        self._account_field = account_field
        self._duplicate_code = duplicate_code

    async def dispatch(
        self, request: RpcRequest, *, peer_ip: str | None
    ) -> tuple[dict[str, object], int]:
        """Answer one request. Returns the body to send and the code to journal.

        Never raises. Every branch below either renders a result or renders a fault, and the
        ASGI layer's own middleware is the backstop for a defect in this one — a ``-32400`` at
        HTTP 200 rather than a 500 that Payme reads as ``-32400`` anyway and that costs us the
        id echo.
        """
        started = perf_counter()
        now = self._clock()
        body = await self._route(request, now=now)
        code = _reply_code(body)
        await self._record(
            at=now,
            method=request.method,
            params=request.params,
            reply_code=code,
            peer_ip=peer_ip,
            duration_ms=_elapsed_ms(started),
            request_id=request.id,
        )
        return body, code

    async def record_refusal(
        self,
        *,
        method: str,
        reply_code: int,
        peer_ip: str | None,
        started: float,
    ) -> None:
        """Journal a call that never reached :meth:`dispatch` — bad auth, or an unparseable body.

        Those are exactly the calls the journal exists to answer questions about. "Did Payme
        ever call us about this?" is asked most often when the answer is "yes, and we refused
        them", and a journal that recorded only the calls that parsed would be silent on the
        one failure mode a certification slot is lost to.

        ``method`` is whatever could be salvaged, or a placeholder: a body that did not parse
        has no method, and the row still has to exist.
        """
        await self._record(
            at=self._clock(),
            method=method,
            params={},
            reply_code=reply_code,
            peer_ip=peer_ip,
            duration_ms=_elapsed_ms(started),
            request_id=None,
        )

    # -- routing ------------------------------------------------------------
    async def _route(self, request: RpcRequest, *, now: datetime) -> dict[str, object]:
        """Pick the handler. An unknown method is ``-32601`` with the name in ``data``."""
        if request.method not in _METHOD_NAMES:
            return render_fault(
                PaymeErrorCode.METHOD_NOT_FOUND,
                "unknown method",
                request_id=request.id,
                data=request.method[:MAX_RENDERED_MESSAGE],
            )
        method = PaymeMethod(request.method)
        params = request.params
        identifier = request.id
        match method:
            case PaymeMethod.CHECK_PERFORM_TRANSACTION:
                return await self._check_perform(params, request_id=identifier, now=now)
            case PaymeMethod.CREATE_TRANSACTION:
                return await self._create(params, request_id=identifier, now=now)
            case PaymeMethod.PERFORM_TRANSACTION:
                return await self._perform(params, request_id=identifier, now=now)
            case PaymeMethod.CANCEL_TRANSACTION:
                return await self._cancel(params, request_id=identifier, now=now)
            case PaymeMethod.CHECK_TRANSACTION:
                return await self._check(params, request_id=identifier)
            case PaymeMethod.GET_STATEMENT:
                return await self._statement(params, request_id=identifier)
            case PaymeMethod.CHANGE_PASSWORD:
                return render_fault(
                    PaymeErrorCode.INTERNAL, CHANGE_PASSWORD_REFUSAL, request_id=identifier
                )

    # -- the six methods ----------------------------------------------------
    async def _check_perform(
        self, params: Mapping[str, Any], *, request_id: int, now: datetime
    ) -> dict[str, object]:
        """``CheckPerformTransaction`` — bare ``{"allow": true}``, and it writes nothing.

        No ``detail`` object and no fiscalisation. Uzbek tax receipts need ИКПУ codes, a
        ``package_code`` and a ``vat_percent`` per item; none of that can be guessed, the
        documentation contradicts itself on whether ``items`` is required, and a wrong receipt
        is worse than none. ``SetFiscalData`` is deliberately not implemented either.
        """
        amount = _integer(params, _PARAM_AMOUNT)
        if amount is None:
            return self._wrong_amount(request_id)
        reference = self._account_value(params)
        if reference is None:
            return self._unknown_account(request_id, params)
        quoted = await self._ledger.quote(public_ref=reference, amount_minor=amount, now=now)
        if isinstance(quoted, Err):
            return self._fault(quoted.error, request_id=request_id)
        return render_success({"allow": True}, request_id=request_id)

    async def _create(
        self, params: Mapping[str, Any], *, request_id: int, now: datetime
    ) -> dict[str, object]:
        """``CreateTransaction`` — the mutex point. A replay returns the STORED row."""
        identifier = _string(params, _PARAM_ID)
        if identifier is None:
            return self._not_found(request_id)
        amount = _integer(params, _PARAM_AMOUNT)
        if amount is None:
            return self._wrong_amount(request_id)
        moment = _integer(params, _PARAM_TIME)
        if moment is None:
            return self._malformed(request_id, _PARAM_TIME)
        reference = self._account_value(params)
        if reference is None:
            return self._unknown_account(request_id, params)
        created = await self._ledger.create(
            payme_transaction_id=identifier,
            payme_time=from_ms(moment),
            amount_minor=amount,
            public_ref=reference,
            now=now,
        )
        if isinstance(created, Err):
            return self._fault(created.error, request_id=request_id)
        view = created.value
        return render_success(
            {
                "create_time": wire_time(view.create_time),
                "transaction": str(view.our_id),
                "state": wire_state(view.state),
            },
            request_id=request_id,
        )

    async def _perform(
        self, params: Mapping[str, Any], *, request_id: int, now: datetime
    ) -> dict[str, object]:
        """``PerformTransaction`` — one commit, then the notification, then the reply.

        The enqueue happens only after an ``Ok``, which is only produced after the ledger's
        transaction committed. A job enqueued before the commit is a job that can read a
        settlement that never happened.
        """
        identifier = _string(params, _PARAM_ID)
        if identifier is None:
            return self._not_found(request_id)
        performed = await self._ledger.perform(payme_transaction_id=identifier, now=now)
        if isinstance(performed, Err):
            return self._fault(performed.error, request_id=request_id)
        view = performed.value
        await self._enqueue_notification(view)
        return render_success(
            {
                "transaction": str(view.our_id),
                "perform_time": wire_time(view.perform_time),
                "state": wire_state(view.state),
            },
            request_id=request_id,
        )

    async def _cancel(
        self, params: Mapping[str, Any], *, request_id: int, now: datetime
    ) -> dict[str, object]:
        """``CancelTransaction`` — releases a created transaction, refuses a performed one.

        An absent ``reason`` is Payme's own ``10`` (unknown) rather than a refusal: the reason
        is echoed back numerically and has no bearing on what we do, so demanding it would turn
        a cosmetic omission into a payment stuck in state 1.
        """
        identifier = _string(params, _PARAM_ID)
        if identifier is None:
            return self._not_found(request_id)
        reason = _integer(params, _PARAM_REASON)
        cancelled = await self._ledger.cancel(
            payme_transaction_id=identifier,
            reason=int(CancelReason.UNKNOWN) if reason is None else reason,
            now=now,
        )
        if isinstance(cancelled, Err):
            return self._fault(cancelled.error, request_id=request_id)
        view = cancelled.value
        return render_success(
            {
                "transaction": str(view.our_id),
                "cancel_time": wire_time(view.cancel_time),
                "state": wire_state(view.state),
            },
            request_id=request_id,
        )

    async def _check(self, params: Mapping[str, Any], *, request_id: int) -> dict[str, object]:
        """``CheckTransaction`` — read-only, and it takes no ``now`` for that reason.

        The absent clock is the specification: a status read that could expire the thing it was
        asked about would make Payme's own poll change the answer it was polling for.
        """
        identifier = _string(params, _PARAM_ID)
        if identifier is None:
            return self._not_found(request_id)
        found = await self._ledger.read(payme_transaction_id=identifier)
        if isinstance(found, Err):
            return self._fault(found.error, request_id=request_id)
        return render_success(_transaction_body(found.value), request_id=request_id)

    async def _statement(self, params: Mapping[str, Any], *, request_id: int) -> dict[str, object]:
        """``GetStatement`` — mandatory, inclusive at both ends, ascending, plural result key.

        Note the swap: in every other reply ``transaction`` is ours and there is no ``id``; in
        a statement row ``id`` is THEIRS and ``transaction`` is ours. It is Payme's shape and
        it is the one place the two identifiers change places.
        """
        frm = _integer(params, _PARAM_FROM)
        to = _integer(params, _PARAM_TO)
        if frm is None:
            return self._malformed(request_id, _PARAM_FROM)
        if to is None:
            return self._malformed(request_id, _PARAM_TO)
        listed = await self._ledger.statement(frm=from_ms(frm), to=from_ms(to))
        if isinstance(listed, Err):
            return self._fault(listed.error, request_id=request_id)
        return render_success(
            {"transactions": self._statement_rows(listed.value)}, request_id=request_id
        )

    def _statement_rows(self, rows: Sequence[PaymeStatementRow]) -> list[dict[str, object]]:
        """Project each row, pairing the account value with the CONFIGURED subfield name."""
        return [
            {
                "id": row.transaction.payme_transaction_id,
                "time": wire_time(row.transaction.payme_time),
                "amount": row.transaction.amount_minor,
                "account": {self._account_field: row.account_value},
                **_transaction_body(row.transaction),
            }
            for row in rows
        ]

    # -- refusals -----------------------------------------------------------
    def _fault(self, error: HbdError, *, request_id: int) -> dict[str, object]:
        """One ledger ``Err`` as one envelope. See the module docstring's mapping table.

        **The envelope's SHAPE is decided by the code's range, not by the exception class**,
        and that distinction is load-bearing rather than pedantic. Everything in
        ``-31050..-31099`` must carry ``data`` and a three-key ``{ru, uz, en}`` map, because
        PAYME's interface renders those to the customer and highlights the account field
        ``data`` names — a bare string there is a broken payment page, not a stylistic choice.

        Almost every code in that range arrives as a :class:`PaymeAccountFault`, which carries
        its own subfield name. One does not: ``HBD_PAYME_DUPLICATE_TRANSACTION_CODE`` is raised
        as a :class:`PaymeStateRefusal` with a settable code, and the whole reason it is
        settable is that Payme's own materials contradict each other about it — the sandbox
        text demands ``-31008`` while PaycomUZ's own PHP template returns ``-31050``. Pointing
        that setting at ``-31050`` or ``-31054`` during certification must therefore change the
        envelope shape with it, or the flag would fix one finding and cause another.
        """
        if isinstance(error, PaymeAccountFault):
            return render_fault(
                error.rpc_code,
                _account_message(error.rpc_code),
                request_id=request_id,
                data=error.account_field,
            )
        if isinstance(error, PaymeFault):
            if error.rpc_code in ACCOUNT_CODE_RANGE:
                return render_fault(
                    error.rpc_code,
                    _account_message(error.rpc_code),
                    request_id=request_id,
                    data=self._account_field,
                )
            return render_fault(error.rpc_code, _fault_message(error), request_id=request_id)
        return render_fault(
            PaymeErrorCode.INTERNAL, _fault_message(error), request_id=request_id
        )

    def _account_value(self, params: Mapping[str, Any]) -> str | None:
        """Our ``public_ref`` out of the account object, or ``None`` when it is not there.

        Read by NAME rather than positionally, because the cabinet's «Настройка Аккаунт» form
        can declare more than one subfield and Payme sends every one it collected.
        """
        value = _account(params).get(self._account_field)
        if not isinstance(value, str) or not value:
            return None
        return value

    def _unknown_account(
        self, request_id: int, params: Mapping[str, Any]
    ) -> dict[str, object]:
        """``-31050`` with ``data``, and the one log line that makes a cabinet typo obvious.

        The expected field name and the names that actually arrived, side by side. That
        mismatch is the single most likely defect on go-live day and it is invisible from the
        wire alone — the customer sees "order not found", we see a perfectly valid request, and
        the difference is one string typed into a web form on Payme's side.
        """
        received = _received_account_fields(params)
        _LOGGER.warning(
            "an inbound call carried no usable account reference",
            extra={
                "event": "payme.account.unknown",
                "expected_field": self._account_field,
                "received_fields": list(received),
            },
        )
        return render_fault(
            PaymeErrorCode.ACCOUNT_UNKNOWN,
            _account_message(PaymeErrorCode.ACCOUNT_UNKNOWN),
            request_id=request_id,
            data=self._account_field,
        )

    def _wrong_amount(self, request_id: int) -> dict[str, object]:
        return render_fault(
            PaymeErrorCode.WRONG_AMOUNT,
            "the amount is missing or is not an integer number of tiyin",
            request_id=request_id,
        )

    def _not_found(self, request_id: int) -> dict[str, object]:
        return render_fault(
            PaymeErrorCode.TRANSACTION_NOT_FOUND,
            "the request names no transaction",
            request_id=request_id,
        )

    def _malformed(self, request_id: int, name: str) -> dict[str, object]:
        return render_fault(
            PaymeErrorCode.ENVELOPE,
            f"params.{name} is missing or is not an integer",
            request_id=request_id,
        )

    # -- side effects -------------------------------------------------------
    async def _enqueue_notification(self, view: PaymeTransactionView) -> None:
        """Hand the settled reference to the queue. **A failure here is never the rail's.**

        The gateway holds no Telegram token — that is the entire point of it being a fourth
        process — so telling the customer is a job the worker runs. If the queue cannot be
        reached, the money is still recorded and Payme still gets its ``200``; the sweep's
        delivery arm picks the intent up on its next pass, which turns a Redis outage at the
        moment of payment into a latency problem rather than a silence.
        """
        try:
            await self._notify(view.intent_public_ref)
        except Exception as exc:
            _LOGGER.exception(
                "a settled payment could not be queued for notification",
                extra={
                    "event": "payme.notify.enqueue_failed",
                    "public_ref": view.intent_public_ref,
                    "payme_transaction_id": view.payme_transaction_id,
                    "detail": repr(exc),
                },
            )

    async def _record(
        self,
        *,
        at: datetime,
        method: str,
        params: Mapping[str, Any],
        reply_code: int,
        peer_ip: str | None,
        duration_ms: int,
        request_id: int | None,
    ) -> None:
        """One journal row and one structured line. Neither can fail the request.

        The two carry the same facts on purpose: the row is queryable months later by an
        operator with the CLI, and the line is greppable now by an operator with the journal.
        Neither carries a body, a header or a Telegram id.
        """
        payme_transaction_id = _string(params, _PARAM_ID)
        public_ref = self._account_value(params)
        _LOGGER.info(
            "payme rpc",
            extra={
                "event": "payme.rpc",
                "method": method[:MAX_JOURNALLED_METHOD],
                "payme_transaction_id": payme_transaction_id,
                "public_ref": public_ref,
                "reply_code": reply_code,
                "duration_ms": duration_ms,
                "peer_ip": peer_ip,
                "request_id": request_id,
            },
        )
        try:
            await self._journal.record(
                at=at,
                method=method[:MAX_JOURNALLED_METHOD],
                payme_transaction_id=payme_transaction_id,
                public_ref=public_ref,
                reply_code=reply_code,
                peer_ip=peer_ip,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            _LOGGER.exception(
                "an inbound call could not be journalled",
                extra={
                    "event": "payme.journal.write_failed",
                    "method": method[:MAX_JOURNALLED_METHOD],
                    "reply_code": reply_code,
                    "detail": repr(exc),
                },
            )


def _elapsed_ms(started: float) -> int:
    """Whole milliseconds since a ``perf_counter`` reading, floored at zero.

    ``perf_counter`` rather than the injected clock: this is a duration, and a test that moves
    the clock backwards to drive an expiry branch must not be able to journal a negative one.
    """
    return max(0, int((perf_counter() - started) * 1000))


#: Which codes :data:`hbd.payme.protocol.ACCOUNT_MESSAGES` actually carries a message for.
#: Derived rather than restated so a sixth account code added there is covered here.
_ACCOUNT_CODES: Final[frozenset[int]] = frozenset(int(code) for code in ACCOUNT_MESSAGES)


def _account_message(code: int) -> Mapping[str, str]:
    """The three-key message for an account-range code, with a total fallback.

    :data:`hbd.payme.protocol.ACCOUNT_MESSAGES` covers the five codes the ledger raises. The
    fallback exists because the code can also arrive through
    ``HBD_PAYME_DUPLICATE_TRANSACTION_CODE``, which certification may point at a member of this
    range that has no message of its own — and a reply carrying a bare string where Payme's
    interface expects a map is a rendering failure on the customer's screen.
    """
    if code in _ACCOUNT_CODES:
        return ACCOUNT_MESSAGES[PaymeErrorCode(code)]
    return localised(
        ru="Заказ недоступен для оплаты",
        uz="Buyurtma toʻlov uchun mavjud emas",
        en="This order cannot be paid",
    )


def _transaction_body(view: PaymeTransactionView) -> dict[str, object]:
    """The five fields every reply that describes a transaction carries.

    Shared between ``CheckTransaction`` and each ``GetStatement`` row because they are the
    same five fields and a second copy is how ``perform_time`` starts rendering as ``null`` in
    one of them. ``reason`` is the one field where ``null`` is correct and ``0`` would be a lie
    about a cancellation reason that does not exist.
    """
    return {
        "create_time": wire_time(view.create_time),
        "perform_time": wire_time(view.perform_time),
        "cancel_time": wire_time(view.cancel_time),
        "transaction": str(view.our_id),
        "state": wire_state(view.state),
        "reason": view.cancel_reason,
    }
