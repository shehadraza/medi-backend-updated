
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from app.core.config import settings

# Match run_dev.py: force this diagnostic to medi_dev.
dev_url = make_url(settings.DATABASE_URL).set(database="medi_dev")
settings.DATABASE_URL = dev_url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = settings.DATABASE_URL

# Import engine only after database override.
from app.db.session import engine


async def main():
    async with engine.connect() as conn:
        database = await conn.scalar(text("SELECT current_database()"))
        print("Verified diagnostic database:", database)

        if database != "medi_dev":
            raise RuntimeError("Refusing to diagnose a database other than medi_dev.")

        query = text("""
            SELECT
                (SELECT COUNT(*) FROM ai_knowledge_sources) AS total_sources,
                (SELECT COUNT(*) FROM ai_knowledge_documents) AS total_documents,
                (SELECT COUNT(*) FROM ai_knowledge_chunks) AS total_chunks,

                COUNT(c.id) FILTER (
                    WHERE s.review_status = 'approved'
                      AND d.status = 'published'
                      AND NOT (
                          s.name = 'PubMed via NCBI E-utilities'
                          OR s.source_url = 'https://pubmed.ncbi.nlm.nih.gov/'
                          OR COALESCE(LOWER(d.source_url), '') LIKE
                             'https://pubmed.ncbi.nlm.nih.gov/%'
                      )
                ) AS eligible_chunks,

                COUNT(c.id) FILTER (
                    WHERE s.review_status = 'approved'
                      AND d.status = 'published'
                      AND c.text ILIKE '%পানি%'
                      AND NOT (
                          s.name = 'PubMed via NCBI E-utilities'
                          OR s.source_url = 'https://pubmed.ncbi.nlm.nih.gov/'
                          OR COALESCE(LOWER(d.source_url), '') LIKE
                             'https://pubmed.ncbi.nlm.nih.gov/%'
                      )
                ) AS bengali_water_matches,

                COUNT(c.id) FILTER (
                    WHERE s.review_status = 'approved'
                      AND d.status = 'published'
                      AND to_tsvector('simple', c.text)
                          @@ websearch_to_tsquery(
                              'simple',
                              'পানি কম পান করলে কী সমস্যা হতে পারে?'
                          )
                      AND NOT (
                          s.name = 'PubMed via NCBI E-utilities'
                          OR s.source_url = 'https://pubmed.ncbi.nlm.nih.gov/'
                          OR COALESCE(LOWER(d.source_url), '') LIKE
                             'https://pubmed.ncbi.nlm.nih.gov/%'
                      )
                ) AS bengali_fulltext_matches

            FROM ai_knowledge_chunks c
            JOIN ai_knowledge_documents d ON d.id = c.document_id
            JOIN ai_knowledge_sources s ON s.id = d.source_id
        """)

        result = (await conn.execute(query)).mappings().one()

        print("\n--- MEDI KNOWLEDGE DIAGNOSTICS ---")
        for key, value in result.items():
            print(f"{key}: {value}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
