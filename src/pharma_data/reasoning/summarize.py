from collections import defaultdict

from pharma_data.reasoning.evidence_gate import EvidenceGate
from pharma_data.reasoning.metric_ontology import MetricOntology
from pharma_data.reasoning.models import (
    ClaimGraph,
    ClaimPosture,
    GateAction,
    GateDecision,
    ResearchClaim,
    SummaryLayer,
    SummaryResult,
)


class SummarizeAgent:
    def __init__(self, ontology: MetricOntology, gate: EvidenceGate | None = None):
        self.ontology = ontology
        self.gate = gate or EvidenceGate()

    def run(
        self,
        graph: ClaimGraph,
        *,
        entity: str | None = None,
        max_claims: int = 12,
    ) -> SummaryResult:
        claims = [
            claim
            for claim in graph.claims
            if not entity
            or (claim.subject_name and claim.subject_name.casefold() == entity.casefold())
        ]
        ranked = sorted(claims, key=self._importance, reverse=True)[:max_claims]
        decisions = [self.gate.evaluate(claim, graph) for claim in ranked]
        grouped: dict[ClaimPosture, list[tuple[ResearchClaim, GateDecision]]] = defaultdict(list)
        for claim, decision in zip(ranked, decisions, strict=True):
            posture = self._posture(decision.action)
            grouped[posture].append((claim, decision))
        full = [
            SummaryLayer(
                posture=posture,
                claim_ids=[claim.id for claim, _ in grouped.get(posture, [])],
                text="；".join(self._sentence(claim) for claim, _ in grouped.get(posture, [])),
            )
            for posture in ClaimPosture
            if grouped.get(posture)
        ]
        key_points = [
            SummaryLayer(
                posture=layer.posture,
                claim_ids=layer.claim_ids[:3],
                text="；".join(
                    self._sentence(next(claim for claim in ranked if claim.id == claim_id))
                    for claim_id in layer.claim_ids[:3]
                ),
            )
            for layer in full
        ]
        passed = grouped.get(ClaimPosture.CONSENSUS, [])
        if passed:
            tldr = "；".join(self._sentence(claim) for claim, _ in passed[:2])
        elif ranked:
            tldr = "当前只有待复核或冲突主张，证据门控禁止生成确定性摘要。"
        else:
            tldr = "当前权限和筛选条件下没有可用主张。"
        warnings = []
        if grouped.get(ClaimPosture.CONFLICT):
            warnings.append("存在冲突层，须先完成冲突消解")
        if grouped.get(ClaimPosture.PENDING):
            warnings.append("待复核层不得用于公开发布或投资建议")
        return SummaryResult(
            entity=entity,
            tldr=tldr,
            key_points=key_points,
            full=full,
            evidence_ids=sorted(
                {evidence.evidence_id for claim in ranked for evidence in claim.evidence}
            ),
            gate_decisions=decisions,
            warnings=warnings,
        )

    def _importance(self, claim: ResearchClaim) -> float:
        weights = []
        for dimension in self.ontology.dimensions:
            if self.ontology.match_claim(dimension, claim.predicate, claim.qualifiers):
                weights.append(dimension.investment_importance)
        authority = max(
            (
                {"A1": 1.0, "A2": 0.85}.get(item.authority_tier or "", 0.5)
                for item in claim.evidence
            ),
            default=0.0,
        )
        approved = 1.0 if claim.review_status == "approved" else 0.5
        return 0.4 * max(weights, default=0.5) + 0.35 * authority + 0.25 * approved

    @staticmethod
    def _posture(action: GateAction) -> ClaimPosture:
        if action == GateAction.PASS:
            return ClaimPosture.CONSENSUS
        if action == GateAction.FLAG_CONFLICT:
            return ClaimPosture.CONFLICT
        return ClaimPosture.PENDING

    @staticmethod
    def _sentence(claim: ResearchClaim) -> str:
        subject = claim.subject_name or "未解析主体"
        value = claim.displayed_value or "未给出对象值"
        if claim.object_unit:
            value = f"{value} {claim.object_unit}"
        metric = str(claim.qualifiers.get("metric_name") or claim.predicate)
        return f"{subject}｜{metric}｜{value}（claim:{claim.id}）"
