from pharma_data.reasoning.evidence_gate import EvidenceGate
from pharma_data.reasoning.metric_ontology import MetricOntology
from pharma_data.reasoning.models import (
    ClaimGraph,
    CompareDSL,
    CompareResult,
    ComparisonCell,
    GateAction,
    MetricDimension,
)


class CompareAgent:
    def __init__(self, ontology: MetricOntology, gate: EvidenceGate | None = None):
        self.ontology = ontology
        self.gate = gate or EvidenceGate()

    def compile(
        self,
        query: str,
        graph: ClaimGraph,
        *,
        objects: list[str] | None = None,
        dimensions: list[str] | None = None,
        time: str | None = None,
        scope: str | None = None,
    ) -> CompareDSL:
        object_names = [item for item in objects or [] if item.strip()]
        if not object_names:
            candidates = sorted(
                {claim.subject_name for claim in graph.claims if claim.subject_name}
            )
            object_names = [name for name in candidates if name.casefold() in query.casefold()]
            if not object_names:
                object_names = candidates[:2]
        if not object_names:
            raise ValueError("没有可比较的实体，请显式提供 objects")
        dimension_ids = [item for item in dimensions or [] if item.strip()]
        if not dimension_ids:
            dimension_ids = [item.id for item in self.ontology.resolve(query)]
        if not dimension_ids:
            dimension_ids = self._available_dimensions(graph, object_names)
        unknown = [item for item in dimension_ids if item not in self.ontology.by_id]
        if unknown:
            raise ValueError(f"未知比较维度: {', '.join(unknown)}")
        if not dimension_ids:
            raise ValueError("没有可用比较维度，请显式提供 dimensions")
        return CompareDSL(
            objects=object_names,
            dimensions=dimension_ids,
            time=time,
            scope=scope,
        )

    def run(self, dsl: CompareDSL, graph: ClaimGraph) -> CompareResult:
        cells = []
        conflict_claim_ids = set()
        for object_name in dsl.objects:
            for dimension_id in dsl.dimensions:
                dimension = self.ontology.by_id[dimension_id]
                claims = [
                    claim
                    for claim in graph.claims
                    if claim.subject_name
                    and claim.subject_name.casefold() == object_name.casefold()
                    and self.ontology.match_claim(dimension, claim.predicate, claim.qualifiers)
                ]
                decisions = [self.gate.evaluate(claim, graph) for claim in claims]
                for decision in decisions:
                    if decision.action == GateAction.FLAG_CONFLICT:
                        conflict_claim_ids.add(decision.claim_id)
                values = []
                for claim, decision in zip(claims, decisions, strict=True):
                    if decision.action != GateAction.ABSTAIN and claim.displayed_value:
                        value = claim.displayed_value
                        if claim.object_unit:
                            value = f"{value} {claim.object_unit}"
                        values.append(value)
                cells.append(
                    ComparisonCell(
                        object_name=object_name,
                        dimension_id=dimension_id,
                        values=values,
                        claim_ids=[claim.id for claim in claims],
                        evidence_ids=[
                            evidence.evidence_id for claim in claims for evidence in claim.evidence
                        ],
                        gate_actions=[decision.action for decision in decisions],
                        missing_reason=None if claims else "无满足权限、复核状态和指标口径的主张",
                    )
                )
        populated = sum(cell.missing_reason is None for cell in cells)
        coverage = populated / len(cells) if cells else 0.0
        warnings = []
        if coverage < 1:
            warnings.append("比较存在数据缺口；不得把缺失值解释为零或不存在")
        if conflict_claim_ids:
            warnings.append("比较包含未消解冲突；不得输出单一确定结论")
        if any(GateAction.REVISE in cell.gate_actions for cell in cells):
            warnings.append("候选或高风险主张仅供内部复核，不得直接发布")
        return CompareResult(
            dsl=dsl,
            cells=cells,
            coverage=round(coverage, 4),
            conflict_claim_ids=sorted(conflict_claim_ids),
            warnings=warnings,
        )

    def _available_dimensions(self, graph: ClaimGraph, objects: list[str]) -> list[str]:
        names = {item.casefold() for item in objects}
        available: list[tuple[float, str]] = []
        for dimension in self.ontology.dimensions:
            count = sum(
                bool(claim.subject_name)
                and (claim.subject_name or "").casefold() in names
                and self.ontology.match_claim(dimension, claim.predicate, claim.qualifiers)
                for claim in graph.claims
            )
            if count:
                available.append((self._utility(dimension, count, len(objects)), dimension.id))
        return [item[1] for item in sorted(available, reverse=True)]

    def _utility(self, dimension: MetricDimension, count: int, object_count: int) -> float:
        availability = min(1.0, count / max(1, object_count))
        return self.ontology.utility(
            dimension,
            relevance=1.0,
            availability=availability,
        )
