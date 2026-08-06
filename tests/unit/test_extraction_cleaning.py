from pharma_data.cleaning import DataCleanAgent
from pharma_data.contracts import DocumentType, ElementType, ParsedDocument, RelationType
from pharma_data.entity_extraction import (
    DictionaryExtractor,
    EntityExtractAgent,
    PatternExtractor,
)
from pharma_data.parsers.common import make_element
from pharma_data.relation_extraction import RelationExtractAgent


def test_entities_relations_and_evidence_are_linked() -> None:
    text = (
        "\u6052\u745e\u533b\u836f\u81ea\u4e3b\u7814\u53d1"
        "\u7684PD-1\u6291\u5236\u5242\u5361\u745e\u5229"
        "\u73e0\u5355\u6297\u7528\u4e8e\u6cbb\u7597"
        "\u975e\u5c0f\u7ec6\u80de\u80ba\u764c\u3002"
    )
    element = make_element(
        document_version_id="version",
        element_type=ElementType.PARAGRAPH,
        reading_order=0,
        text=text,
        parser_name="test",
        parser_version="1",
    )
    parsed = ParsedDocument(
        document_id="doc",
        document_version_id="version",
        document_type=DocumentType.RESEARCH_REPORT,
        elements=[element],
    )
    mentions = EntityExtractAgent(
        [DictionaryExtractor("config/entities.json"), PatternExtractor()]
    ).extract(parsed)
    assertions = RelationExtractAgent().extract(parsed, mentions)
    cleaned = DataCleanAgent().clean(
        document_version_id="version",
        mentions=mentions,
        assertions=assertions,
    )

    predicates = {assertion.predicate for assertion in cleaned.assertions}
    assert RelationType.DEVELOPS in predicates
    assert RelationType.TARGETS in predicates
    assert RelationType.TREATS in predicates
    assert all(assertion.evidence_element_id == element.element_id for assertion in assertions)


def test_conflicting_values_are_preserved() -> None:
    from pharma_data.contracts import AssertionCandidate, EntityMention, EntityType

    mention = EntityMention(
        entity_type=EntityType.DRUG,
        original_text="Drug X",
        normalized_name="Drug X",
        extraction_method="test",
        confidence=1.0,
    )
    assertions = [
        AssertionCandidate(
            subject_mention_id=mention.mention_id,
            predicate=RelationType.REPORTS,
            object_value="2",
            object_unit="phase",
            evidence_element_id="e1",
            evidence_text="phase 2",
            extraction_method="test",
            confidence=0.9,
        ),
        AssertionCandidate(
            subject_mention_id=mention.mention_id,
            predicate=RelationType.REPORTS,
            object_value="3",
            object_unit="phase",
            evidence_element_id="e2",
            evidence_text="phase 3",
            extraction_method="test",
            confidence=0.9,
        ),
    ]
    result = DataCleanAgent().clean(
        document_version_id="version",
        mentions=[mention],
        assertions=assertions,
    )

    assert len(result.assertions) == 2
    assert len(result.conflicts) == 1
