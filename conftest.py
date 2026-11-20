"""Install a validated isolated test DB URL before test modules import the app."""

import os
import sys

import pytest

from app.core.test_database import (
    InvalidTestDatabaseConfiguration,
    validate_test_database_url,
)


if "app.core.config" in sys.modules or "app.db.session" in sys.modules:
    raise pytest.UsageError(
        "Application database settings loaded before the test database guard."
    )

try:
    _test_database_url = validate_test_database_url(
        os.environ.get("MEDI_TEST_DATABASE_URL")
    )
except InvalidTestDatabaseConfiguration as exc:
    raise pytest.UsageError(str(exc)) from None

# Test mode disables dotenv loading; the explicit test URL is the only DB URL.
os.environ["MEDI_TEST_MODE"] = "1"
os.environ["DATABASE_URL"] = _test_database_url
# Isolated tests use a fixed non-production key; never inherit an application key.
os.environ["ENCRYPTION_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
del _test_database_url
