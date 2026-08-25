# Production RAG Knowledge Assistant

Production RAG Knowledge Assistant is a production-oriented portfolio project for secure, multi-document organizational search. The planned application will ingest PDF and DOCX documents into tenant-isolated collections, retrieve relevant passages with hybrid search, and generate grounded answers with validated citations to source files, pages, sections, and quotes.

## Planned features

- User registration, authentication, organizations, and document collections
- Asynchronous PDF and DOCX ingestion with structure and metadata preservation
- Structure-aware chunking and configurable OpenAI embeddings
- PostgreSQL semantic and keyword hybrid retrieval using pgvector and full-text search
- Metadata and authorization filtering, reranking, and grounded answer generation
- Server-validated citations and a PDF source viewer
- Conversation history, document deletion, versioning, and reindexing
- Retrieval and answer-quality evaluation, automated testing, and observability
- Local operation through Docker Compose

## Planned architecture

The planned system uses a Next.js frontend; a typed FastAPI backend built with Pydantic, SQLAlchemy, and Alembic; PostgreSQL with pgvector and full-text search; Celery and Redis for background work; and S3-compatible object storage with MinIO locally. PyMuPDF and python-docx will parse documents. OpenAI models will provide configurable embeddings and structured answer generation. LangChain will be used selectively, while orchestration remains plain Python unless a deterministic multi-step workflow later justifies LangGraph.

## Repository structure

```text
.
├── backend/          # Future backend application
├── frontend/         # Future Next.js application
├── infrastructure/   # Future local and deployment infrastructure
├── evaluations/      # Future RAG evaluation assets
├── docs/
│   ├── PROJECT_SPEC.md
│   └── ROADMAP.md
├── AGENTS.md
├── README.md
└── .env.example
```

## Current status

Foundation only. The repository currently contains project documentation, configuration placeholders, and empty directories. **The application is not implemented yet.** No backend, frontend, database, infrastructure services, or RAG pipeline has been created.

See the [project specification](docs/PROJECT_SPEC.md) for product requirements and the [roadmap](docs/ROADMAP.md) for the ordered implementation milestones.
