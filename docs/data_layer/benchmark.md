# Gold benchmark format and gates

Run datactl eval benchmark GOLD.json. The JSON object contains arrays named:
native_pdf_text, scanned_pdf_text, tables, entities, entity_links, relations,
deduplicated_relations, dates, units, conflicts, and projection_ids.

Text items use {"gold": "...", "predicted": "..."}. Set-valued tasks use arrays in
gold and predicted. Link, date, unit, and projection items use scalar gold and
predicted fields. Tables contain gold and predicted HTML.

The evaluator reports character error rate, deterministic DOM-tree table
similarity, micro precision/recall/F1, pair accuracy, conflict recall, and
projection ID consistency. It enforces the project gates: native CER 0.01,
scanned CER 0.05, table score 0.85, entity F1/link accuracy 0.90, relation F1
0.85, relation dedup precision 0.98, date accuracy 0.95, unit accuracy 0.98,
conflict recall 0.90, and projection consistency 1.00.

An empty benchmark is useful only for schema smoke testing and is not evidence
that empirical quality gates have been met. Release evidence must use reviewed,
licensed Gold annotations.
