# Project Roadmap

Statuses: **Milestones 1–9 — completed.** Milestones 10–15 — pending.

## 1. Repository foundation — Completed

**Goal:** Establish the product source of truth, milestone sequence, repository conventions, configuration placeholders, and empty component boundaries.

**Acceptance criteria:** Required foundation files and directories exist; documentation agrees that no application is implemented; environment examples contain no secrets; ignore rules cover planned local artifacts; the repository passes a scope and consistency review.

## 2. FastAPI and PostgreSQL/pgvector development environment — Completed

**Goal:** Bootstrap the backend and a reproducible local database environment with pgvector available.

**Acceptance criteria:** A health endpoint runs; typed settings load from environment variables; PostgreSQL connectivity and pgvector availability are verified; linting, type checking, and baseline tests run through documented commands.

## 3. Database models and migrations — Completed

**Goal:** Define the initial relational model and migration workflow for tenants, users, collections, documents, chunks, jobs, and conversations.

**Acceptance criteria:** SQLAlchemy models are typed; Alembic creates and reverses the schema; constraints and tenant keys are tested; no schema relies on runtime auto-creation.

## 4. PDF/DOCX upload and asynchronous ingestion — Completed

**Goal:** Securely accept documents, store originals, and queue observable ingestion jobs.

**Acceptance criteria:** Authorized uploads use the storage abstraction; type and size validation exists; Celery/Redis processing is idempotent and retryable; job states and failures are testable.

## 5. Parsing, cleaning and structure-aware chunking — Completed

**Goal:** Extract useful content while retaining source structure and traceability.

**Acceptance criteria:** PDF pages and DOCX sections are preserved where available; cleaning and chunking are deterministic; every chunk maps to a document version and source location; representative parser tests pass.

## 6. Embeddings and vector retrieval — Completed

**Goal:** Generate configurable embeddings and retrieve semantically related authorized chunks with pgvector.

**Acceptance criteria:** Embedding calls are batched and retry-safe; model and dimensions are recorded; vectors are indexed; vector search respects tenant scope; deterministic integration tests cover ranking and failures.

## 7. PostgreSQL full-text search and hybrid retrieval — Completed

**Goal:** Combine lexical and semantic evidence through a documented fusion strategy.

**Acceptance criteria:** Full-text indexes and migrations exist; keyword and vector candidates are fused deterministically; tenant filters apply to both paths; evaluation compares component and hybrid retrieval.

## 8. Reranking and metadata filtering — Complete

**Goal:** Improve candidate ordering and support safe, explicit filters without weakening authorization.

**Acceptance criteria:** Reranking is configurable and observable; allowed filters are validated server-side; authorization constraints cannot be overridden; tests cover ranking, invalid filters, and empty results.

## 9. Answer generation and validated citations — Complete

**Goal:** Generate evidence-bound structured answers and expose only citations verified by the server.

**Acceptance criteria:** The Responses API uses structured output; insufficient evidence produces an honest response; each citation resolves to an authorized retrieved passage with valid metadata and quote; fabricated IDs are rejected in tests.

## 10. Authentication, collections and tenant isolation — Pending

**Goal:** Deliver user identity, organization membership, and collection management with comprehensive isolation.

**Acceptance criteria:** Registration and authentication flows are tested; backend queries derive tenant scope from authenticated membership; cross-tenant read/write attempts fail; frontend-supplied organization IDs never grant access.

## 11. Conversation history and follow-up-question rewriting — Pending

**Goal:** Support contextual conversations without allowing history to corrupt scope or retrieval intent.

**Acceptance criteria:** Conversations are tenant-scoped; the original and rewritten questions are stored; rewriting is testable and configurable; each turn rechecks current authorization.

## 12. Deletion, versioning and reindexing — Pending

**Goal:** Manage the complete lifecycle of source objects and derived data safely.

**Acceptance criteria:** Version changes are traceable; deletion removes or makes all derived data inaccessible per policy; reindexing is idempotent and recoverable; stale versions do not appear in retrieval.

## 13. Next.js frontend and PDF citation viewer — Pending

**Goal:** Provide a usable interface for authentication, collections, ingestion, chat, and source verification.

**Acceptance criteria:** Core flows work against the real API; processing and error states are accessible; citations open the correct authorized PDF page or best source location; no security scope is trusted from client state.

## 14. RAG evaluation, testing and observability — Pending

**Goal:** Make quality, reliability, and failures measurable and reproducible.

**Acceptance criteria:** Versioned datasets exercise retrieval, citations, groundedness, refusals, and isolation; deterministic metrics and supplemental Ragas evaluation run; structured logs and useful traces/metrics cover ingestion and queries; measured baselines are documented.

## 15. Docker hardening, deployment and portfolio documentation — Pending

**Goal:** Harden the complete local stack and present a reproducible, accurate portfolio project.

**Acceptance criteria:** Docker Compose starts the full application with health checks, persistent services, non-secret configuration, and documented recovery steps; security and operational checks pass; architecture, setup, tradeoffs, limitations, and measured results are documented without unsupported claims.
