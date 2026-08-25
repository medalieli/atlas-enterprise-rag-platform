# Project Specification

## Product overview

Production RAG Knowledge Assistant is a secure, multi-document search and question-answering application for organizations. It addresses the difficulty of finding reliable answers across growing collections of internal PDF and DOCX files while retaining enough source context for users to verify every answer.

Retrieval-augmented generation (RAG) retrieves relevant passages from indexed documents at question time and supplies them as context to a language model. **It does not train or fine-tune the language model on uploaded documents.**

## Target users

- Teams that need searchable access to policies, manuals, reports, research, or operational documents
- Knowledge workers who need concise answers backed by inspectable sources
- Organization administrators who manage users, collections, access, and document lifecycles
- Engineers and evaluators responsible for retrieval quality, safety, and system operation

## Main use cases

- Register, authenticate, and access an organization-scoped workspace.
- Create collections and upload PDF or DOCX documents.
- Monitor asynchronous processing and identify failures.
- Ask questions across authorized collections and receive grounded answers with citations.
- Open cited sources at the relevant page or section and inspect the supporting quote.
- Continue a conversation without losing the original retrieval context or authorization boundary.
- Delete, replace, or reindex documents.
- Evaluate retrieval and answer behavior against repeatable datasets.

## Functional requirements

1. Manage users, authentication, organizations, memberships, and collections.
2. Accept PDF and DOCX uploads through an S3-compatible storage abstraction.
3. Validate uploads and process documents asynchronously with observable job states.
4. Extract and clean text while preserving filenames, pages, sections, and other useful metadata.
5. Split content with structure-aware chunking and maintain traceability to the source.
6. Generate configurable embeddings and store chunks in PostgreSQL with pgvector.
7. Support PostgreSQL full-text keyword search and semantic vector search.
8. Combine results through hybrid retrieval, authorization and metadata filters, and reranking.
9. Generate grounded answers with the OpenAI Responses API and structured outputs.
10. Return server-validated citations containing stable identifiers and useful source details.
11. Store conversation history and safely rewrite contextual follow-up questions.
12. Support document deletion, versioning, and reindexing without leaving inaccessible or stale data.
13. Provide an interface for collection management, chat, ingestion status, and PDF citation viewing.
14. Provide deterministic retrieval evaluation and answer-quality evaluation.

## Non-functional requirements

- **Security:** least-privilege access, tenant isolation, safe secret handling, untrusted-file defenses, and auditable authorization decisions.
- **Reliability:** idempotent ingestion, explicit job states, recoverable failures, transactional metadata changes, and safe retries.
- **Traceability:** every indexed chunk and citation must be traceable to a document version and source location.
- **Quality:** important behavior must have automated tests; retrieval and answer changes must be evaluated against versioned cases.
- **Observability:** structured logs, correlation identifiers, useful metrics, and visibility into ingestion and query stages.
- **Maintainability:** typed Python, clear service boundaries, migrations, configurable providers and models, and current documentation.
- **Performance:** interactive queries and background ingestion must have measurable targets established from representative testing; no unmeasured claims are permitted.
- **Portability:** the complete development environment must eventually run locally through Docker Compose.

## High-level architecture

- A Next.js web client provides authentication, collection management, chat, upload status, and source viewing.
- A FastAPI service owns validation, authorization, application APIs, retrieval, answer generation, and citation validation.
- PostgreSQL stores relational data, full-text indexes, chunks, and pgvector embeddings.
- Celery workers use Redis for queued ingestion and reindexing tasks.
- An S3-compatible abstraction stores source documents; local development uses MinIO.
- PyMuPDF and python-docx extract source content. OpenAI provides configurable embeddings and structured generation.
- LangChain may support narrow integrations. Plain Python orchestrates the deterministic pipeline until complexity demonstrates a need for LangGraph.

## Document-ingestion flow

1. An authenticated user requests an upload within an authorized collection.
2. The backend derives organization scope from the authenticated membership, validates file metadata, and creates a document record and immutable version.
3. The original file is stored through the S3-compatible abstraction and an asynchronous job is queued.
4. A worker treats the file as untrusted, validates it again, and parses pages, sections, text, and metadata.
5. Cleaning and structure-aware chunking produce traceable chunks with stable source locations.
6. The worker creates embeddings and persists chunks, vectors, and full-text-search data atomically or with recoverable state transitions.
7. The document version becomes available only after required indexing succeeds; failures remain visible and retryable.

## Question-answering flow

1. The backend authenticates the user and derives allowed organizations and collections server-side.
2. It validates the question and, for follow-ups, deterministically produces a standalone retrieval query while preserving the original user wording.
3. Keyword and semantic searches run only across authorized, active document versions and apply permitted metadata filters.
4. Results are fused, deduplicated, and reranked.
5. The generation model receives the question, selected passages, and strict structured-output instructions.
6. The server validates every returned citation identifier against the retrieved passages and the user's current authorization.
7. The API returns the grounded answer, validated citation metadata, and sufficient source details for inspection. If evidence is inadequate, it must say so instead of fabricating support.

## Security and tenant isolation

- Uploaded documents are untrusted input. Validate type, size, parsing behavior, filenames, and storage keys; isolate processing and impose resource limits.
- Authentication establishes identity; backend-controlled membership records establish organization and collection access.
- Never trust an organization ID, collection scope, storage key, document ID, or citation identifier merely because the frontend supplied it.
- Every backend query that reads or mutates tenant data must include organization and user authorization constraints.
- Background jobs must carry opaque identifiers and independently re-establish authorization and tenant scope from persisted records.
- Storage paths, database uniqueness rules, caches, logs, and evaluation exports must not leak data across tenants.
- Secrets belong in environment-backed secret management and must never be committed.
- Deletion must remove or render inaccessible the source object, derived chunks, embeddings, search records, and cached references according to the defined retention policy.

## Citation requirements

- Each factual claim that depends on retrieved content should map to one or more supporting citations.
- A citation must reference a server-known retrieved passage and include a stable citation ID, document/version ID, filename, page when available, section when available, and a short supporting quote.
- The server—not the model or frontend—must resolve and validate citation identifiers, source metadata, authorization, and quote boundaries.
- Quotes must be present in or safely derived from the cited source passage.
- Citations must remain traceable to the exact indexed document version and open the viewer at the best available source location.
- Unsupported, unknown, unauthorized, or malformed citations must be rejected rather than displayed.

## Evaluation requirements

- Maintain versioned evaluation cases with questions, authorized scope, expected relevant passages or documents, and answer criteria.
- Measure deterministic retrieval behavior with suitable metrics such as recall at k, precision at k, reciprocal rank, and ranking changes where applicable.
- Evaluate citation validity, citation coverage, groundedness, answer relevance, refusal when evidence is insufficient, and tenant-isolation failures.
- Use Ragas as a supplemental answer-quality tool, not as a replacement for deterministic tests and human review.
- Record dataset, configuration, model, prompt, and code versions so results are reproducible.
- Establish baselines through measurement; do not claim accuracy, latency, scale, or cost results that have not been observed.

## Outside the first version

- Training or fine-tuning language models on uploaded documents
- Internet-wide or third-party enterprise search connectors
- Image OCR, handwriting recognition, audio/video ingestion, and complex spreadsheet ingestion
- Autonomous agents that take external actions
- LangGraph orchestration before the deterministic RAG pipeline is proven
- Native mobile applications, real-time collaborative editing, and enterprise billing
- Advanced regulatory certifications or globally distributed high-availability deployment

## Definition of project completion

The project is complete when all roadmap milestones are implemented and documented; the full stack runs locally through Docker Compose; PDF and DOCX documents can be securely ingested, searched, cited, deleted, versioned, and reindexed within enforced tenant boundaries; important behaviors have automated tests; migrations and operational setup are reproducible; evaluation reports measured retrieval and answer quality without unsupported claims; and the portfolio documentation accurately explains architecture, security decisions, limitations, and verification steps.
