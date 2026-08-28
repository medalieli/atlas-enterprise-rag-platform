# Operations, backup and recovery

PostgreSQL plus source objects are authoritative. Redis contains disposable Celery broker/result and transient coordination state; after Redis loss, run the bounded job reconciler to republish durable queued/retrying jobs.

`operations/backup.sh` creates a compressed custom-format `pg_dump`, source-object copy, SHA-256 manifests and measured metadata. Quiesce uploads/activation briefly (or use a consistent snapshot) so database pointers and objects share a recovery point. Encrypt backups with an independently managed KMS/age key, copy them off-host, test decryption, and apply a documented retention policy such as 7 daily/5 weekly/12 monthly.

Restore only to a new isolated database and empty object prefix. `restore.sh` requires `ALLOW_DISPOSABLE_RESTORE=yes`, rejects production-like database URLs, verifies checksums and uses `pg_restore --clean --if-exists`. Then run Alembic `current/check`, storage reconciliation, and fixture assertions for tenants/collections; documents, versions, active generations, chunks/embeddings; conversations/citations; lifecycle/tombstones; hashes; retrieval and fake-provider grounded answers. Never overwrite the working database.

Database-known storage keys are authoritative. Quarantine unreferenced objects before deletion; missing active objects are incidents. Preserve tombstones and historical answer prose per lifecycle policy. Fixture restore observations are not production RPO/RTO guarantees.

For incidents, stop new writes, retain correlation IDs/sanitized logs, check readiness, queue depth, database connections and storage hashes, then restart the smallest affected component. PostgreSQL/storage outages fail requests; Redis outages defer jobs; OpenAI/reranker failures use bounded retries and safe errors; telemetry failure cannot fail requests. Reconciliation/ingestion are idempotent.
