import asyncio
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import DocumentVersion
from app.db.session import dispose_engine, session_factory


async def reconcile_storage() -> tuple[int, int, int]:
    """Return expected, missing, and orphan object counts without exposing keys."""
    root = Path(get_settings().document_storage_path).resolve()
    async with session_factory() as session:
        expected = set(await session.scalars(select(DocumentVersion.storage_key)))
    actual = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    return len(expected), len(expected - actual), len(actual - expected)


def main() -> None:
    try:
        expected, missing, orphaned = asyncio.run(reconcile_storage())
        print(
            f"expected_objects={expected} missing_objects={missing} "
            f"orphan_objects={orphaned}"
        )
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
