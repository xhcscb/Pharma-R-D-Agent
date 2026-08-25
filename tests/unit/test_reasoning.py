from pharma_data.reasoning.claim_graph import build_claim_graph
from pharma_data.reasoning.compare import CompareAgent
from pharma_data.reasoning.evidence_gate import EvidenceGate
from pharma_data.reasoning.metric_ontology import MetricOntology
from pharma_data.reasoning.models import (
    ClaimEdge,
    ClaimEdgeType,
    ClaimGraph,
    EvidenceRef,
    GateAction,
    ResearchClaim,
)
from pharma_data.reasoning.summarize import SummarizeAgent
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    Document,
    DocumentVersion,
    EntityMentionRecord,
    EntityRecord,
    RawArtifactRecord,
    SourceRecord,
    SourceRegistry,
)


def _claim(
    claim_id: str,
    subject: str,
    value: str,
    *,
    status: str = "approved",
    authority: str = "A1",
) -> ResearchClaim:
    return ResearchClaim(
        id=claim_id,
        subject_name=subject,
        subject_type="Company",
        predicate="REPORTS",
        object_value=value,
        object_unit="亿元",
        qualifiers={"metric_name": "营业收入"},
        confidence=0.96,
        review_status=status,
        evidence=[
            EvidenceRef(
                evidence_id=f"e-{claim_id}",
                document_version_id=f"v-{claim_id}",
                source_name="法定披露平台",
                authority_tier=authority,
                text=f"{subject}营业收入{value}亿元",
                page_number=1,
            )
        ],
    )


def test_metric_ontology_resolves_and_normalizes() -> None:
    ontology = MetricOntology.load()
    assert ontology.resolve("比较两家公司营业收入")[0].id == "company.revenue"
    assert ontology.normalize_number("12.5亿元") == (1_250_000_000.0, "CNY")
    assert ontology.normalize_stage("III期") == "PHASE_III"


def test_evidence_gate_separates_pass_revise_conflict_and_abstain() -> None:
    gate = EvidenceGate()
    approved = _claim("a", "甲公司", "10")
    candidate = _claim("b", "甲公司", "11", status="candidate")
    no_evidence = _claim("c", "甲公司", "12").model_copy(update={"evidence": []})
    graph = ClaimGraph(
        claims=[approved, candidate, no_evidence],
        edges=[
            ClaimEdge(
                source_claim_id="a",
                target_claim_id="b",
                edge_type=ClaimEdgeType.REFUTES,
                rationale="来源不一致",
            )
        ],
    )
    assert gate.evaluate(approved, graph).action == GateAction.FLAG_CONFLICT
    graph.edges = []
    assert gate.evaluate(approved, graph).action == GateAction.PASS
    assert gate.evaluate(candidate, graph).action == GateAction.REVISE
    assert gate.evaluate(no_evidence, graph).action == GateAction.ABSTAIN


def test_compare_and_summary_share_claims_and_evidence() -> None:
    ontology = MetricOntology.load()
    graph = ClaimGraph(claims=[_claim("a", "甲公司", "10"), _claim("b", "乙公司", "20")])
    compare = CompareAgent(ontology)
    dsl = compare.compile(
        "比较甲公司和乙公司营业收入",
        graph,
        objects=["甲公司", "乙公司"],
    )
    result = compare.run(dsl, graph)
    assert result.coverage == 1
    assert {item.values[0] for item in result.cells} == {"10 亿元", "20 亿元"}
    summary = SummarizeAgent(ontology).run(graph, entity="甲公司")
    assert summary.gate_decisions[0].action == GateAction.PASS
    assert summary.evidence_ids == ["e-a"]
    assert "claim:a" in summary.tldr


def test_claim_graph_enforces_access_and_preserves_authority(db_session) -> None:
    source = SourceRegistry(
        name="官方法定披露样例",
        authority_tier="A1",
        adapter_name="FixtureAdapter",
        default_license_status="public_access",
    )
    db_session.add(source)
    db_session.flush()
    source_record = SourceRecord(
        source_id=source.id,
        external_id="FIXTURE-1",
        title="受限测试报告",
        document_type="financial_report",
        license_status="public_access",
        access_class="restricted",
        record_hash="1" * 64,
    )
    db_session.add(source_record)
    db_session.flush()
    artifact = RawArtifactRecord(
        source_record_id=source_record.id,
        media_type="application/pdf",
        object_path="objects/fixture.pdf",
        content_hash="2" * 64,
        size_bytes=10,
        license_status="public_access",
        access_class="restricted",
    )
    document = Document(
        stable_key="fixture:1",
        document_type="financial_report",
        title="受限测试报告",
        language="zh-CN",
    )
    db_session.add_all([artifact, document])
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        source_record_id=source_record.id,
        artifact_id=artifact.id,
        content_hash="3" * 64,
        license_status="public_access",
        access_class="restricted",
    )
    db_session.add(version)
    db_session.flush()
    company = EntityRecord(
        entity_type="Company",
        canonical_name="甲公司",
        normalized_name="甲公司",
        review_status="approved",
    )
    metric = EntityRecord(
        entity_type="FinancialMetric",
        canonical_name="营业收入",
        normalized_name="营业收入",
        review_status="approved",
    )
    db_session.add_all([company, metric])
    db_session.flush()
    company_mention = EntityMentionRecord(
        document_version_id=version.id,
        entity_id=company.id,
        entity_type="Company",
        original_text="甲公司",
        normalized_name="甲公司",
        extraction_method="fixture",
        confidence=1,
        link_status="approved",
    )
    db_session.add(company_mention)
    db_session.flush()
    assertion = AssertionRecord(
        subject_entity_id=company.id,
        subject_mention_id=company_mention.id,
        predicate="REPORTS",
        object_entity_id=metric.id,
        object_value="10",
        object_unit="亿元",
        qualifiers={"metric_name": "营业收入"},
        assertion_mode="stated",
        extraction_method="fixture",
        confidence=1,
        review_status="approved",
        assertion_key="4" * 64,
    )
    db_session.add(assertion)
    db_session.flush()
    db_session.add(
        AssertionEvidenceRecord(
            assertion_id=assertion.id,
            document_version_id=version.id,
            evidence_role="support",
            evidence_text="甲公司营业收入10亿元",
            page_number=3,
        )
    )
    db_session.flush()

    assert not build_claim_graph(
        db_session,
        allowed_access_classes=["public"],
    ).claims
    graph = build_claim_graph(
        db_session,
        allowed_access_classes=["public", "restricted"],
    )
    assert len(graph.claims) == 1
    assert graph.claims[0].evidence[0].authority_tier == "A1"
    assert graph.claims[0].evidence[0].page_number == 3
    assert graph.evidence_links[0].edge_type == ClaimEdgeType.CITES
