
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.db.session import engine, get_db
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.models.user import User


@pytest_asyncio.fixture(loop_scope="session")
async def admin_api_client(monkeypatch):
    super_admin_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    unverified_id = str(uuid.uuid4())
    regular_admin_id = str(uuid.uuid4())

    super_admin_email = f"super-{super_admin_id}@example.com"

    monkeypatch.setattr(
        settings,
        "MEDI_SUPER_ADMIN_EMAIL",
        super_admin_email,
    )

    actor = {}

    async with engine.connect() as connection:
        transaction = await connection.begin()

        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as db:

                super_admin = User(
                    id=super_admin_id,
                    full_name="Test Super Admin",
                    email=super_admin_email,
                    password_hash="test-only-password",
                    is_active=True,
                    is_verified=True,
                    is_admin=True,
                    role="super_admin",
                )

                target = User(
                    id=target_id,
                    full_name="Target User",
                    email=f"target-{target_id}@example.com",
                    password_hash="test-only-password",
                    is_active=True,
                    is_verified=True,
                    is_admin=False,
                    role="user",
                )

                unverified = User(
                    id=unverified_id,
                    full_name="Unverified User",
                    email=f"unverified-{unverified_id}@example.com",
                    password_hash="test-only-password",
                    is_active=True,
                    is_verified=False,
                    is_admin=False,
                    role="user",
                )

                regular_admin = User(
                    id=regular_admin_id,
                    full_name="Regular Admin",
                    email=f"admin-{regular_admin_id}@example.com",
                    password_hash="test-only-password",
                    is_active=True,
                    is_verified=True,
                    is_admin=True,
                    role="admin",
                )

                db.add_all([
                    super_admin,
                    target,
                    unverified,
                    regular_admin,
                ])

                await db.flush()

                actor["user"] = super_admin

                async def override_get_db():
                    yield db

                async def override_get_current_user():
                    return actor["user"]

                app.dependency_overrides[get_db] = override_get_db
                app.dependency_overrides[
                    get_current_user
                ] = override_get_current_user

                transport = ASGITransport(app=app)

                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                ) as client:
                    yield {
                        "client": client,
                        "db": db,
                        "super_admin": super_admin,
                        "target": target,
                        "unverified": unverified,
                        "regular_admin": regular_admin,
                        "actor": actor,
                    }

        finally:
            app.dependency_overrides.clear()

            if transaction.is_active:
                await transaction.rollback()


@pytest.mark.asyncio(loop_scope="session")
async def test_super_admin_can_list_users(admin_api_client):
    client = admin_api_client["client"]

    response = await client.get("/admin/users")

    assert response.status_code == 200
    assert response.json()["total"] >= 4


@pytest.mark.asyncio(loop_scope="session")
async def test_knowledge_source_monitoring_is_super_admin_only_and_sanitized(admin_api_client):
    client = admin_api_client["client"]
    class EmptyResult:
        def scalar_one_or_none(self):
            return None

        def all(self):
            return []

    class ReadOnlyEmptyDB:
        async def execute(self, statement):
            return EmptyResult()

        async def get(self, model, key):
            return None

    async def override_empty_db():
        yield ReadOnlyEmptyDB()

    app.dependency_overrides[get_db] = override_empty_db
    response = await client.get("/admin/knowledge-sources-status")

    assert response.status_code == 200
    body = response.json()
    assert body["worker_enabled"] in (True, False)
    assert {source["key"] for source in body["sources"]} == {"medlineplus", "pubmed"}
    assert all("document_counts" in source for source in body["sources"])
    pubmed = next(source for source in body["sources"] if source["key"] == "pubmed")
    assert pubmed["acquisition_enabled"] is False
    assert pubmed["user_facing_enabled"] is False
    assert "patient" not in response.text.casefold()
    assert "credential" not in response.text.casefold()

    admin_api_client["actor"]["user"] = admin_api_client["regular_admin"]
    denied = await client.get("/admin/knowledge-sources-status")
    assert denied.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_super_admin_can_grant_admin_access(admin_api_client):
    client = admin_api_client["client"]
    target = admin_api_client["target"]

    response = await client.post(
        f"/admin/users/{target.id}/grant"
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["user"]["is_admin"] is True

    await admin_api_client["db"].refresh(target)

    assert target.role == "admin"
    assert target.is_admin is True


@pytest.mark.asyncio(loop_scope="session")
async def test_super_admin_can_revoke_admin_access(admin_api_client):
    client = admin_api_client["client"]
    target = admin_api_client["target"]

    target.role = "admin"
    target.is_admin = True
    await admin_api_client["db"].flush()

    response = await client.post(
        f"/admin/users/{target.id}/revoke"
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"
    assert response.json()["user"]["is_admin"] is False

    await admin_api_client["db"].refresh(target)

    assert target.role == "user"
    assert target.is_admin is False


@pytest.mark.asyncio(loop_scope="session")
async def test_regular_user_cannot_access_admin_api(admin_api_client):
    client = admin_api_client["client"]
    admin_api_client["actor"]["user"] = admin_api_client["target"]

    response = await client.get("/admin/users")

    assert response.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_regular_admin_cannot_grant_admin_access(admin_api_client):
    client = admin_api_client["client"]
    admin_api_client["actor"]["user"] = (
        admin_api_client["regular_admin"]
    )

    target = admin_api_client["target"]

    response = await client.post(
        f"/admin/users/{target.id}/grant"
    )

    assert response.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_super_admin_cannot_grant_access_to_unverified_user(
    admin_api_client,
):
    client = admin_api_client["client"]
    unverified = admin_api_client["unverified"]

    response = await client.post(
        f"/admin/users/{unverified.id}/grant"
    )

    assert response.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_super_admin_cannot_modify_own_access(admin_api_client):
    client = admin_api_client["client"]
    super_admin = admin_api_client["super_admin"]

    grant_response = await client.post(
        f"/admin/users/{super_admin.id}/grant"
    )

    revoke_response = await client.post(
        f"/admin/users/{super_admin.id}/revoke"
    )

    assert grant_response.status_code == 403
    assert revoke_response.status_code == 403

    await admin_api_client["db"].refresh(super_admin)

    assert super_admin.role == "super_admin"
    assert super_admin.is_admin is True


@pytest.mark.asyncio(loop_scope="session")
async def test_grant_nonexistent_user_returns_404(admin_api_client):
    client = admin_api_client["client"]

    response = await client.post(
        f"/admin/users/{uuid.uuid4()}/grant"
    )

    assert response.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_revoke_user_without_admin_access_returns_409(
    admin_api_client,
):
    client = admin_api_client["client"]
    target = admin_api_client["target"]

    response = await client.post(
        f"/admin/users/{target.id}/revoke"
    )

    assert response.status_code == 409
