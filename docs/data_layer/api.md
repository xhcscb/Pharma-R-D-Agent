# Query interfaces

REST is available at /docs and GraphQL at /graphql.

Public reads default to public access. Requests for team_internal or restricted
content require the X-Internal-API-Key header matching INTERNAL_API_KEY. A failed
authorization returns 403; an inaccessible document or assertion returns 404.

Implemented REST operations:

- POST /v1/ingestions
- GET /v1/ingestions/{id}
- POST /v1/documents/{id}/reprocess
- GET /v1/documents/{id}
- GET /v1/documents/{id}/elements
- GET /v1/entities/{id}
- GET /v1/assertions/{id}
- GET /v1/conflicts
- GET /v1/review-queue
- POST /v1/reviews and POST /v1/reviews/{target_type}/{target_id}
- POST /v1/search
- POST /v1/projections/{name}/rebuild
- GET /v1/projections/{name}/status
- POST /v1/dataset-snapshots

GraphQL exposes document, entity, entityNeighbors, entityTimeline,
searchDocuments, searchEvidence, assertion, and conflictGroup.
