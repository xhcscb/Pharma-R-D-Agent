# Data governance

A1 covers regulators, exchanges, and official trial registries. A2 covers issuer
filings, IR publications, and official calls. B1 covers public or licensed
sell-side research. B2 covers peer-reviewed literature and recognized databases.

license_status is mandatory: public, authorized_restricted, metadata_only,
prohibited, or unknown. Unknown and prohibited records are quarantined. Public
snapshots contain only public document versions. Restricted raw content never
belongs in Git.

Every approved assertion must reference a document element or an audio utterance.
Conflicting assertions remain immutable. Resolution adds review records; it never
deletes the disagreeing source claims.

Models create Candidate or Silver data. Only an explicit review decision creates
Gold data and outbox events for knowledge-store projection.
