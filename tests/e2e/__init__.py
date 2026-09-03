"""The browser gate's server half.

Not collected by pytest — nothing here is named ``test_*``. It is a package so that
``python -m tests.e2e.serve_admin_e2e`` resolves ``tests.test_admin.conftest``'s fixtures
as ordinary imports, and so mypy walks it under the same ``--strict`` as everything else.
"""
