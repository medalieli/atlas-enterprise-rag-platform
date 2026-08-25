import argparse
import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.embedding_backfill import embed_pending_document
from app.embeddings import create_embedding_provider


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed pending chunks for one document"
    )
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("document_id", type=UUID)
    args = parser.parse_args()
    settings = get_settings()
    count = await embed_pending_document(
        args.tenant_id,
        args.document_id,
        settings,
        create_embedding_provider(settings),
    )
    print(f"Embedded {count} pending chunks")


if __name__ == "__main__":
    asyncio.run(main())
