# Canonical data model

PostgreSQL is the only source of truth. The schema is created by Alembic revision
0001_initial and contains source, artifact, document-version, processing, evidence,
fact, review, outbox, projection-checkpoint, snapshot, and audit records.

Stable IDs are derived from document version, evidence location, and normalized
content for document elements, entity mentions, assertions, conflicts, and audio
utterances. Reprocessing the same version therefore updates lineage without
duplicating facts.

An Assertion stores subject, predicate, entity or literal object, unit, qualifiers,
valid time, as-of date, assertion mode, confidence, and review state. Evidence is a
separate record containing the document version plus PDF page/bounding box or audio
utterance/time range. Approval is rejected when evidence is missing.

Conflicts preserve every source assertion. Resolution is additive and never
implements last-value-wins deletion.
