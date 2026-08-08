import json

from pharma_data.contracts import DocumentType, RelationType
from pharma_data.entity_extraction import DictionaryExtractor, EntityExtractAgent, PatternExtractor
from pharma_data.parsers.structured import JsonParser
from pharma_data.relation_extraction import RelationExtractAgent


def test_openfda_field_element_yields_localized_drug_indication_relation(tmp_path) -> None:
    path = tmp_path / "label.json"
    payload = {
        "id": "label-1",
        "indications_and_usage": [
            "KEYTRUDA is indicated for the treatment of patients with NSCLC."
        ],
        "warnings": ["Unrelated warning text."],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = JsonParser().parse(
        path,
        document_id="doc",
        document_version_id="version",
        document_type=DocumentType.REGULATORY,
        artifact_id="artifact",
    )
    mentions = EntityExtractAgent(
        [DictionaryExtractor("config/entities.json"), PatternExtractor()]
    ).extract(parsed)
    assertions = RelationExtractAgent().extract(parsed, mentions)

    treats = [item for item in assertions if item.predicate == RelationType.TREATS]
    assert len(treats) == 1
    evidence = next(
        item for item in parsed.elements if item.element_id == treats[0].evidence_element_id
    )
    assert evidence.structured_payload["json_path"] == "$.indications_and_usage"
    assert "KEYTRUDA" in treats[0].evidence_text
