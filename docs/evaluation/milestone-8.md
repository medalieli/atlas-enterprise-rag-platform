# Milestone 8 focused retrieval evaluation

Run date: 2026-08-26. Reproduce with `backend/scripts/live_m8_smoke.py` against
the migrated Docker stack and configured real OpenAI embedding provider. The fixture
contains three synthetic documents: an English exact-identifier refund policy, a
French paraphrase, and an unrelated maintenance passage. Queries include identifier,
English paraphrase, French paraphrase, distractors, and server-side metadata filters.

| Retrieval mode | MRR@10 | NDCG@10 | Recall@5 |
| --- | ---: | ---: | ---: |
| Semantic | 1.0000 | 1.0000 | 1.0000 |
| Keyword | 0.3333 | 0.3333 | 0.3333 |
| Hybrid before reranking | 1.0000 | 1.0000 | 1.0000 |
| Hybrid after reranking | 1.0000 | 1.0000 | 1.0000 |

The reranker preserved the already-perfect hybrid ordering on this deliberately small
fixture. These measurements therefore do **not** establish an improvement from
reranking. They establish that bounded real-model reranking preserves the labeled
top result across exact, paraphrased, multilingual and filtered cases. Broader and
statistically meaningful evaluation remains Milestone 14.
