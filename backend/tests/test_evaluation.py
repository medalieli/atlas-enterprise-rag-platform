import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation import (
    Dataset,
    Thresholds,
    aggregate,
    compare_thresholds,
    load_dataset,
    ranking_metrics,
    run,
)

DATASET = Path(__file__).parents[2] / "evaluations" / "rag-v1.json"
THRESHOLDS = Path(__file__).parents[2] / "evaluations" / "thresholds-v1.json"


def test_dataset_is_versioned_split_and_uniquely_labeled() -> None:
    dataset, digest = load_dataset(DATASET)
    assert dataset.schema_version == "1.0"
    assert dataset.dataset_version == "2026.08.1"
    assert len(digest) == 64
    assert {case.split for case in dataset.cases} == {"development", "heldout"}
    assert len({case.id for case in dataset.cases}) == len(dataset.cases)


def test_ranking_formulas_are_deterministic() -> None:
    result = ranking_metrics(["noise", "b", "a"], ["a", "b"])
    assert result["precision@10"] == pytest.approx(2 / 3)
    assert result["recall@10"] == 1
    assert result["mrr@10"] == 0.5
    assert result["ndcg@10"] == pytest.approx(0.6934264)
    assert ranking_metrics([], ["a"])["recall@10"] == 0


def test_malformed_missing_and_duplicate_labels_are_rejected() -> None:
    raw = json.loads(DATASET.read_text(encoding="utf-8"))
    raw["cases"][1]["id"] = raw["cases"][0]["id"]
    with pytest.raises(ValidationError, match="duplicate evaluation case id"):
        Dataset.model_validate(raw)
    raw = json.loads(DATASET.read_text(encoding="utf-8"))
    del raw["cases"][0]["expected"]
    with pytest.raises(ValidationError):
        Dataset.model_validate(raw)
    raw = json.loads(DATASET.read_text(encoding="utf-8"))
    raw["cases"][0]["observed"]["keyword"] = ["a", "a"]
    with pytest.raises(ValidationError, match="duplicate ranking labels"):
        Dataset.model_validate(raw)


def test_machine_report_is_deterministic_except_run_metadata() -> None:
    first, second = run(DATASET), run(DATASET)
    for result in (first, second):
        result["run"].pop("timestamp")
        result["run"].pop("duration_seconds")
    assert first == second
    assert first["dataset"]["cases"] == 14
    assert first["run"]["provider_calls"] == 0


def test_regression_thresholds_and_slice_aggregation() -> None:
    result = run(DATASET)
    thresholds = Thresholds.model_validate_json(THRESHOLDS.read_bytes())
    assert compare_thresholds(result, thresholds) == []
    thresholds.minimum["reranked.recall@10"] = 1.01
    assert compare_thresholds(result, thresholds) == ["reranked.recall@10"]
    assert "heldout" in result["slices"] and "french" in result["slices"]


def test_aggregate_rejects_no_data_naturally() -> None:
    assert aggregate([]) == {"aggregate": {}, "slices": {}}
