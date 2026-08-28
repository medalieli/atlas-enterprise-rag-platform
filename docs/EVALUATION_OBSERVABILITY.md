# Evaluation and observability

Milestone 14 makes the RAG pipeline measurable without sending private content to
telemetry systems. It does not define production SLOs or deployment policy.

## Evaluation dataset

`evaluations/rag-v1.json` is a versioned, synthetic dataset. Every case declares a
development or held-out split, language, filters, expected evidence labels, facts,
answer status, citations, rewrite outcome, source locations, and applicable slices.
Held-out cases are reserved for regression reporting and are not tuning targets. The
small fixture does not establish statistical generality.

Run the reference graders from `backend`:

```powershell
uv run python scripts/run_evaluation.py
uv run --group evaluation python scripts/run_ragas_evaluation.py `
  ../evaluations/rag-v1.json --output ../evaluations/reports/ragas-latest.json
```

The first command validates `evaluations/thresholds-v1.json` and exits non-zero on
regression. Reports include the dataset hash, Git commit, configuration, prompt
versions, aggregate metrics, and slices. The Ragas supplement uses only non-LLM
context precision/recall over synthetic evidence labels and makes no provider calls.
Normal tests do not install the optional evaluation group and never contact OpenAI.

### Measured synthetic baseline

Dataset `2026.08.1` contains 14 cases (9 development, 5 held-out) and has SHA-256
`df919658e1d0f2b4ebaf3669d30c87bebeb68702a5ca37c58b9be907e0a8f0da`. Keyword
and semantic Recall@10 are `0.9286`; hybrid and reranked Recall@10 and NDCG@10 are
`1.0000`. Answer-status, factual, citation precision/recall, claim coverage, source
location, rewrite/clarification, injection, lifecycle, and isolation scores are
`1.0000` across the deterministic snapshot. The non-LLM Ragas supplement reports
context precision and recall of `1.0000` on the ten cases where retrieval evidence is
applicable; refusal/isolation cases are recorded as `null`, not scored as retrieval
failures. Exact aggregates and every slice are in `evaluations/reports/`.

The authenticated 2026-08-28 live subset passed six synthetic cases (answerable,
insufficient, conflicting, French, follow-up, injection). It made 12 provider
operations: five document-embedding calls, six answer-generation calls, and one
follow-up rewrite. The generation and rewrite operations used configured/returned
model `gpt-5.6-terra`, totaling 2,629 input and 528 output tokens with 11,688.6 ms
combined latency. Embedding usage was observed in aggregate metrics but was not
isolated at the start of this run, so an exact per-run embedding-token total is not
claimed. This bounded run is an operational smoke result, not a deterministic
threshold or statistical claim.

The snapshot compares keyword, semantic, hybrid, and reranked rankings, then grades
answer status, facts, citations, claim coverage, source location, filtering,
conflict/refusal behavior, rewriting/clarification, injection resistance, lifecycle
exclusion, and isolation. Citation and authorization labels are reference-derived;
no LLM judge is used. A separately invoked live subset may measure provider behavior,
but records only aggregate calls, model names, token counts, and latency—never inputs
or outputs.

## Telemetry architecture

W3C trace context flows from the Next.js BFF to FastAPI and through Celery message
headers to worker spans. OpenTelemetry export is asynchronous and bounded; collector
failure cannot fail a user request. Stable spans cover BFF/API requests, task
execution, ingestion stages, retrieval/fusion/reranking, follow-up rewriting,
generation, citation validation, and lifecycle work.

The FastAPI `/internal/metrics` endpoint is disabled by default and requires a bearer
scrape credential when enabled. Prometheus labels are limited to route templates and
enumerated methods, status classes, modes, operations, outcomes, providers/models,
directions, and error categories. UUIDs, filenames, metadata, exception text, and
arbitrary routes are never labels.

Logs contain safe request correlation plus trace/span IDs. Questions, answers,
messages, source text, prompts, vectors, filenames, metadata values, identity and
resource IDs, cookies, authorization values, tokens, keys, and raw provider responses
are prohibited from logs, spans, metrics, and baggage.

## Local stack

The normal Compose stack remains lightweight. Start the opt-in profile with a local,
non-production scrape credential:

```powershell
$env:TELEMETRY_ENABLED='true'
$env:METRICS_ENABLED='true'
$env:METRICS_BEARER_TOKEN='local-observability-token'
docker compose --profile observability up --build
```

The pinned profile contains OpenTelemetry Collector, Prometheus, Tempo, and Grafana.
Only Grafana is host-bound, on `http://127.0.0.1:3001`. Provisioning loads Prometheus
and Tempo data sources plus the **Local RAG observability** dashboard for request and
error rate, p50/p95 latency, RAG stages, ingestion queue/failures, retrieval/answer
outcomes, and provider errors/retries/token usage. Local thresholds and observed
fixture latency are not production SLOs.

## Limitations and deferrals

The dataset is intentionally bounded, latency is machine-dependent, and the optional
live subset is too small for statistical claims. Vendor monitoring, paging,
autoscaling, Kubernetes/cloud deployment, stress/soak testing, disaster recovery, and
production SLO policy are explicitly deferred to Milestone 15.
