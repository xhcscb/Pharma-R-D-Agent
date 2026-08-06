# Data-layer architecture

The canonical PostgreSQL database is the only source of truth. Raw artifacts are
immutable and content-addressed. Parsing, entity extraction, relation extraction,
cleaning, review, and projections are controlled and replayable steps.

## Flow

1. A source adapter discovers source records and fetches public or authorized data.
2. The object store writes immutable bytes under the SHA-256 path.
3. DocParser creates versioned elements or timestamped utterances.
4. EntityExtract creates mentions and links candidates to canonical entities.
5. RelationExtract creates evidence-backed assertions.
6. DataClean normalizes values, deduplicates assertions, and records conflicts.
7. Human review approves or rejects assertions.
8. An outbox projects approved facts to Neo4j, Milvus, TimescaleDB, and Elasticsearch.

No parser or extractor writes directly to a knowledge-store projection.


## Pipeline state and recovery

The normal path is DISCOVERED, FETCHED, PARSED, ENTITY_EXTRACTED,
RELATION_EXTRACTED, CLEANED, NEEDS_REVIEW, APPROVED, and PROJECTED. Exceptional
states are QUARANTINED, FAILED_RETRYABLE, and FAILED_FINAL. PostgreSQL workers
claim jobs with FOR UPDATE SKIP LOCKED. The idempotency key includes document
version hash, pipeline step, schema version, component version, and configuration
hash.

## Document parsing

The router handles PDF, HTML, JSON, XLSX, XBRL/XML, image, plain text, and
audio/video inputs. Hybrid PDF parsing compares native PyMuPDF, Docling,
PaddleOCR, and PP-StructureV3 candidates when installed. Low-native-text pages
trigger OCR candidates. Every selected element records parser/version,
confidence, page, bounding box, reading order, content hash, and structured
payload. Unreliable chart values remain null.

Audio is standardized by FFmpeg to mono 16 kHz PCM, transcribed with
faster-whisper VAD and word timestamps, and optionally diarized. Speaker identity
never comes from acoustic clustering alone.

## Projections

Approved facts leave PostgreSQL only through outbox events. Neo4j accepts
approved entities and evidence-backed approved assertions. Milvus owns
document_chunks, entity_descriptions, and assertion_evidence. TimescaleDB owns
the six declared event series. Elasticsearch owns documents, document_elements,
news_articles, and earnings_call_utterances. Every searchable record includes an
access class.
