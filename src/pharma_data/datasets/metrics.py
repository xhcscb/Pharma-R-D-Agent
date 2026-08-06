import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

QUALITY_THRESHOLDS = {
    "native_pdf_character_error_rate": ("max", 0.01),
    "scanned_pdf_character_error_rate": ("max", 0.05),
    "table_teds": ("min", 0.85),
    "core_entity_f1": ("min", 0.90),
    "entity_link_accuracy": ("min", 0.90),
    "relation_micro_f1": ("min", 0.85),
    "relation_dedup_precision": ("min", 0.98),
    "date_normalization_accuracy": ("min", 0.95),
    "unit_normalization_accuracy": ("min", 0.98),
    "conflict_detection_recall": ("min", 0.90),
    "projection_id_consistency": ("min", 1.0),
}


def levenshtein_distance(left: list[Any], right: list[Any]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_item in enumerate(left, start=1):
        current = [row]
        for column, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(pairs: Iterable[dict[str, str]]) -> float:
    edits = 0
    reference_characters = 0
    for pair in pairs:
        gold = list(pair["gold"])
        predicted = list(pair["predicted"])
        edits += levenshtein_distance(gold, predicted)
        reference_characters += len(gold)
    return edits / max(reference_characters, 1)


def set_scores(examples: Iterable[dict[str, list[Any]]]) -> dict[str, float]:
    true_positive = 0
    predicted_total = 0
    gold_total = 0
    for example in examples:
        gold = {_stable_item(item) for item in example["gold"]}
        predicted = {_stable_item(item) for item in example["predicted"]}
        true_positive += len(gold & predicted)
        predicted_total += len(predicted)
        gold_total += len(gold)
    precision = true_positive / predicted_total if predicted_total else float(gold_total == 0)
    recall = true_positive / gold_total if gold_total else float(predicted_total == 0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def pair_accuracy(pairs: Iterable[dict[str, Any]]) -> float:
    values = list(pairs)
    return (
        sum(_stable_item(item["gold"]) == _stable_item(item["predicted"]) for item in values)
        / len(values)
        if values
        else 1.0
    )


def teds_score(pairs: Iterable[dict[str, str]]) -> float:
    """Dependency-free table tree similarity baseline.

    DOM tags and normalized text nodes are compared as an ordered tree-token
    sequence. The metric is deterministic and ranges from zero to one.
    """

    values = list(pairs)
    if not values:
        return 1.0
    scores = []
    for pair in values:
        gold = _table_tokens(pair["gold"])
        predicted = _table_tokens(pair["predicted"])
        distance = levenshtein_distance(gold, predicted)
        scores.append(1.0 - distance / max(len(gold), len(predicted), 1))
    return sum(scores) / len(scores)


class DatasetBenchmarkEvaluator:
    def __init__(self, thresholds: dict[str, tuple[str, float]] | None = None):
        self.thresholds = thresholds or QUALITY_THRESHOLDS

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        metrics = {
            "native_pdf_character_error_rate": character_error_rate(
                payload.get("native_pdf_text", [])
            ),
            "scanned_pdf_character_error_rate": character_error_rate(
                payload.get("scanned_pdf_text", [])
            ),
            "table_teds": teds_score(payload.get("tables", [])),
            "core_entity_f1": set_scores(payload.get("entities", []))["f1"],
            "entity_link_accuracy": pair_accuracy(payload.get("entity_links", [])),
            "relation_micro_f1": set_scores(payload.get("relations", []))["f1"],
            "relation_dedup_precision": set_scores(payload.get("deduplicated_relations", []))[
                "precision"
            ],
            "date_normalization_accuracy": pair_accuracy(payload.get("dates", [])),
            "unit_normalization_accuracy": pair_accuracy(payload.get("units", [])),
            "conflict_detection_recall": set_scores(payload.get("conflicts", []))["recall"],
            "projection_id_consistency": pair_accuracy(payload.get("projection_ids", [])),
        }
        checks = {}
        for name, value in metrics.items():
            direction, threshold = self.thresholds[name]
            passed = value <= threshold if direction == "max" else value >= threshold
            checks[name] = {
                "passed": passed,
                "value": value,
                "operator": "<=" if direction == "max" else ">=",
                "threshold": threshold,
            }
        return {"passed": all(item["passed"] for item in checks.values()), "checks": checks}

    def evaluate_file(self, path: str | Path) -> dict[str, Any]:
        return self.evaluate(json.loads(Path(path).read_text(encoding="utf-8")))


def _stable_item(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _table_tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table") or soup
    tokens: list[str] = []

    def visit(node: Any) -> None:
        name = getattr(node, "name", None)
        if name:
            tokens.append(f"<{name}>")
        text = getattr(node, "string", None)
        if text and not getattr(node, "contents", []):
            normalized = " ".join(str(text).split())
            if normalized:
                tokens.append(normalized)
        for child in getattr(node, "children", []):
            if getattr(child, "name", None):
                visit(child)
            elif str(child).strip():
                tokens.append(" ".join(str(child).split()))
        if name:
            tokens.append(f"</{name}>")

    visit(table)
    return tokens
