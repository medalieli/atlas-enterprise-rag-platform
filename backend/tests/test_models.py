from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.db import models  # noqa: F401
from app.db.base import Base

EXPECTED_TABLES = {
    "collections",
    "conversations",
    "document_chunks",
    "documents",
    "memberships",
    "organizations",
    "processing_jobs",
    "users",
}


def test_metadata_contains_only_milestone_3_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_tenant_owned_table_has_a_required_tenant_key() -> None:
    for table_name in EXPECTED_TABLES - {"organizations", "users"}:
        tenant_column = Base.metadata.tables[table_name].c.tenant_id
        assert tenant_column.nullable is False


def test_tenant_child_links_use_composite_foreign_keys() -> None:
    expected_constraints = {
        ("documents", "fk_documents_tenant_collection"),
        ("document_chunks", "fk_document_chunks_tenant_document"),
        ("processing_jobs", "fk_processing_jobs_tenant_document"),
        ("conversations", "fk_conversations_tenant_collection"),
        ("conversations", "fk_conversations_tenant_membership"),
    }

    actual_constraints = {
        (table.name, constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and len(constraint.column_keys) == 2
    }

    assert expected_constraints <= actual_constraints


def test_scoped_uniqueness_constraints_are_declared() -> None:
    expected_constraints = {
        "uq_collections_tenant_name",
        "uq_document_chunks_tenant_document_index",
        "uq_documents_tenant_storage_key",
        "uq_memberships_tenant_user",
    }
    actual_constraints = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert expected_constraints <= actual_constraints
