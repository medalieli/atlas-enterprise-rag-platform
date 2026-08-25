# Milestone 3 Data Model

The initial schema establishes persistence and tenant-safe relationships only. It does not implement authentication, ingestion behavior, retrieval, embeddings, or conversation memory.

## Tables and relationships

- `organizations` is the tenant root. Its unique slug provides a stable human-readable identifier.
- `users` stores global user identity data without credentials or authentication behavior.
- `memberships` joins users to organizations and assigns a basic member or admin role. A user can belong to an organization only once.
- `collections` groups documents inside one organization. Collection names are unique only within their tenant.
- `documents` stores source-file identity, storage location, media type, size, processing status, safe failure text, and flexible source metadata. Each document belongs to a collection in the same tenant.
- `document_chunks` stores extracted text and traceable page, section, and character-offset metadata. Each chunk belongs to a document in the same tenant and has a unique position within that document. It intentionally has no embedding column yet.
- `processing_jobs` records the state and attempts of work associated with a same-tenant document. Queue execution and retry behavior remain for Milestone 4.
- `conversations` is an organization-scoped container tied to a collection and a current organization member. Messages and conversation-memory behavior remain for Milestone 11.

## Tenant isolation

Every tenant-owned table carries a non-null `tenant_id`. Composite foreign keys include that key when connecting collections, documents, chunks, jobs, conversations, and memberships. PostgreSQL therefore rejects cross-tenant links even if an application query is incorrect.

Tenant-local identifiers used by composite foreign keys have matching unique constraints. Tenant-scoped names, storage keys, and chunk positions are also unique in the database.

## Types and lifecycle decisions

- Primary keys are PostgreSQL UUIDs with database and Python defaults.
- Audit timestamps use timezone-aware PostgreSQL timestamps and database creation defaults.
- Organization deletion cascades through tenant-owned data. User deletion is restricted while memberships exist. Documents cascade to their chunks and jobs. Conversations are deleted with their collection, while their creator membership cannot be removed while referenced.
- JSONB is limited to document and chunk source metadata whose keys vary by file type and parser.
- Status values use named PostgreSQL enums. No embedding dimensions or vector columns are introduced in this milestone.
- Alembic is the only mechanism that creates application tables; application startup never calls `create_all`.
