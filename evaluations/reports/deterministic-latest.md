# Deterministic RAG evaluation

Dataset: `synthetic-rag-regression` `2026.08.1` (14 cases; 9 development, 5 held-out)
SHA-256: `df919658e1d0f2b4ebaf3669d30c87bebeb68702a5ca37c58b9be907e0a8f0da`
Git commit: `14b34fe5b7867fd409279591aadc2a88ddde4827`

No provider or LLM-judge calls were made. Results describe a small synthetic fixture and are not statistically general.

## Aggregate metrics

| Metric | Value |
| --- | ---: |
| answer_status_accuracy | 1.0000 |
| citation_precision | 1.0000 |
| citation_recall | 1.0000 |
| claim_citation_coverage | 1.0000 |
| factual_correctness | 1.0000 |
| filter_correctness | 1.0000 |
| hybrid.mrr@10 | 0.7143 |
| hybrid.ndcg@10 | 1.0000 |
| hybrid.precision@10 | 0.8929 |
| hybrid.recall@10 | 1.0000 |
| injection_resistance | 1.0000 |
| isolation_correctness | 1.0000 |
| keyword.mrr@10 | 0.6429 |
| keyword.ndcg@10 | 0.9286 |
| keyword.precision@10 | 0.8571 |
| keyword.recall@10 | 0.9286 |
| lifecycle_exclusion | 1.0000 |
| reranked.mrr@10 | 0.7143 |
| reranked.ndcg@10 | 1.0000 |
| reranked.precision@10 | 0.8929 |
| reranked.recall@10 | 1.0000 |
| rewrite_clarification_accuracy | 1.0000 |
| semantic.mrr@10 | 0.6071 |
| semantic.ndcg@10 | 0.9022 |
| semantic.precision@10 | 0.8214 |
| semantic.recall@10 | 0.9286 |
| source_location_accuracy | 1.0000 |

## Per-slice summary

| Slice | Reranked recall@10 | Status accuracy | Citation precision | Citation recall |
| --- | ---: | ---: | ---: | ---: |
| answerable | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| citation-coverage | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| clarification | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| collection-isolation | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| conflict | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| deletion | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| development | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| en | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| english | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| exact | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| follow-up | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| fr | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| french | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| heldout | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| insufficient | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| keyword-only | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| metadata-filter | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| multi-source | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| prompt-injection | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| quoted-phrase | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| refusal | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| reindex | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| replacement | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| rewrite | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| semantic-only | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| stale-version | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| tenant-isolation | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
