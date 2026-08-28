from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import NonLLMContextPrecisionWithReference, NonLLMContextRecall

from app.evaluation import load_dataset


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic Ragas supplement"
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset, digest = load_dataset(args.dataset)
    precision_metric = NonLLMContextPrecisionWithReference()
    recall_metric = NonLLMContextRecall()
    cases: list[dict[str, object]] = []
    for case in dataset.cases:
        sample = SingleTurnSample(
            # Synthetic evidence labels are intentionally used instead of content.
            retrieved_contexts=case.observed.reranked,
            reference_contexts=case.expected.evidence,
        )
        applicable = bool(case.expected.evidence)
        precision = (
            precision_metric.single_turn_score(sample) if applicable else math.nan
        )
        recall = recall_metric.single_turn_score(sample) if applicable else math.nan
        cases.append(
            {
                "id": case.id,
                "split": case.split,
                "context_precision": precision if math.isfinite(precision) else None,
                "context_recall": recall if math.isfinite(recall) else None,
            }
        )
    report = {
        "schema_version": "1.0",
        "kind": "ragas-deterministic-supplement",
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": digest,
        "generated_at": datetime.now(UTC).isoformat(),
        "provider_calls": 0,
        "llm_judge": "disabled",
        "metrics": {
            name: sum(float(case[name]) for case in cases if case[name] is not None)
            / sum(case[name] is not None for case in cases)
            for name in ("context_precision", "context_recall")
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
