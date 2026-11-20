
import asyncio
import xml.etree.ElementTree as ET
import httpx

from app.modules.ai.knowledge_sync import (
    MEDLINE_API,
    QUERIES,
    parse_medlineplus_xml,
)


async def main():
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=False,
        headers={"User-Agent": "MEDI-Knowledge-Sync/1.0"},
    ) as client:

        for query in QUERIES:
            print("\n" + "=" * 60)
            print("QUERY:", query)

            try:
                response = await client.get(
                    MEDLINE_API,
                    params={
                        "db": "healthTopics",
                        "term": query,
                        "retmax": 10,
                        "rettype": "topic",
                    },
                )
                response.raise_for_status()

                root = ET.fromstring(response.content)
                docs = root.findall(".//document")

                print("HTTP:", response.status_code)
                print("ROOT:", root.tag)
                print("API COUNT:", root.findtext("count"))
                print("XML DOCUMENTS:", len(docs))

                if docs:
                    doc = docs[0]

                    print("FIRST URL:", doc.attrib.get("url"))
                    print("DOCUMENT ATTRIBUTES:", doc.attrib)

                    for item in doc.findall("content"):
                        content_text = "".join(item.itertext())

                        print("CONTENT ATTRIBUTES:", item.attrib)
                        print("CONTENT PREVIEW:", content_text[:500])

                    print(
                        "CONTENT NODES:",
                        [
                            (
                                item.attrib.get("name"),
                                len("".join(item.itertext()))
                            )
                            for item in doc.findall("content")
                        ],
                    )

                print(
                    "PARSER RECORDS:",
                    len(parse_medlineplus_xml(response.content)),
                )

            except Exception as exc:
                print("ERROR:", type(exc).__name__, str(exc)[:200])


if __name__ == "__main__":
    asyncio.run(main())
