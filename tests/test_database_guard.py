import pytest

from app.core.test_database import (
    InvalidTestDatabaseConfiguration,
    validate_test_database_url,
)


@pytest.mark.parametrize(
    "value",
    [None, "", "not-a-url", "sqlite+aiosqlite:///medi_test"],
)
def test_test_database_url_requires_explicit_postgresql_url(value):
    with pytest.raises(InvalidTestDatabaseConfiguration):
        validate_test_database_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "postgresql+asyncpg://user:password@db.example.invalid/medi_test",
        "postgresql+asyncpg://user:password@127.0.0.1/medi_db",
        "postgresql+asyncpg://user:password@127.0.0.1/medi_prod_test",
        "postgresql+asyncpg://user:password@127.0.0.1/medi_test?options=-csearch_path%3Dpublic",
    ],
)
def test_test_database_url_rejects_nonisolated_targets(value):
    with pytest.raises(InvalidTestDatabaseConfiguration) as error:
        validate_test_database_url(value)
    assert "password" not in str(error.value)
    assert "db.example.invalid" not in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        "postgresql+asyncpg://test_user:test_password@localhost/medi_unit_test",
        "postgresql+asyncpg://test_user:test_password@[::1]:5432/medi_unit_test",
    ],
)
def test_test_database_url_accepts_local_test_databases(value):
    validated = validate_test_database_url(value)
    assert "medi_unit_test" in validated
