# Focused conversational evaluation

Milestone 11 uses a reproducible deterministic fixture in
`tests/test_rewriting.py` and `tests/test_conversations_integration.py`. It covers a
direct first turn, a context-dependent clarification turn, bounded history, stable
ordering, idempotency, and empty authorized retrieval. The measured fixture results
were:

- rewrite/classification correctness: 100% for the labeled cases;
- clarification correctness: 100%;
- answer-status correctness: 100%;
- citation validity: 100% for generated cited answers in the existing answer suite;
- factual claims with citations: 100% in answered fixtures;
- duplicate paid/provider work on idempotent replay: 0 calls.

The fixture is intentionally focused and too small to support a general claim that
rewriting improves retrieval MRR/NDCG. Retrieval ranking deltas, French multi-turn
coverage, conflict fixtures, and production distributions remain part of Milestone 14.

The bounded real-provider check used one Luna rewrite call and one Terra grounded-answer
call. Luna classified the follow-up as rewritten. Terra returned `answered`, and every
returned source ID belonged to the supplied context. No source or message text was
printed or retained in this report.
