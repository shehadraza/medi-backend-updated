
from pathlib import Path
import shutil

path = Path("app/modules/ai/knowledge_sync.py")

if not path.exists():
    raise SystemExit("ERROR: knowledge_sync.py not found.")

source = path.read_text(encoding="utf-8")
original = source

# 1. Ensure embedding provider import exists.
import_line = (
    "from app.modules.ai.embeddings.factory import get_embedding_provider"
)

if import_line not in source:
    anchor = "from app.modules.ai.rag.ingestion import ingest_document"
    if anchor not in source:
        raise SystemExit("ERROR: Could not locate import section.")
    source = source.replace(
        anchor,
        anchor + "\n" + import_line,
        1,
    )

# 2. Move provider initialization outside the disabled PubMed branch.
wrong = (
    '        return {\n'
    '            "seen": 0,\n'
    '            "created": 0,\n'
    '            "unchanged": 0,\n'
    '            "metadata_updated": 0,\n'
    '            "out_of_order": 0,\n'
    '            "skipped": 1,\n'
    '            "disabled": 1,\n'
    '        }\n'
    '        embedding_provider = get_embedding_provider()\n'
    '    state = await db.get(KnowledgeSyncState, source_id)'
)

correct = (
    '        return {\n'
    '            "seen": 0,\n'
    '            "created": 0,\n'
    '            "unchanged": 0,\n'
    '            "metadata_updated": 0,\n'
    '            "out_of_order": 0,\n'
    '            "skipped": 1,\n'
    '            "disabled": 1,\n'
    '        }\n'
    '\n'
    '    embedding_provider = get_embedding_provider()\n'
    '    state = await db.get(KnowledgeSyncState, source_id)'
)

if wrong in source:
    source = source.replace(wrong, correct, 1)
elif "    embedding_provider = get_embedding_provider()" not in source:
    raise SystemExit("ERROR: Could not safely locate provider initialization.")

# 3. Pass provider to the updated-document ingestion.
old_update = (
    '                await ingest_document(\n'
    '                    db,\n'
    '                    same,\n'
    '                    normalized.encode("utf-8"),\n'
    '                    "document.txt",\n'
    '                )'
)

new_update = (
    '                await ingest_document(\n'
    '                    db,\n'
    '                    same,\n'
    '                    normalized.encode("utf-8"),\n'
    '                    "document.txt",\n'
    '                    embedding_provider=embedding_provider,\n'
    '                )'
)

if old_update in source:
    source = source.replace(old_update, new_update, 1)
elif new_update not in source:
    raise SystemExit("ERROR: Updated-document ingestion block not found.")

# 4. Pass provider to new-document ingestion.
old_new = (
    '        await ingest_document(\n'
    '            db,\n'
    '            document,\n'
    '            normalized.encode("utf-8"),\n'
    '            "document.txt",\n'
    '        )'
)

new_new = (
    '        await ingest_document(\n'
    '            db,\n'
    '            document,\n'
    '            normalized.encode("utf-8"),\n'
    '            "document.txt",\n'
    '            embedding_provider=embedding_provider,\n'
    '        )'
)

if old_new in source:
    source = source.replace(old_new, new_new, 1)
elif new_new not in source:
    raise SystemExit("ERROR: New-document ingestion block not found.")

# 5. Verify both ingestion calls are connected.
if source.count("embedding_provider=embedding_provider") != 2:
    raise SystemExit("ERROR: Expected exactly two provider-enabled ingestion calls.")

if source == original:
    print("No changes required; provider integration already exists.")
else:
    backup = path.with_suffix(".py.backup")
    shutil.copy2(path, backup)
    path.write_text(source, encoding="utf-8")
    print("SUCCESS: knowledge_sync.py updated.")
    print(f"BACKUP: {backup}")

