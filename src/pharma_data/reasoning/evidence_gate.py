import re

from pharma_data.reasoning.models import (
    ClaimEdgeType,
    ClaimGraph,
    GateAction,
    GateDecision,
    ResearchClaim,
    RiskType,
)


class EvidenceGate:
    """对每条主张执行可解释、可审计的证据门控。"""

    def evaluate(self, claim: ResearchClaim, graph: ClaimGraph) -> GateDecision:
        risk = self.classify_risk(claim)
        reasons = []
        conflicting = any(
            edge.edge_type == ClaimEdgeType.REFUTES
            and claim.id in {edge.source_claim_id, edge.target_claim_id}
            for edge in graph.edges
        )
        if conflicting:
            return GateDecision(
                claim_id=claim.id,
                action=GateAction.FLAG_CONFLICT,
                risk_type=risk,
                reasons=["主张位于未消解的反驳边中"],
            )
        if not claim.evidence:
            return GateDecision(
                claim_id=claim.id,
                action=GateAction.ABSTAIN,
                risk_type=risk,
                reasons=["缺少可定位证据"],
            )
        if claim.review_status != "approved":
            reasons.append("主张尚未完成人工批准")
        authoritative = any(item.authority_tier in {"A1", "A2"} for item in claim.evidence)
        if risk in {RiskType.NUMERIC, RiskType.STAGE, RiskType.REGULATORY} and not authoritative:
            reasons.append("高风险事实缺少 A1/A2 权威证据")
        if risk == RiskType.STRONG_JUDGMENT:
            reasons.append("强判断必须改写为有条件、可归因的表述")
        if reasons:
            return GateDecision(
                claim_id=claim.id,
                action=GateAction.REVISE,
                risk_type=risk,
                reasons=reasons,
            )
        return GateDecision(
            claim_id=claim.id,
            action=GateAction.PASS,
            risk_type=risk,
            reasons=["已批准且证据定位与权威等级满足门控"],
        )

    @staticmethod
    def classify_risk(claim: ResearchClaim) -> RiskType:
        text = " ".join(
            [
                claim.predicate,
                claim.object_value or "",
                str(claim.qualifiers.get("metric_name") or ""),
                *(item.text for item in claim.evidence),
            ]
        )
        if re.search(r"必然|确定|绝对|唯一|无风险|显著优于", text):
            return RiskType.STRONG_JUDGMENT
        if claim.predicate == "REPORTS" or re.search(r"\d+(?:\.\d+)?\s*(?:%|元|万|亿)", text):
            return RiskType.NUMERIC
        if claim.predicate == "HAS_STAGE" or re.search(r"(?:I|II|III|1|2|3)期|临床阶段", text):
            return RiskType.STAGE
        if re.search(r"获批|批准|受理|上市许可|NMPA|药监", text, re.IGNORECASE):
            return RiskType.REGULATORY
        return RiskType.GENERAL
