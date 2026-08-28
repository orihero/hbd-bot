"""The never-throw boundary for every persistence call.

``KitRepository`` promises that no method raises. That promise is kept in exactly one
place — here — so no repository method carries its own ``try``/``except`` and none of them
can drift apart on what an ``IntegrityError`` means.

The translation is deliberate, not a catch-all:

* ``IntegrityError`` is **terminal**. A duplicate key or a violated check will fail
  identically forever; retrying it burns the retry budget the transient failures need.
* every other ``SQLAlchemyError`` is **retryable** — a dropped connection, a lock timeout,
  a failed-over primary all look like this and all succeed on the next attempt.
* a pydantic failure means a stored row no longer matches the schema we read it with.
  That is a data-integrity bug, not a transport hiccup, so it is terminal and loud.
* an ``HbdError`` raised by the mapping layer is already typed and passes through intact.

Nothing is swallowed: every branch logs the operation, its context and the cause before
returning the ``Err``.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from hbd.contracts import Result, err, ok
from hbd.errors import HbdError, NotFoundError, StorageError, ValidationError
from hbd.logging import get_logger

__all__ = ["run_guarded", "NotFoundError", "not_found"]

_log = get_logger(__name__)


def not_found(entity: str, **context: Any) -> NotFoundError:
    """Build the standard not-found error for ``entity``."""
    return NotFoundError(f"{entity} not found", context={"entity": entity, **context})


async def run_guarded[T](
    operation: str,
    factory: Callable[[], Coroutine[Any, Any, T]],
    **context: Any,
) -> Result[T]:
    """Run ``factory()`` and convert any failure into a typed ``Err``.

    ``factory`` is a zero-argument callable rather than an awaitable so the coroutine is
    created inside the ``try``. Creating it outside would leave an un-awaited coroutine
    behind on an early failure, which Python reports as a warning at an unrelated moment.
    """
    try:
        return ok(await factory())
    except NotFoundError as exc:
        # An expected answer, not an incident: the idempotency probe asks for a kit that
        # does not exist yet on every single order. A traceback here is pure noise.
        _log.debug("db row not found", extra={"operation": operation, **context})
        return err(exc)
    except HbdError as exc:
        # exc_info is how the JSON formatter picks the error up into its "error" field.
        _log.warning("db operation failed", extra={"operation": operation, **context}, exc_info=exc)
        return err(exc)
    except IntegrityError as exc:
        # Annotated as the base type because the three branches below build different
        # subclasses into the same name; without it mypy pins the type to the first one.
        error: HbdError = StorageError(
            f"{operation} violated a database constraint",
            is_retryable=False,
            context={"operation": operation, "detail": str(exc.orig), **context},
            cause=exc,
        )
        _log.error(
            "db constraint violated", extra={"operation": operation, **context}, exc_info=exc
        )
        return err(error)
    except SQLAlchemyError as exc:
        error = StorageError(
            f"{operation} failed against the database",
            context={"operation": operation, "detail": str(exc), **context},
            cause=exc,
        )
        _log.error("db operation errored", extra={"operation": operation, **context}, exc_info=exc)
        return err(error)
    except PydanticValidationError as exc:
        error = ValidationError(
            f"{operation} read a row that no longer matches its schema",
            context={"operation": operation, "issue_count": len(exc.errors()), **context},
            cause=exc,
        )
        _log.error(
            "db row failed validation", extra={"operation": operation, **context}, exc_info=exc
        )
        return err(error)
