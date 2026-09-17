"""What a route *does*, separated from how it is spelled on the wire.

A router in this package is a straight line: parse, delegate, render. Everything with a
decision in it — the reveal gate, the object key, the byte range — lives here, so it can be
unit-tested without an ASGI client and so no two routes can grow two answers to the same
question.

The one rule that shapes every module here: **a service never reaches for a concrete
implementation.** It takes ``bayram.contracts.Storage``, not ``LocalFileStorage``; it takes
``WindowCounterStore``, not a Redis client. §12.7 is the reason — the panel resolves an
object key through a public protocol member and never through a private method of whatever
backend happens to be mounted today.
"""

from __future__ import annotations
