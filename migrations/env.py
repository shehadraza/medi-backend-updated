
import asyncio
import app.models.notification
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.db.base import Base
from app.models.password_reset import PasswordResetToken
from app.models.email_verification import EmailVerificationToken

# Import models so Alembic can detect their tables
from app.models.user import User
from app.models.session import UserSession
from app.models.health_profile import HealthProfile
from app.models.health_checkin import DailyHealthCheckIn
from app.models.medication import (
    Prescription,
    PrescriptionItem,
    Medication,
    MedicationSchedule,
    MedicationLog,
)
from app.models.medicine_catalog import MedicineCatalog
from app.models.ai import (
    AIConversation,
    AIMessage,
    AIMessageFeedback,
    KnowledgeSource,
    KnowledgeDocument,
    KnowledgeChunk,
    KnowledgeSyncState,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Keep database credentials in .env, not alembic.ini
config.set_main_option(
    "sqlalchemy.url",
    settings.DATABASE_URL.replace("%", "%%"),
)

target_metadata = Base.metadata


def run_migrations_offline():
    url = settings.DATABASE_URL

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
