"""The ``X-Forwarded-For`` matrix. A bug in this file is a forgeable rate limiter.

Everything the login limiter counts, every ``created_ip``/``last_ip`` column, and the
"a session whose IP jumped countries" detection signal read the value this module returns.
The three cases §14 names as acceptance are the first three tests below — no proxy, one
trusted proxy, and a header spoofed by an untrusted peer — and the rest are the ways an
attacker who knows the header exists would try to move the answer: prepending entries,
sending junk, sending a thousand entries, and dressing an address up in a form the parser
might mishandle.
"""

from __future__ import annotations

from ipaddress import ip_network
from typing import Final

import pytest

from bayram.admin.security.clientip import (
    MAX_FORWARDED_ENTRIES,
    is_trusted_peer,
    parse_trusted_proxies,
    resolve_client_ip,
)
from bayram.errors import ConfigError

_PROXY: Final[str] = "10.0.0.9"
_CLIENT: Final[str] = "203.0.113.7"
_ATTACKER: Final[str] = "198.51.100.66"
_TRUSTED: Final[tuple[str, ...]] = ("10.0.0.0/8",)


# ---------------------------------------------------------------------------
# The three acceptance cases
# ---------------------------------------------------------------------------
def test_with_no_proxy_configured_the_peer_is_the_client() -> None:
    assert (
        resolve_client_ip(peer_ip=_CLIENT, forwarded_for=None, trusted_proxies=(), hops=0)
        == _CLIENT
    )


def test_one_trusted_proxy_at_one_hop_yields_the_client_it_saw() -> None:
    assert (
        resolve_client_ip(
            peer_ip=_PROXY,
            forwarded_for=_CLIENT,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=1,
        )
        == _CLIENT
    )


def test_a_header_from_an_untrusted_peer_is_ignored_entirely() -> None:
    """The whole attack: a direct caller claiming to be somebody else."""
    assert (
        resolve_client_ip(
            peer_ip=_ATTACKER,
            forwarded_for=_CLIENT,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=1,
        )
        == _ATTACKER
    )


# ---------------------------------------------------------------------------
# Everything an attacker who knows about the header would try
# ---------------------------------------------------------------------------
def test_entries_the_client_prepended_are_never_believed() -> None:
    """With one trusted proxy only the rightmost entry was written by that proxy."""
    forwarded = f"{_ATTACKER}, {_CLIENT}"

    assert (
        resolve_client_ip(
            peer_ip=_PROXY,
            forwarded_for=forwarded,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=1,
        )
        == _CLIENT
    )


def test_two_hops_walk_two_entries_left() -> None:
    forwarded = f"{_CLIENT}, 10.0.0.44"

    assert (
        resolve_client_ip(
            peer_ip=_PROXY,
            forwarded_for=forwarded,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=2,
        )
        == _CLIENT
    )


def test_zero_hops_never_reads_the_header_even_from_a_trusted_peer() -> None:
    """``hops`` defaults to 0, and the default must not trust a header at all."""
    assert (
        resolve_client_ip(
            peer_ip=_PROXY,
            forwarded_for=_CLIENT,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=0,
        )
        == _PROXY
    )


@pytest.mark.parametrize(
    "forwarded",
    ["not-an-ip", "", "   ", "999.999.999.999", "<script>", "203.0.113.7 203.0.113.8"],
)
def test_a_malformed_entry_falls_back_to_the_peer_and_is_never_returned(forwarded: str) -> None:
    resolved = resolve_client_ip(
        peer_ip=_PROXY,
        forwarded_for=forwarded,
        trusted_proxies=parse_trusted_proxies(_TRUSTED),
        hops=1,
    )

    assert resolved == _PROXY


def test_a_chain_shorter_than_the_configured_hops_falls_back_to_the_peer() -> None:
    assert (
        resolve_client_ip(
            peer_ip=_PROXY,
            forwarded_for=_CLIENT,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=3,
        )
        == _PROXY
    )


def test_a_flood_of_entries_is_truncated_from_the_left() -> None:
    """A 10 000-entry header is a parser workload, not a proxy chain."""
    forwarded = ", ".join([_ATTACKER] * (MAX_FORWARDED_ENTRIES * 4) + [_CLIENT])

    assert (
        resolve_client_ip(
            peer_ip=_PROXY,
            forwarded_for=forwarded,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=1,
        )
        == _CLIENT
    )


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (f"{_CLIENT}:44321", _CLIENT),
        ("[2001:db8::1]:44321", "2001:db8::1"),
        ("[2001:db8::1]", "2001:db8::1"),
        ("2001:db8::1", "2001:db8::1"),
        ("::ffff:203.0.113.7", _CLIENT),
        (f"  {_CLIENT}  ", _CLIENT),
    ],
)
def test_the_forms_proxies_actually_emit_are_normalised(entry: str, expected: str) -> None:
    """Same client, same limiter bucket, whichever shape the proxy wrote it in."""
    assert (
        resolve_client_ip(
            peer_ip=_PROXY,
            forwarded_for=entry,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=1,
        )
        == expected
    )


def test_an_ipv4_mapped_peer_is_trusted_by_its_ipv4_network() -> None:
    assert is_trusted_peer("::ffff:10.0.0.9", parse_trusted_proxies(_TRUSTED)) is True


@pytest.mark.parametrize("peer", [None, "", "not-an-ip"])
def test_an_unusable_peer_is_reported_as_unknown_not_as_someone_else(peer: str | None) -> None:
    assert (
        resolve_client_ip(
            peer_ip=peer,
            forwarded_for=_CLIENT,
            trusted_proxies=parse_trusted_proxies(_TRUSTED),
            hops=1,
        )
        is None
    )


def test_negative_hops_is_a_configuration_bug_and_raises() -> None:
    with pytest.raises(ValueError, match="hops"):
        resolve_client_ip(peer_ip=_PROXY, forwarded_for=None, trusted_proxies=(), hops=-1)


# ---------------------------------------------------------------------------
# Parsing the configured CIDR list
# ---------------------------------------------------------------------------
def test_trusted_cidrs_parse_and_blank_entries_are_skipped() -> None:
    networks = parse_trusted_proxies(("10.0.0.0/8", "  ", "2001:db8::/32", "127.0.0.1"))

    assert networks == (
        ip_network("10.0.0.0/8"),
        ip_network("2001:db8::/32"),
        ip_network("127.0.0.1/32"),
    )


def test_host_bits_are_accepted_rather_than_rejected_on_a_technicality() -> None:
    assert parse_trusted_proxies(("10.0.0.7/24",)) == (ip_network("10.0.0.0/24"),)


def test_an_unparsable_cidr_fails_the_boot_and_names_the_entry() -> None:
    """Silently trusting nothing is a limiter that shares one bucket; say so at startup."""
    with pytest.raises(ConfigError) as caught:
        parse_trusted_proxies(("10.0.0.0/8", "10.0.0.0/pizza"))

    assert "10.0.0.0/pizza" in caught.value.operator_message


def test_an_empty_trusted_list_trusts_nobody() -> None:
    assert is_trusted_peer(_PROXY, ()) is False


@pytest.mark.parametrize("peer", [None, "", "10.0.0.9.9", "localhost"])
def test_a_peer_that_is_not_an_address_is_never_trusted(peer: str | None) -> None:
    """A hostname is not an address: resolving one here would be a DNS-controlled bypass."""
    assert is_trusted_peer(peer, parse_trusted_proxies(_TRUSTED)) is False
