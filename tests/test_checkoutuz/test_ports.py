"""``bayram.checkoutuz.ports``: the rail's leaf vocabulary and the one tiyin-to-som conversion.

checkout.uz takes SOM in ``1_000..10_000_000`` and this system stores TIYIN, so
:func:`som_from_minor` refuses — never rounds — anything that is not a whole, in-range number
of som (``DECISIONS.md D28``).
"""

from __future__ import annotations

import pytest

from bayram.checkoutuz import ports
from bayram.checkoutuz.ports import (
    CHECKOUTUZ_PROVIDER_NAME,
    MAX_AMOUNT_SOM,
    MIN_AMOUNT_SOM,
    CheckoutUzStatus,
    som_from_minor,
)
from bayram.contracts import Err, Ok
from bayram.errors import CheckoutError


@pytest.mark.parametrize(
    ("amount_minor", "som"),
    [
        (1_500_000, 15_000),
        (4_900_000, 49_000),
        (MIN_AMOUNT_SOM * 100, MIN_AMOUNT_SOM),
        (MAX_AMOUNT_SOM * 100, MAX_AMOUNT_SOM),
    ],
)
def test_a_whole_in_range_amount_converts_exactly(amount_minor: int, som: int) -> None:
    result = som_from_minor(amount_minor)

    assert isinstance(result, Ok)
    assert result.value == som


@pytest.mark.parametrize(
    "amount_minor",
    [
        1_500_050,  # a tiyin remainder: refuse, never round
        99_900,  # 999 som, below the floor
        1_000_000_100,  # 10_000_001 som, above the ceiling
        0,
        -1_500_000,
        MIN_AMOUNT_SOM * 100 - 100,
    ],
)
def test_an_unpayable_amount_is_refused_as_a_checkout_error(amount_minor: int) -> None:
    result = som_from_minor(amount_minor)

    assert isinstance(result, Err)
    assert isinstance(result.error, CheckoutError)
    assert result.error.is_retryable is False


def test_a_bool_is_not_a_price() -> None:
    assert isinstance(som_from_minor(True), Err)


def test_the_vocabulary_is_the_decided_one() -> None:
    assert CHECKOUTUZ_PROVIDER_NAME == "checkoutuz"
    assert (MIN_AMOUNT_SOM, MAX_AMOUNT_SOM) == (1_000, 10_000_000)
    assert ports.LINK_REUSE_MARGIN_S == 60
    assert ports.POLL_GRACE_S == 900
    assert CheckoutUzStatus("pending") is CheckoutUzStatus.PENDING
    assert CheckoutUzStatus("paid") is CheckoutUzStatus.PAID


def test_the_ports_module_imports_no_http_client_and_no_database() -> None:
    # The leaf every other checkout.uz module shares; it must stay importable anywhere.
    import ast
    from pathlib import Path

    tree = ast.parse(Path(ports.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not {name for name in imported if name.startswith(("httpx", "bayram.db", "redis"))}
