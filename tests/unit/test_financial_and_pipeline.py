from pharma_data.cleaning import DataCleanAgent
from pharma_data.contracts import DocumentType, ElementType, ParsedDocument, RelationType
from pharma_data.entity_extraction import DictionaryExtractor, EntityExtractAgent, PatternExtractor
from pharma_data.parsers.common import make_element
from pharma_data.relation_extraction import RelationExtractAgent


def _document(text: str) -> ParsedDocument:
    element = make_element(
        document_version_id="version",
        element_type=ElementType.PARAGRAPH,
        reading_order=0,
        text=text,
        parser_name="test",
        parser_version="1",
    )
    return ParsedDocument(
        document_id="document",
        document_version_id="version",
        document_type=DocumentType.FINANCIAL_REPORT,
        elements=[element],
    )


def test_financial_metric_keeps_raw_value_and_normalizes_scale() -> None:
    document = _document("\u6052\u745e\u533b\u836f\u8425\u4e1a\u6536\u5165100\u4ebf\u5143")
    mentions = EntityExtractAgent([PatternExtractor()]).extract(document)
    assertions = RelationExtractAgent().extract(document, mentions)
    cleaned = DataCleanAgent().clean(
        document_version_id="version",
        mentions=mentions,
        assertions=assertions,
    )

    metric = next(item for item in cleaned.assertions if item.predicate == RelationType.REPORTS)
    assert metric.object_value == "100"
    assert metric.object_unit == "CNY"
    assert metric.qualifiers["raw_unit"] == "\u4ebf\u5143"
    assert metric.qualifiers["scale"] == "100000000"
    assert metric.qualifiers["normalized_numeric_value"] == "10000000000"


def test_pipeline_stage_is_attached_to_drug_indication_region_program() -> None:
    document = _document(
        "\u5361\u745e\u5229\u73e0\u5355\u6297\u7528\u4e8e\u6cbb\u7597"
        "\u975e\u5c0f\u7ec6\u80de\u80ba\u764c\uff0c\u5df2\u8fdb\u5165III\u671f\u9636\u6bb5\u3002"
    )
    mentions = EntityExtractAgent(
        [DictionaryExtractor("config/entities.json"), PatternExtractor()]
    ).extract(document)
    assertions = RelationExtractAgent().extract(document, mentions)

    stage = next(item for item in assertions if item.predicate == RelationType.HAS_STAGE)
    program = next(item for item in mentions if item.mention_id == stage.subject_mention_id)
    assert program.normalized_name.endswith("|unspecified")
