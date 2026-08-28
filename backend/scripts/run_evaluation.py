import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation import Thresholds, compare_thresholds, run


def markdown(result: dict[str, object]) -> str:
    dataset = result["dataset"]
    metrics = result["aggregate"]
    rows = [
        "# Deterministic RAG evaluation",
        "",
        f"Dataset: `{dataset['id']}` `{dataset['version']}` "
        f"({dataset['cases']} cases; {dataset['development']} development, "
        f"{dataset['heldout']} held-out)",
        f"SHA-256: `{dataset['sha256']}`",
        f"Git commit: `{result['run']['git_commit']}`",
        "",
        "No provider or LLM-judge calls were made. Results describe a small "
        "synthetic fixture and are not statistically general.",
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    rows.extend(f"| {name} | {value:.4f} |" for name, value in sorted(metrics.items()))
    rows.extend(
        [
            "",
            "## Per-slice summary",
            "",
            "| Slice | Reranked recall@10 | Status accuracy | Citation precision "
            "| Citation recall |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, values in result["slices"].items():
        rows.append(
            f"| {name} | {values['reranked.recall@10']:.4f} | "
            f"{values['answer_status_accuracy']:.4f} | "
            f"{values['citation_precision']:.4f} | "
            f"{values['citation_recall']:.4f} |"
        )
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset", type=Path, default=Path("../evaluations/rag-v1.json")
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("../evaluations/reports/deterministic-latest.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("../evaluations/reports/deterministic-latest.md"),
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("../evaluations/thresholds-v1.json"),
    )
    args = parser.parse_args()
    result = run(args.dataset)
    thresholds = Thresholds.model_validate_json(args.thresholds.read_bytes())
    failures = compare_thresholds(result, thresholds)
    result["thresholds"] = {
        "file": args.thresholds.name,
        "minimum": thresholds.minimum,
        "failures": failures,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(markdown(result), encoding="utf-8")
    print(
        f"evaluation=passed cases={result['dataset']['cases']} "
        f"dataset_sha256={result['dataset']['sha256']} provider_calls=0"
    )
    if failures:
        raise SystemExit("evaluation regression: " + ",".join(failures))


if __name__ == "__main__":
    main()
