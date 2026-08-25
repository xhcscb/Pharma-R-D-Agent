from sqlalchemy.orm import Session

from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    Document,
    DocumentAccessGrantRecord,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
    EntityRecord,
    ProcessingJob,
    ProcessingRun,
    RawArtifactRecord,
    SourceRecord,
    SourceRegistry,
)
from pharma_data.visualization import build_entity_extraction_example, build_relation_graph


def test_relation_graph_keeps_candidate_edge_and_evidence(db_session: Session) -> None:
    source = SourceRegistry(
        name="official_fixture",
        authority_tier="A1",
        adapter_name="FixtureAdapter",
        default_license_status="public_access",
    )
    db_session.add(source)
    db_session.flush()
    source_record = SourceRecord(
        source_id=source.id,
        external_id="FIXTURE-1",
        title="官方关系样例",
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
        size_bytes=128,
        license_status="public_access",
        access_class="restricted",
    )
    document = Document(
        stable_key="official_fixture:FIXTURE-1",
        document_type="financial_report",
        title="官方关系样例",
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
    document.current_version_id = version.id
    db_session.add(
        DocumentAccessGrantRecord(
            document_version_id=version.id,
            source_record_id=source_record.id,
            access_class="restricted",
            license_status="public_access",
            provenance_status="fixture",
        )
    )
    job = ProcessingJob(
        document_version_id=version.id,
        pipeline_step="fixture",
        status="NEEDS_REVIEW",
        idempotency_key="fixture-active-run",
    )
    db_session.add(job)
    db_session.flush()
    run = ProcessingRun(
        job_id=job.id,
        trace_id="fixture-trace",
        producer="fixture",
        producer_version="1",
        schema_version="2.0",
        input_hash=version.content_hash,
        status="NEEDS_REVIEW",
    )
    db_session.add(run)
    db_session.flush()
    version.active_parse_run_id = run.id
    element = DocumentElementRecord(
        document_version_id=version.id,
        parse_run_id=run.id,
        page_number=7,
        element_type="paragraph",
        reading_order=0,
        text="样例药物作用于样例靶点。",
        parser_name="fixture",
        parser_version="1",
        confidence=1.0,
        content_hash="5" * 64,
    )
    db_session.add(element)
    db_session.flush()

    drug = EntityRecord(
        entity_type="Drug",
        canonical_name="样例药物",
        normalized_name="样例药物",
        review_status="candidate",
    )
    target = EntityRecord(
        entity_type="Target",
        canonical_name="样例靶点",
        normalized_name="样例靶点",
        review_status="candidate",
    )
    db_session.add_all([drug, target])
    db_session.flush()
    drug_mention = EntityMentionRecord(
        document_version_id=version.id,
        element_id=element.id,
        entity_id=drug.id,
        entity_type="Drug",
        original_text="样例药物",
        normalized_name="样例药物",
        extraction_method="fixture",
        confidence=0.96,
        link_status="candidate",
    )
    target_mention = EntityMentionRecord(
        document_version_id=version.id,
        element_id=element.id,
        entity_id=target.id,
        entity_type="Target",
        original_text="样例靶点",
        normalized_name="样例靶点",
        extraction_method="fixture",
        confidence=0.95,
        link_status="candidate",
    )
    db_session.add_all([drug_mention, target_mention])
    db_session.flush()
    assertion = AssertionRecord(
        subject_entity_id=drug.id,
        subject_mention_id=drug_mention.id,
        predicate="TARGETS",
        object_entity_id=target.id,
        object_mention_id=target_mention.id,
        assertion_mode="stated",
        extraction_method="fixture",
        confidence=0.91,
        review_status="candidate",
        assertion_key="4" * 64,
    )
    db_session.add(assertion)
    db_session.flush()
    db_session.add(
        AssertionEvidenceRecord(
            assertion_id=assertion.id,
            document_version_id=version.id,
            element_id=element.id,
            evidence_role="support",
            evidence_text="样例药物作用于样例靶点。",
            page_number=7,
        )
    )
    db_session.flush()

    graph = build_relation_graph(db_session, ["public", "restricted"])

    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["predicate"] == "TARGETS"
    assert graph["edges"][0]["page_number"] == 7
    assert graph["edges"][0]["evidence"] == "样例药物作用于样例靶点。"
    assert build_entity_extraction_example(db_session, ["public", "restricted"]) is None
