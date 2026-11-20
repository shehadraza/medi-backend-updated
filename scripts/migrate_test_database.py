"""Explicitly migrate only a validated, local MEDI test database."""

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.test_database import (  # noqa: E402
    InvalidTestDatabaseConfiguration,
    validate_test_database_url,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Alembic migrations against an isolated local test database."
    )
    parser.add_argument(
        "--upgrade-head",
        action="store_true",
        help="Explicitly authorize upgrading the validated test database to head.",
    )
    args = parser.parse_args()
    if not args.upgrade_head:
        parser.error("--upgrade-head is required; no migration was run.")

    try:
        test_url = validate_test_database_url(
            os.environ.get("MEDI_TEST_DATABASE_URL")
        )
    except InvalidTestDatabaseConfiguration as exc:
        parser.error(str(exc))

    if "app.core.config" in sys.modules or "app.db.session" in sys.modules:
        parser.error("Application database settings loaded before test URL validation.")

    # Alembic's existing env.py reads DATABASE_URL through Settings. Install
    # only the already-validated test URL before importing Alembic or app config.
    os.environ["MEDI_TEST_MODE"] = "1"
    os.environ["DATABASE_URL"] = test_url

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    print("Isolated test database schema is at Alembic head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
