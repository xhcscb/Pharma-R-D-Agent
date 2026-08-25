from pharma_data.datasets.metrics import (
    DatasetBenchmarkEvaluator,
    character_error_rate,
    set_scores,
    teds_score,
)


def test_quality_metrics_are_deterministic() -> None:
    assert character_error_rate([{"gold": "abc", "predicted": "adc"}]) == 1 / 3
    assert (
        teds_score(
            [
                {
                    "gold": "<table><tr><td>A</td></tr></table>",
                    "predicted": "<table><tr><td>A</td></tr></table>",
                }
            ]
        )
        == 1.0
    )
    assert set_scores([{"gold": ["a", "b"], "predicted": ["a"]}]) == {
        "precision": 1.0,
        "recall": 0.5,
        "f1": 2 / 3,
    }


def test_complete_perfect_benchmark_passes_all_gates() -> None:
    payload = {
        "native_pdf_text": [{"gold": "text", "predicted": "text"}],
        "scanned_pdf_text": [{"gold": "scan", "predicted": "scan"}],
        "tables": [
            {
                "gold": "<table><tr><td>A</td></tr></table>",
                "predicted": "<table><tr><td>A</td></tr></table>",
            }
        ],
        "entities": [{"gold": ["Drug:X"], "predicted": ["Drug:X"]}],
        "entity_links": [{"gold": "drug-x", "predicted": "drug-x"}],
        "relations": [
            {
                "gold": [["drug-x", "TREATS", "cancer"]],
                "predicted": [["drug-x", "TREATS", "cancer"]],
            }
        ],
        "deduplicated_relations": [{"gold": ["r1"], "predicted": ["r1"]}],
        "dates": [{"gold": "2025-01-01", "predicted": "2025-01-01"}],
        "units": [{"gold": "CNY", "predicted": "CNY"}],
        "conflicts": [{"gold": ["c1"], "predicted": ["c1"]}],
        "projection_ids": [{"gold": "a1", "predicted": "a1"}],
    }

    report = DatasetBenchmarkEvaluator().evaluate(payload)

    assert report["passed"] is True
    assert all(check["passed"] for check in report["checks"].values())


def test_empty_benchmark_cannot_pass_release_gates() -> None:
    report = DatasetBenchmarkEvaluator().evaluate({})

    assert report["passed"] is False
    assert set(report["missing_required_sets"]) == set(report["coverage"])
