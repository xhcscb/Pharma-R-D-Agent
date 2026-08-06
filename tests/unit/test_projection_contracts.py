from pharma_data.config import Settings
from pharma_data.storage.elasticsearch.projector import ElasticsearchProjector
from pharma_data.storage.milvus.projector import HashingEmbedder, MilvusProjector
from pharma_data.storage.timescale.projector import TimescaleProjector


def test_projection_store_contracts_match_architecture() -> None:
    settings = Settings(_env_file=None)
    assert MilvusProjector(settings).collections == (
        "document_chunks",
        "entity_descriptions",
        "assertion_evidence",
    )
    assert ElasticsearchProjector(settings).indices == (
        "documents",
        "document_elements",
        "news_articles",
        "earnings_call_utterances",
    )
    assert TimescaleProjector(settings).tables == (
        "market_price",
        "financial_metric_series",
        "clinical_event",
        "regulatory_event",
        "news_event",
        "assertion_version_event",
    )


def test_hashing_embedding_is_versioned_normalized_and_deterministic() -> None:
    embedder = HashingEmbedder(64)
    first = embedder.encode("clinical evidence")
    second = embedder.encode("clinical evidence")

    assert first == second
    assert len(first) == 64
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9
