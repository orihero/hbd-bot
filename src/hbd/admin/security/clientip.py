"""Deriving the real client IP from ``X-Forwarded-For``, without trusting the client.

The panel binds to loopback behind a reverse proxy, which is also the compensating control
for having no MFA (ADMIN_PANEL_PLAN §12.1 T13). Behind that proxy every request's peer
address is the proxy, so a per-IP rate limiter collapses into one bucket shared by every
operator and every attacker, and ``last_ip`` records the proxy on every row. Trusting the
header instead is worse: the attacker rotates it per request and the limiter stops
existing at all.

So the header is read **only** when the peer is inside an explicitly configured trusted
CIDR, and even then only the entry ``hops`` places from the right is believed — everything
further left was appended by whoever spoke to the first proxy, which includes the client.
A malformed entry is never returned: it is not "close enough", it is a value an attacker
chose. When the header cannot yield a usable address the peer is used, because a limiter
key that is wrong-but-attacker-controlled is worse than one that is wrong-but-shared.

Everything here is a pure function over primitives. The CIDR list is parsed once at
startup by :func:`parse_trusted_proxies`, which raises ``ConfigError`` like the rest of the
configuration layer, so a typo in ``HBD_ADMIN_TRUSTED_PROXY_CIDRS`` fails the boot rather
than silently trusting nothing (or, worse, everything).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from typing import Final

from hbd.errors import ConfigError

__all__ = [
    "IpNetwork",
    "MAX_FORWARDED_ENTRIES",
    "parse_trusted_proxies",
    "is_trusted_peer",
    "resolve_client_ip",
]

type IpNetwork = IPv4Network | IPv6Network
type _IpAddress = IPv4Address | IPv6Address

#: Only the rightmost few entries can ever be believed, so a header longer than this is
#: truncated from the left before parsing. A proxy chain deeper than 32 does not exist in
#: this deployment; an attacker-supplied 10 000-entry header does.
MAX_FORWARDED_ENTRIES: Final[int] = 32

_FORWARDED_SEPARATOR: Final[str] = ","
_PORT_SEPARATOR: Final[str] = ":"


def parse_trusted_proxies(cidrs: Sequence[str]) -> tuple[IpNetwork, ...]:
    """Parse configured CIDRs. Raises ``ConfigError`` naming the offending entry.

    ``strict=False`` so ``10.0.0.7/24`` is accepted as the network it obviously means
    rather than rejected on a host-bits technicality an operator cannot see.
    """
    networks: list[IpNetwork] = []
    for raw in cidrs:
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            networks.append(ip_network(candidate, strict=False))
        except ValueError as exc:
            raise ConfigError(
                f"HBD_ADMIN_TRUSTED_PROXY_CIDRS contains an unparsable entry: {candidate!r}",
                context={"entry": candidate},
                cause=exc,
            ) from exc
    return tuple(networks)


def _parse_ip(value: str) -> _IpAddress | None:
    """Parse one address, tolerating the forms proxies actually emit. Never raises.

    Handles ``[2001:db8::1]:443`` and ``203.0.113.7:443`` because some proxies append the
    source port, and unwraps IPv4-mapped IPv6 (``::ffff:203.0.113.7``) so the same client
    produces the same limiter key whether it arrived over a v4 or a dual-stack socket.
    """
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("["):
        host, _, _ = candidate.partition("]")
        candidate = host[1:]
    elif candidate.count(_PORT_SEPARATOR) == 1:
        candidate = candidate.split(_PORT_SEPARATOR, 1)[0]
    try:
        parsed = ip_address(candidate)
    except ValueError:
        return None
    if isinstance(parsed, IPv6Address) and parsed.ipv4_mapped is not None:
        return parsed.ipv4_mapped
    return parsed


def is_trusted_peer(peer_ip: str | None, trusted_proxies: Iterable[IpNetwork]) -> bool:
    """True when the transport peer is inside one of the configured proxy networks."""
    parsed = _parse_ip(peer_ip) if peer_ip is not None else None
    if parsed is None:
        return False
    return any(parsed in network for network in trusted_proxies)


def _forwarded_entries(header: str) -> tuple[str, ...]:
    entries = tuple(header.split(_FORWARDED_SEPARATOR))
    return entries[-MAX_FORWARDED_ENTRIES:]


def resolve_client_ip(
    *,
    peer_ip: str | None,
    forwarded_for: str | None,
    trusted_proxies: Sequence[IpNetwork] = (),
    hops: int = 0,
) -> str | None:
    """The address to rate-limit and record, in canonical form.

    ``peer_ip`` is the transport peer (``request.client.host``); ``forwarded_for`` is the
    raw ``X-Forwarded-For`` header, or ``None`` when absent. Returns ``None`` only when the
    peer address itself is missing or unparsable — an unknown address is reported as
    unknown rather than as some other client's.

    The rules, in order:

    1. The peer is not inside ``trusted_proxies`` → the header is ignored entirely.
    2. ``hops`` is 0 → the peer is the client. Zero is the default: with no proxy declared
       there is no reason to read the header at all.
    3. Otherwise: start past the right-hand end of the header and step left exactly
       ``hops`` times. ``hops`` is the number of trusted proxies in front of us, so with
       one proxy (``hops=1``) that is the last entry — the address that proxy itself
       observed, which no client can write. Everything further right does not exist;
       everything further left was supplied by whoever spoke to the outermost proxy. If
       the position does not exist, or does not hold a parsable address, fall back to the
       peer rather than believing a neighbouring entry.
    """
    if hops < 0:
        raise ValueError(f"hops must not be negative, got {hops}")
    peer = _parse_ip(peer_ip) if peer_ip is not None else None
    if peer is None:
        return None
    if hops == 0 or not forwarded_for or not is_trusted_peer(peer_ip, trusted_proxies):
        return str(peer)
    entries = _forwarded_entries(forwarded_for)
    index = len(entries) - hops
    if index < 0:
        return str(peer)
    client = _parse_ip(entries[index])
    return str(client) if client is not None else str(peer)
