"""Optional scheduled trusted knowledge source synchronization worker."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.ai import KnowledgeSource, KnowledgeSyncState
from app.modules.ai.knowledge_sync import sync_medlineplus, sync_pubmed
from app.modules.ai.source_adapters import SOURCE_ADAPTERS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medi.knowledge_sync")


async def run_sync_cycle() -> bool:
    if not settings.AI_KNOWLEDGE_SYNC_ENABLED:
        return False
    completed = False
    sync_functions = {"medlineplus": sync_medlineplus, "pubmed": sync_pubmed}
    adapters = [
        (adapter.display_name, adapter.source_url, sync_functions[adapter.key])
        for adapter in SOURCE_ADAPTERS
        if adapter.key in sync_functions and adapter.acquisition_enabled
    ]
    for name, source_url, synchronize in adapters:
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(select(KnowledgeSource.id).where(
                    KnowledgeSource.name == name,
                    KnowledgeSource.source_url == source_url,
                ))
                source_id = result.scalar_one_or_none()
                if source_id:
                    state = await db.get(KnowledgeSyncState, source_id)
                    if state and state.next_sync_at and state.next_sync_at > datetime.now(timezone.utc):
                        continue
                counts = await synchronize(db)
                logger.info(
                    "Trusted knowledge sync completed for %s: seen=%s created=%s unchanged=%s metadata_updated=%s out_of_order=%s",
                    name, counts["seen"], counts["created"], counts["unchanged"], counts["metadata_updated"], counts["out_of_order"],
                )
                completed = True
            except Exception:
                logger.warning("Trusted knowledge synchronization failed for %s; sanitized status was recorded.", name)
    return completed


async def seconds_until_next_sync() -> float:
    async with AsyncSessionLocal() as db:
        try:
            names = [
                (adapter.display_name, adapter.source_url)
                for adapter in SOURCE_ADAPTERS
                if adapter.acquisition_enabled
            ]
            delays = []
            for name, source_url in names:
                result = await db.execute(select(KnowledgeSource.id).where(
                    KnowledgeSource.name == name, KnowledgeSource.source_url == source_url,
                ))
                source_id = result.scalar_one_or_none()
                state = await db.get(KnowledgeSyncState, source_id) if source_id else None
                if state and state.next_sync_at:
                    delays.append((state.next_sync_at - datetime.now(timezone.utc)).total_seconds())
                elif state is None:
                    delays.append(1.0)
            if delays:
                return max(1.0, min(delays))
        except Exception:
            return float(settings.AI_KNOWLEDGE_SYNC_RETRY_SECONDS)
    return 1.0


async def main() -> None:
    if not settings.AI_KNOWLEDGE_SYNC_ENABLED:
        raise RuntimeError("AI_KNOWLEDGE_SYNC_ENABLED must be enabled to start this worker.")
    try:
        while True:
            await run_sync_cycle()
            delay = await seconds_until_next_sync()
            await asyncio.sleep(delay)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
