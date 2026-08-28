from __future__ import annotations

import hashlib
import math
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.observability import EVALUATION_DURATION, EVALUATION_RUNS

MODES = ("keyword", "semantic", "hybrid", "reranked")


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence: list[str]
    facts: list[str]
    status: str
    citations: list[str]
    rewrite: Literal["unchanged", "rewritten", "clarification"]


class Observed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: list[str]
    semantic: list[str]
    hybrid: list[str]
    reranked: list[str]
    status: str
    facts: list[str]
    citations: list[str]
    locations: list[str]
    rewrite: Literal["unchanged", "rewritten", "clarification"]
    filter_correct: bool = True
    injection_resisted: bool = True
    stale_excluded: bool = True
    deleted_excluded: bool = True
    isolation_correct: bool = True

    @model_validator(mode="after")
    def unique_rankings(self) -> Observed:
        for mode in MODES:
            values = getattr(self, mode)
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate ranking labels in {mode}")
        return self


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    split: Literal["development", "heldout"]
    language: Literal["en", "fr"]
    query_kind: str
    question: str
    filters: dict[str, str]
    expected: Expected
    observed: Observed
    expected_locations: list[str]
    slices: list[str] = Field(min_length=1)


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    dataset_id: str
    dataset_version: str
    provenance: str
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases_and_splits(self) -> Dataset:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evaluation case id")
        if {case.split for case in self.cases} != {"development", "heldout"}:
            raise ValueError("development and heldout cases are required")
        return self


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    dataset_version: str
    minimum: dict[str, float]


def compare_thresholds(result: dict[str, object], thresholds: Thresholds) -> list[str]:
    dataset = result["dataset"]
    if dataset["version"] != thresholds.dataset_version:  # type: ignore[index]
        return ["dataset_version"]
    aggregate_metrics = result["aggregate"]
    return [
        name
        for name, minimum in thresholds.minimum.items()
        if name not in aggregate_metrics  # type: ignore[operator]
        or aggregate_metrics[name] < minimum  # type: ignore[index]
    ]


def ranking_metrics(
    ranking: list[str], relevant: list[str], k: int = 10
) -> dict[str, float]:
    top = ranking[:k]
    truth = set(relevant)
    hits = [1 if item in truth else 0 for item in top]
    precision = sum(hits) / len(top) if top else (1.0 if not truth else 0.0)
    recall = sum(hits) / len(truth) if truth else (1.0 if not top else 0.0)
    reciprocal = next((1.0 / index for index, hit in enumerate(hits, 1) if hit), 0.0)
    dcg = sum(hit / math.log2(index + 1) for index, hit in enumerate(hits, 1))
    ideal = sum(
        1.0 / math.log2(index + 1) for index in range(1, min(len(truth), k) + 1)
    )
    ndcg = dcg / ideal if ideal else (1.0 if not top else 0.0)
    return {
        f"precision@{k}": precision,
        f"recall@{k}": recall,
        "mrr@10": reciprocal,
        "ndcg@10": ndcg,
    }


def _ratio(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(right) if right else (1.0 if not left else 0.0)


def grade(case: EvalCase) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for mode in MODES:
        metrics.update(
            {
                f"{mode}.{key}": value
                for key, value in ranking_metrics(
                    getattr(case.observed, mode), case.expected.evidence
                ).items()
            }
        )
    expected_citations, actual_citations = (
        set(case.expected.citations),
        set(case.observed.citations),
    )
    metrics.update(
        {
            "filter_correctness": float(case.observed.filter_correct),
            "answer_status_accuracy": float(
                case.observed.status == case.expected.status
            ),
            "factual_correctness": _ratio(
                set(case.observed.facts), set(case.expected.facts)
            ),
            "citation_precision": _ratio(expected_citations, actual_citations),
            "citation_recall": _ratio(actual_citations, expected_citations),
            "claim_citation_coverage": float(
                not case.expected.facts or expected_citations.issubset(actual_citations)
            ),
            "source_location_accuracy": float(
                set(case.observed.locations) == set(case.expected_locations)
            ),
            "rewrite_clarification_accuracy": float(
                case.observed.rewrite == case.expected.rewrite
            ),
            "injection_resistance": float(case.observed.injection_resisted),
            "lifecycle_exclusion": float(
                case.observed.stale_excluded and case.observed.deleted_excluded
            ),
            "isolation_correctness": float(case.observed.isolation_correct),
        }
    )
    return metrics


def load_dataset(path: Path) -> tuple[Dataset, str]:
    raw = path.read_bytes()
    return Dataset.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def aggregate(cases: list[tuple[EvalCase, dict[str, float]]]) -> dict[str, object]:
    values: dict[str, list[float]] = defaultdict(list)
    slices: dict[str, list[dict[str, float]]] = defaultdict(list)
    for case, result in cases:
        for key, value in result.items():
            values[key].append(value)
        for name in [case.split, case.language, *case.slices]:
            slices[name].append(result)

    def mean(rows: list[dict[str, float]]) -> dict[str, float]:
        return {key: sum(item[key] for item in rows) / len(rows) for key in rows[0]}

    return {
        "aggregate": {key: sum(row) / len(row) for key, row in values.items()},
        "slices": {name: mean(rows) for name, rows in sorted(slices.items())},
    }


def run(dataset_path: Path) -> dict[str, object]:
    started = perf_counter()
    dataset, digest = load_dataset(dataset_path)
    graded = [(case, grade(case)) for case in dataset.cases]
    summary = aggregate(graded)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    result = {
        "schema_version": "1.0",
        "dataset": {
            "id": dataset.dataset_id,
            "version": dataset.dataset_version,
            "sha256": digest,
            "cases": len(dataset.cases),
            "development": sum(c.split == "development" for c in dataset.cases),
            "heldout": sum(c.split == "heldout" for c in dataset.cases),
        },
        "run": {
            "kind": "deterministic",
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit": commit,
            "duration_seconds": perf_counter() - started,
            "provider_calls": 0,
            "prompt_versions": {},
        },
        "configuration": {
            "retrieval_snapshot": "deterministic-fixture-v1",
            "embedding_model": "deterministic-reference",
            "reranker_model": "deterministic-reference",
            "answer_prompt": "grounded-answer-v1",
            "rewrite_prompt": "follow-up-rewriter-v1",
            "llm_judge": "disabled",
        },
        **summary,
        "cases": [
            {
                "id": case.id,
                "split": case.split,
                "slices": case.slices,
                "metrics": metrics,
            }
            for case, metrics in graded
        ],
    }
    EVALUATION_RUNS.labels("deterministic", "succeeded").inc()
    EVALUATION_DURATION.labels("deterministic").observe(perf_counter() - started)
    return result
