from sqlalchemy import Computed, ForeignKeyConstraint, UniqueConstraint

from app.db import models  # noqa: F401
from app.db.base import Base

EXPECTED_TABLES = {
    "collections",
    "conversations",
    "conversation_citations",
    "conversation_messages",
    "conversation_turns",
    "document_chunks",
    "document_index_generations",
    "document_source_units",
    "document_versions",
    "documents",
    "memberships",
    "organizations",
    "processing_jobs",
    "users",
}


def test_metadata_contains_expected_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_tenant_owned_table_has_a_required_tenant_key() -> None:
    inherited_scope = {"conversation_citations", "conversation_messages"}
    for table_name in EXPECTED_TABLES - {"organizations", "users"} - inherited_scope:
        tenant_column = Base.metadata.tables[table_name].c.tenant_id
        assert tenant_column.nullable is False


def test_tenant_child_links_use_composite_foreign_keys() -> None:
    expected_constraints = {
        ("documents", "fk_documents_tenant_collection"),
        ("document_chunks", "fk_document_chunks_tenant_document"),
        ("document_chunks", "fk_document_chunks_tenant_source_unit"),
        ("document_chunks", "fk_chunks_generation"),
        ("document_source_units", "fk_source_units_tenant_document"),
        ("document_source_units", "fk_source_units_generation"),
        ("document_versions", "fk_document_versions_tenant_document"),
        ("document_index_generations", "fk_generations_tenant_version"),
        ("processing_jobs", "fk_processing_jobs_tenant_document"),
        ("conversations", "fk_conversations_tenant_collection"),
        ("conversations", "fk_conversations_tenant_membership"),
    }

    actual_constraints = {
        (table.name, constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and len(constraint.column_keys) >= 2
    }

    assert expected_constraints <= actual_constraints


def test_scoped_uniqueness_constraints_are_declared() -> None:
    expected_constraints = {
        "uq_collections_tenant_name",
        "uq_document_chunks_generation_index",
        "uq_document_versions_order",
        "uq_document_versions_storage_key",
        "uq_generations_order",
        "uq_memberships_tenant_user",
        "uq_users_issuer_subject",
    }
    actual_constraints = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert expected_constraints <= actual_constraints


def test_search_vector_is_stored_and_uses_explicit_simple_configuration() -> None:
    column = Base.metadata.tables["document_chunks"].c.search_vector
    assert isinstance(column.computed, Computed)
    assert column.computed.persisted is True
    expression = str(column.computed.sqltext)
    assert "'simple'::regconfig" in expression
    assert "section" in expression
    assert "content" in expression
