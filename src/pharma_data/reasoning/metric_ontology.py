import json
import re
from pathlib import Path
from typing import Any

from pharma_data.reasoning.models import MetricDimension


class MetricOntology:
    def __init__(
        self,
        dimensions: list[MetricDimension],
        utility_weights: dict[str, float] | None = None,
    ):
        if not dimensions:
            raise ValueError("指标本体不得为空")
        ids = [item.id for item in dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("指标本体存在重复 id")
        self.dimensions = dimensions
        self.by_id = {item.id: item for item in dimensions}
        self.utility_weights = utility_weights or {
            "relevance": 0.40,
            "availability": 0.25,
            "investment_importance": 0.35,
            "missing_penalty": 0.45,
        }

    @classmethod
    def load(cls, path: str | Path = "config/metric_ontology.json") -> "MetricOntology":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        dimensions = [MetricDimension.model_validate(item) for item in payload["dimensions"]]
        return cls(dimensions, payload.get("utility_weights"))

    def resolve(self, query: str, entity_type: str | None = None) -> list[MetricDimension]:
        needle = self._key(query)
        matches = []
        for item in self.dimensions:
            if entity_type and entity_type not in item.entity_types:
                continue
            terms = [item.id, item.name, *item.aliases, *item.metric_names]
            if any(self._key(term) in needle or needle in self._key(term) for term in terms):
                matches.append(item)
        return matches

    def match_claim(
        self,
        dimension: MetricDimension,
        predicate: str,
        qualifiers: dict[str, Any],
    ) -> bool:
        if predicate not in dimension.predicates:
            return False
        if not dimension.metric_names:
            return True
        metric_name = str(qualifiers.get("metric_name") or "")
        return self._key(metric_name) in {self._key(item) for item in dimension.metric_names}

    def utility(
        self,
        dimension: MetricDimension,
        *,
        relevance: float,
        availability: float,
    ) -> float:
        weights = self.utility_weights
        score = (
            weights["relevance"] * relevance
            + weights["availability"] * availability
            + weights["investment_importance"] * dimension.investment_importance
        )
        if availability == 0:
            score -= weights.get("missing_penalty", 0)
        return round(max(0.0, min(1.0, score)), 4)

    @staticmethod
    def normalize_number(raw: str) -> tuple[float | None, str | None]:
        text = raw.replace(",", "").replace("，", "").strip()
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*(亿元|万元|元|%|万|亿)?", text)
        if not match:
            return None, None
        value = float(match.group(1))
        unit = match.group(2)
        scale = {"万": 1e4, "万元": 1e4, "亿": 1e8, "亿元": 1e8}.get(unit, 1)
        normalized_unit = "CNY" if unit in {"元", "万元", "亿元"} else unit
        return value * scale, normalized_unit

    @staticmethod
    def normalize_stage(raw: str) -> str | None:
        text = raw.upper().replace(" ", "")
        patterns = (
            (r"(PRE[- ]?CLINICAL|临床前)", "PRECLINICAL"),
            (r"(PHASEI{3}|III期|3期)", "PHASE_III"),
            (r"(PHASEII|II期|2期)", "PHASE_II"),
            (r"(PHASEI|I期|1期)", "PHASE_I"),
            (r"(NDA|BLA|上市申请)", "REGISTRATION"),
            (r"(APPROVED|获批上市|已上市)", "APPROVED"),
        )
        for pattern, normalized in patterns:
            if re.search(pattern, text):
                return normalized
        return None

    @staticmethod
    def _key(value: str) -> str:
        return re.sub(r"[\s_\-./]+", "", value).casefold()
