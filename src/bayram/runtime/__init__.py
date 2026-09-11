"""The composition root: where protocols meet concrete vendors.

Everything below this package depends on a ``Protocol``. Everything in it depends on the
implementations. That is the whole point — no handler, stage or adapter imports another
vendor, so ``BAYRAM_USE_FAKE_PROVIDERS=1`` can swap all six of them at once and the rest of
the application does not notice.
"""

from __future__ import annotations

from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.jobs import build_kit_worker_settings, generate_and_deliver
from bayram.runtime.providers import ProviderSet, build_provider_set
from bayram.runtime.startup import verify_host
from bayram.runtime.submitter import ArqOrderSubmitter, InProcessOrderSubmitter

__all__ = [
    "AppContainer",
    "build_container",
    "ProviderSet",
    "build_provider_set",
    "ArqOrderSubmitter",
    "InProcessOrderSubmitter",
    "generate_and_deliver",
    "build_kit_worker_settings",
    "verify_host",
]
