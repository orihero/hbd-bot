"""``payme_rpc_log`` — one row per inbound rail call, so an incident is answerable.

This is the only table in the schema written by a request that arrives from the public
internet, from a caller we do not control, carrying a credential we do not rotate. When the
rail says "we called you eleven times and you refused four", the entire question is which
four, when, with what code, and how long we took. A log line cannot answer it: the gateway's
journal is rotated by the host, is not queryable, and is the first thing gone when a VPS is
rebuilt. So the answer is a table.

**IT DELIBERATELY CARRIES NO ``telegram_user_id``, NO REQUEST BODY AND NO HEADER, AND THAT
ABSENCE IS THE DESIGN RATHER THAN AN OMISSION TO BE FILLED IN LATER.** Storing the bodies is
the obvious next thought — they are small, they are JSON, and they would make replaying an
incident trivial. It is refused. The bodies carry the ``Authorization`` header's twin (the
credential is in the header, but a body echoed into a log beside a failing auth attempt is
one copy-paste from being pasted into a ticket), they carry the account object, and they
would drag this table into ``tests/test_db/test_privacy_constraints.py``'s
``tables_with_personal_data`` — which would put an inbound-request log on a retention clock,
oblige a sweep BY NAME, and make the one table an operator reads DURING an incident the one
table that has been deleting itself on a schedule. Every column below is therefore a method
name, an opaque reference, a machine id, an integer, or the address of THEIR server. That is
precisely the argument ``vendor_usage`` (revision 0016) already makes for itself, and this
table is a closer fit for it than ``vendor_usage`` is: ``vendor_usage`` is our outbound
telemetry and holds no id because none was needed, whereas this one holds none because the
identifiers it does carry — ``public_ref``, the rail's transaction id — were chosen from the
start to be meaningless without a join.

``peer_ip`` is worth its own sentence, because an IP address is personal data in the general
case and is not one here. The rail publishes the fifteen addresses its calls originate from
and the allowlist is enforced at the TLS terminator rather than in this process, so every
address in this column is a machine in somebody's data centre, never a customer's phone. It
is stored precisely BECAUSE the filter is upstream: a terminator misconfigured with the
wrong proxy-hop count makes the application see the proxy's own address, and the only way to
discover the real caller set is to have written down what we actually saw. A NULL here means
the transport did not give us one, which is itself the fact worth having.

**WHY THE BOUND IS A 90-DAY CUTOFF ON ``at`` AND NOT AN ``*_expires_at`` CLOCK.** The suffix
is this codebase's word for a RETENTION clock: a published legal commitment, stamped per row
by its writer from ``RetentionPolicy``, which ``tests/test_db/test_audit_retention.py``
collects by name and demands a sweep for. This table holds no personal data and has no such
commitment to make. It is bounded growth on an internal journal, on ``vendor_usage``'s and
``bot_membership_events``' footing — a cutoff applied at sweep time in ``bayram.db.purge``, and
90 days rather than 400 because the questions this table answers are asked during and just
after an incident, and a certification dispute that is still open after a quarter is not
going to be settled by an entry in it.

**WHY IT IS APPEND-ONLY AND HAS NO ``TimestampMixin``.** ``at`` is the one meaningful
instant; a ``created_at`` beside it would be a second clock that always equals the first, and
an ``updated_at`` would be an invitation to amend a journal whose only value is that nobody
amends it. ``purge_runs`` refuses the mixin for the identical reason and says so.

**WHY THE JOURNAL AND THE TRANSACTION TABLE ARE SEPARATE.** Rows land here for calls that
create no transaction at all: a failed authentication, an unparseable body, a method we do
not implement, a quote for an intent that does not exist. Those are the calls an incident is
actually about, and they have no transaction row to hang off. Writing them here keeps
``payme_transactions`` a record of MONEY — unbounded, never swept — while the chatter around
it stays bounded and disposable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import Base, UtcDateTime
from bayram.db.models.payme_transaction import PAYME_TRANSACTION_ID_LENGTH
from bayram.db.models.payment_intent import PUBLIC_REF_LENGTH

__all__ = ["PaymeRpcLogRow", "RPC_METHOD_LENGTH", "PEER_IP_LENGTH"]

#: The longest method name the rail defines is ``CheckPerformTransaction`` at 23 characters.
#: Sized to ``ENUM_LENGTH``'s 32 rather than to a closed enum on purpose: an UNKNOWN method
#: is one of the things this journal exists to record, and an ``enum_type`` column would
#: raise on the way in and lose exactly the row an incident needs. Truncation on the way in
#: is handled by the writer; the width is what stops a hostile 4 KB "method" name.
RPC_METHOD_LENGTH: Final[int] = 32
#: An IPv6 address in its longest textual form — an IPv4-mapped one such as
#: ``0000:0000:0000:0000:0000:ffff:255.255.255.255`` — is 45 characters. The rail's own
#: published addresses are IPv4, but the column records what the TRANSPORT reported, and a
#: terminator speaking IPv6 to us is a configuration nobody has to have anticipated.
PEER_IP_LENGTH: Final[int] = 45


class PaymeRpcLogRow(Base):
    """One inbound call and how it was answered. Append-only, never amended.

    ``TimestampMixin`` is deliberately not used — see the module docstring. The two
    identifier columns are BOTH nullable and that is not a weakness in the schema: a call
    that failed authentication has neither, a call for an unknown account has a
    ``public_ref`` and no transaction, and a perform for a transaction we know has both. What
    the row carries is the honest answer to "how much did we actually learn from this call",
    and a NULL is part of that answer rather than a gap in it.
    """

    __tablename__ = "payme_rpc_log"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: When the call was answered. Indexed: every read of this table is a window, and the
    #: 90-day cutoff sweep is a range delete on exactly this column.
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    #: The method NAME as it arrived on the wire, including one we do not implement — see
    #: :data:`RPC_METHOD_LENGTH` on why this is a string and not a closed enum.
    method: Mapped[str] = mapped_column(sa.String(RPC_METHOD_LENGTH), nullable=False)
    #: The rail's own transaction id, when the call named one we could read. NULL otherwise.
    #: Indexed because "show me everything that happened to this transaction" is the one
    #: query anybody runs against this table under pressure. Width shared with
    #: ``payme_transactions`` so the two are joinable without a cast.
    payme_transaction_id: Mapped[str | None] = mapped_column(
        sa.String(PAYME_TRANSACTION_ID_LENGTH), nullable=True, index=True
    )
    #: Our opaque account reference, when the call named one. NULL otherwise. Indexed for
    #: the same reason as the column above, from the other end: a customer complains about a
    #: payment page, and the only handle they and we share is this. Width shared with
    #: ``payment_intents.public_ref``.
    public_ref: Mapped[str | None] = mapped_column(
        sa.String(PUBLIC_REF_LENGTH), nullable=True, index=True
    )
    #: ``0`` for a successful reply, otherwise the JSON-RPC error code we sent — which is
    #: negative for every fault the protocol defines, so the two populations are told apart
    #: by sign and no second column is needed. NOT NULL and no default: every call is
    #: answered, so there is always a code, and this is a MEASURED value rather than an
    #: unmeasured quantity the null-never-zero rule would govern.
    reply_code: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: The address the request came from, as the transport reported it. THEIR server, never a
    #: customer — see the module docstring on why this is stored and why it is not personal
    #: data. NULL when the transport gave us nothing.
    peer_ip: Mapped[str | None] = mapped_column(sa.String(PEER_IP_LENGTH), nullable=True)
    #: How long we took, in milliseconds. NOT NULL, and measured rather than defaulted: the
    #: rail retries on a slow answer as readily as on a failed one, so a creeping p95 here is
    #: the earliest warning of a duplicate-call storm that would otherwise be discovered as a
    #: pile of refusals.
    duration_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False)
