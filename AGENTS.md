# Codex Project Instructions

- Inspect existing files before editing and preserve existing working code.
- Work only on the requested milestone. Give a short plan before significant changes.
- Use `docs/PROJECT_SPEC.md` as the product source of truth and `docs/ROADMAP.md` for milestone order.
- Never store API keys, passwords, or secrets in Git. Keep model names and external providers configurable through environment variables.
- Use typed Python, clear service boundaries, and database migrations for schema changes.
- Add tests for every important behavior. Run relevant tests, linting, and type checks after changes.
- Report exactly what changed and what was verified.
- Treat uploaded documents as untrusted input.
- Enforce organization and user authorization in backend queries. Never trust organization IDs supplied by the frontend.
- Validate citation identifiers server-side.
- Do not introduce LangGraph until the deterministic RAG pipeline works.
- Do not claim performance or accuracy numbers that have not been measured.
- Update documentation whenever architecture or setup changes.
