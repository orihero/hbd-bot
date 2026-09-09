"""The rail's refusals, as ``HbdError`` subclasses that each carry a JSON-RPC code.

**Why these are exceptions at all, in a codebase whose seams return ``Result``.** They are
raised INSIDE the persistence transaction that is deciding the answer, and they are raised
precisely so that raising them rolls it back. "This intent already has a live transaction" is
not a value the state machine can return and then remember to undo three statements later; it
is a refusal that must leave no row behind, and an exception inside
``async with self._sessions.begin()`` is the only construct that guarantees that without a
single compensating write. The seam itself still never raises: every public ledger method is
wrapped in :func:`hbd.db.guard.run_guarded`, which catches ``HbdError`` and hands the caller
an ``Err``. The refusal crosses the boundary as a value; it just does not START as one.

**They are ``HbdError`` subclasses SPECIFICALLY so that ladder already catches them.**
``run_guarded`` catches ``NotFoundError``, then ``HbdError``, then ``IntegrityError``,
``SQLAlchemyError`` and pydantic's ``ValidationError``. A fresh exception base would have
fallen through all five, escaped the guard, escaped the seam, and reached the ASGI layer —
where it would have been rendered as ``-32400`` "internal error" instead of the specific
refusal Payme's certification suite is asserting. Inheriting is not tidiness here; it is the
difference between a passing scenario and an unexplainable one.

**``rpc_code`` is the only thing this hierarchy adds**, and it is a CLASS attribute on the
fixed-code subclasses and an INSTANCE attribute on the two that vary. That split is the
protocol's, not ours: ``-31001``, ``-31003`` and ``-31007`` mean exactly one thing each, while
"state refusal" is emitted through a setting because Payme's own materials contradict each
other about the duplicate-transaction case, and the account range has five members that differ
only in which of them applies.

**No ``error.*`` locale key is invented here, and none should be.** These sentences are for
PAYME's screen — rendered from :data:`hbd.payme.protocol.ACCOUNT_MESSAGES` by the dispatcher,
in Payme's three languages, on a page we do not control. A customer of ours never sees one:
by the time a Payme refusal happens the customer is in a browser, not in a chat, and the bot
learns about the outcome minutes later through a notification job with its own copy. So every
class here inherits ``HbdError``'s generic ``error.generic`` key untouched rather than
declaring one. (The obvious alternative, ``default_user_message_key = None``, is not
available: ``HbdError`` declares that attribute as ``str`` and ``mypy --strict`` rejects the
narrowing. Inheriting the generic key invents nothing, which was the actual requirement.)

Every class is terminal — ``default_is_retryable = False`` — and that is load-bearing rather
than a default: ``Err.is_retryable`` drives the ARQ ladder, and a retryable payment refusal
would re-run a settlement on a schedule for an answer that cannot change until Payme calls
again with different arguments.

See ``PAYME_INTEGRATION §4`` for the account-code allocation and ``§6`` for why there is no
reversal behind ``PaymeOrderDelivered``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hbd.errors import ErrorCode, HbdError
from hbd.payme.protocol import DEFAULT_ACCOUNT_FIELD, PaymeErrorCode

__all__ = [
    "PaymeFault",
    "PaymeAmountMismatch",
    "PaymeTransactionNotFound",
    "PaymeOrderDelivered",
    "PaymeStateRefusal",
    "PaymeAccountFault",
]


# ``N818`` wants every exception name to end in ``Error``. It is suppressed here, once, and
# only on the base: "fault" is JSON-RPC's OWN word for the object these render into — the
# reply carries an ``error`` member whose contents the specification calls a fault — and the
# five subclasses read as English sentences about a payment (``PaymeAmountMismatch``,
# ``PaymeOrderDelivered``) rather than as exception types, which is what they are at every
# call site: refusals raised to roll a transaction back. Renaming the base to
# ``PaymeFaultError`` would additionally make ruff start demanding the suffix on all five, so
# the choice is one suppression here or five renames that make the code read worse.
class PaymeFault(HbdError):  # noqa: N818
    """Base of every refusal that has a JSON-RPC code to be rendered as.

    Catch this to mean "the rail said no for a reason the protocol has a number for", as
    distinct from ``HbdError``, which at this seam means "something broke and Payme gets
    ``-32400``". The dispatcher makes exactly that distinction and nothing else: a
    ``PaymeFault`` renders :attr:`rpc_code`, anything else renders internal error.

    :attr:`rpc_code` defaults to ``INTERNAL`` rather than to a business code so that a
    subclass which forgets to set one degrades to "we broke" instead of silently claiming a
    specific business refusal Payme would then act on.
    """

    #: The JSON-RPC code this refusal renders as. Overridden per subclass, and per instance by
    #: the two subclasses whose code is not fixed by the protocol.
    rpc_code: int = PaymeErrorCode.INTERNAL

    code = ErrorCode.PAYMENT_FAILED
    default_is_retryable = False

    def with_context(self, **extra: Any) -> HbdError:
        """Clone with extra operator context, **preserving the code**.

        ``HbdError.with_context`` rebuilds the error by calling ``type(self)(...)`` with the
        five base keyword arguments only. For every subclass in this file whose code is an
        INSTANCE attribute that clone would silently fall back to the class default — a
        ``-31055`` cashbox mismatch would become a ``-31008`` state refusal on its way into a
        log line, and the wrong number would then be the one Payme was told. The override is
        two lines and it is the reason this method exists at all.
        """
        clone = super().with_context(**extra)
        if isinstance(clone, PaymeFault):
            clone.rpc_code = self.rpc_code
        return clone


class PaymeAmountMismatch(PaymeFault):
    """``-31001``: the amount Payme quoted is not the amount the intent was opened for.

    **A REFUSAL, never a re-price.** The tempting alternative — read the current price out of
    ``Settings`` and accept anything that matches it — would let a price change between the
    tap and the payment silently charge a customer a number they were never shown. The intent
    stores what the customer was quoted, in tiyin, and that integer is the only one this
    comparison may use.

    Nothing on this path multiplies by 100: ``single_song_price_minor = 700_000`` is already
    the number Payme is sent, and a stray multiplication would present a seven-million-so'm
    song, which is why the link builder's test suite pins the unmultiplied value by name.
    """

    rpc_code: int = PaymeErrorCode.WRONG_AMOUNT


class PaymeTransactionNotFound(PaymeFault):
    """``-31003``: we have no transaction under that Payme id, and we will not create one.

    **PerformTransaction NEVER creates a transaction**, and this is the class that enforces it.
    No primary source guarantees that CreateTransaction always precedes PerformTransaction on
    the wire, and both official reference servers answer ``-31003`` defensively rather than
    inventing a row; performing an order we never agreed to hold would write a receipt and a
    credit grant against an intent nobody checked the amount, the cashbox or the expiry of.
    """

    rpc_code: int = PaymeErrorCode.TRANSACTION_NOT_FOUND


class PaymeOrderDelivered(PaymeFault):
    """``-31007``: the transaction was performed, the goods are delivered, and it stands.

    **Unconditional, and the absence of a reversal behind it is a decision rather than a gap.**
    ``credit_accounts.balance`` is documented as a single fungible scalar with no lot
    structure, and ``verify_balances`` asserts it equals the sum of the ledger's deltas — so a
    compensating debit for purchase A cannot know it is not burning a credit the customer paid
    for in purchase B, or one already spent on a song that has been delivered. PaycomUZ's own
    merchant template returns false from ``Order::allowCancel()`` by default, so this is the
    REFERENCE behaviour and not a corner we cut.

    A genuine refund is therefore an operator procedure — a refund in Payme's cabinet plus a
    credit correction — and it is written down in the deployment runbook rather than automated
    against a balance that cannot express which credit is being taken back.
    """

    rpc_code: int = PaymeErrorCode.ORDER_DELIVERED


class PaymeStateRefusal(PaymeFault):
    """``-31008`` by default: the transition asked for is not one of the three legal ones.

    The legal transitions are ``created -> performed``, ``created -> cancelled`` and
    ``performed -> cancelled_after_perform``. Everything else lands here.

    **The code is settable at construction for exactly one case**, and it is the one place
    Payme's own materials contradict themselves: "this order already has another active
    transaction". The sandbox scenario text demands ``-31008``, PaycomUZ's PHP template returns
    ``-31050``, and three third-party packages pick ``-31054`` or ``-31099``. The gateway emits
    it through ``HBD_PAYME_DUPLICATE_TRANSACTION_CODE`` so a certification finding is an
    environment variable rather than a release. Every other construction takes the default and
    should — a settable code that got used for convenience would put the protocol's one honest
    ambiguity and a dozen ordinary refusals behind the same knob.
    """

    rpc_code: int = PaymeErrorCode.STATE_REFUSAL

    def __init__(
        self,
        operator_message: str,
        *,
        rpc_code: int = PaymeErrorCode.STATE_REFUSAL,
        user_message_key: str | None = None,
        code: ErrorCode | None = None,
        is_retryable: bool | None = None,
        context: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            operator_message,
            user_message_key=user_message_key,
            code=code,
            is_retryable=is_retryable,
            context=context,
            cause=cause,
        )
        self.rpc_code = rpc_code


class PaymeAccountFault(PaymeFault):
    """``-31050..-31099``: something is wrong with the ORDER, not with the transaction.

    The only family that carries ``data``, and the value of ``data`` is the account SUBFIELD
    NAME — the string a human typed into the cabinet's «Настройка Аккаунт» form, which must
    equal ``HBD_PAYME_ACCOUNT_FIELD``. Payme's interface uses it to highlight which field of
    the payment form the customer got wrong, so sending the wrong name renders a correct
    refusal against the wrong input box.

    ``account_field`` is carried on the INSTANCE rather than read from settings by the
    renderer, because the raiser is inside a database transaction that knows which field name
    the intent was issued under, and the renderer is in an ASGI handler that would have to be
    handed a settings object to find out. It defaults to
    :data:`hbd.payme.protocol.DEFAULT_ACCOUNT_FIELD` so a test or a CLI can raise one without
    threading configuration through.

    ``rpc_code`` is per-instance for the ordinary reason that five members of one family differ
    only in which of them applies: unknown order, already paid, cancelled, expired, wrong
    cashbox. The last of those, ``-31055``, is the one that only exists because the intent
    stores the merchant id it was ISSUED for — without that column, a deployment repointed at a
    sandbox cashbox while a production link is still live in somebody's chat has no way to
    notice, and the customer is charged by an account nobody is reconciling.
    """

    rpc_code: int = PaymeErrorCode.ACCOUNT_UNKNOWN

    def __init__(
        self,
        operator_message: str,
        *,
        rpc_code: int = PaymeErrorCode.ACCOUNT_UNKNOWN,
        account_field: str = DEFAULT_ACCOUNT_FIELD,
        user_message_key: str | None = None,
        code: ErrorCode | None = None,
        is_retryable: bool | None = None,
        context: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            operator_message,
            user_message_key=user_message_key,
            code=code,
            is_retryable=is_retryable,
            context=context,
            cause=cause,
        )
        self.rpc_code = rpc_code
        #: The account subfield name that becomes ``error.data``. See the class docstring.
        self.account_field = account_field

    def with_context(self, **extra: Any) -> HbdError:
        """As :meth:`PaymeFault.with_context`, and it must carry ``account_field`` too.

        Same failure, one field further along: the base clone would reset the subfield name to
        its default, and a deployment whose cabinet is configured with anything other than
        ``order_id`` would then report the wrong field on every logged refusal.
        """
        clone = super().with_context(**extra)
        if isinstance(clone, PaymeAccountFault):
            clone.account_field = self.account_field
        return clone
