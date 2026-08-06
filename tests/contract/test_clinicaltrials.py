import respx
from httpx import Response

from pharma_data.connectors.clinical import ClinicalTrialsGovAdapter


@respx.mock
def test_clinicaltrials_adapter_preserves_full_json() -> None:
    study = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000001",
                "briefTitle": "Drug study",
            },
            "statusModule": {"studyFirstPostDateStruct": {"date": "2025-01-01"}},
        },
        "derivedSection": {"miscInfoModule": {"versionHolder": "2026-01-01"}},
    }
    respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
        return_value=Response(200, json={"studies": [study]})
    )
    adapter = ClinicalTrialsGovAdapter()
    page = adapter.discover({"condition": "oncology", "page_size": 10})
    fetched = adapter.fetch(page.records[0])[0]

    assert page.records[0].source_record_id == "NCT00000001"
    assert b"derivedSection" in fetched.content
