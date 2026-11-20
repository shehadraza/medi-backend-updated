"""Fail-closed validation for explicitly selected isolated PostgreSQL test DBs."""

from sqlalchemy.engine import make_url


class InvalidTestDatabaseConfiguration(ValueError):
    """The test database target is missing or does not meet isolation rules."""


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_test_database_url(value: str | None) -> str:
    """Validate a local PostgreSQL URL without including it in errors."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidTestDatabaseConfiguration(
            "MEDI_TEST_DATABASE_URL must explicitly identify an isolated test database."
        )

    try:
        url = make_url(value.strip())
    except Exception as exc:
        raise InvalidTestDatabaseConfiguration(
            "MEDI_TEST_DATABASE_URL is not a valid database URL."
        ) from exc

    if url.drivername != "postgresql+asyncpg":
        raise InvalidTestDatabaseConfiguration(
            "The test database must use the PostgreSQL asyncpg driver."
        )

    host = (url.host or "").casefold()
    if host not in _LOOPBACK_HOSTS:
        raise InvalidTestDatabaseConfiguration(
            "The test database host must be local loopback."
        )

    database = url.database or ""
    normalized_database = database.casefold()
    if (
        not normalized_database.endswith("_test")
        or normalized_database in {"medi_db", "medi_prod_test", "medi_production_test"}
        or "prod" in normalized_database
        or not normalized_database.replace("_", "").isalnum()
    ):
        raise InvalidTestDatabaseConfiguration(
            "The test database name must be an isolated name ending in '_test'."
        )

    query_keys = {str(key).casefold() for key in url.query}
    if query_keys.intersection({"options", "search_path", "currentschema"}):
        raise InvalidTestDatabaseConfiguration(
            "The test database URL must not override the PostgreSQL schema or search path."
        )

    return url.render_as_string(hide_password=False)
