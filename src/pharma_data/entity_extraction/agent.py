from collections import defaultdict

from pharma_data.contracts import EntityMention, EntityType, ParsedDocument, ReviewStatus
from pharma_data.entity_extraction.extractors import (
    DictionaryExtractor,
    MentionExtractor,
    PatternExtractor,
)
from pharma_data.utils.hashing import stable_uuid


class EntityExtractAgent:
    name = "EntityExtract"
    version = "0.2.0"

    def __init__(self, extractors: list[MentionExtractor] | None = None):
        self.extractors = extractors or [DictionaryExtractor(), PatternExtractor()]

    def extract(self, document: ParsedDocument) -> list[EntityMention]:
        groups: dict[tuple[object, ...], list[EntityMention]] = defaultdict(list)
        for extractor in self.extractors:
            for mention in extractor.extract(document):
                key = (
                    mention.element_id,
                    mention.audio_start_ms,
                    mention.char_start,
                    mention.char_end,
                    mention.entity_type,
                    mention.normalized_name.casefold(),
                )
                groups[key].append(mention)

        merged: list[EntityMention] = []
        for candidates in groups.values():
            winner = max(candidates, key=lambda item: item.confidence)
            methods = sorted({candidate.extraction_method for candidate in candidates})
            merged.append(
                winner.model_copy(
                    update={
                        "extraction_method": "+".join(methods),
                        "confidence": min(
                            0.999,
                            max(candidate.confidence for candidate in candidates)
                            + 0.01 * (len(candidates) - 1),
                        ),
                        "metadata": {**winner.metadata, "candidate_methods": methods},
                    }
                )
            )
        merged = [self._with_stable_id(document, item) for item in merged]
        merged.extend(self._derive_pipeline_programs(merged))
        merged = [self._with_stable_id(document, item) for item in merged]
        return sorted(
            merged,
            key=lambda item: (
                item.element_id or "",
                item.audio_start_ms or -1,
                item.char_start or -1,
                item.entity_type.value,
            ),
        )

    @staticmethod
    def _with_stable_id(document: ParsedDocument, mention: EntityMention) -> EntityMention:
        return mention.model_copy(
            update={
                "mention_id": stable_uuid(
                    {
                        "document_version_id": document.document_version_id,
                        "entity_type": mention.entity_type.value,
                        "normalized_name": mention.normalized_name,
                        "element_id": mention.element_id,
                        "char_start": mention.char_start,
                        "char_end": mention.char_end,
                        "audio_start_ms": mention.audio_start_ms,
                        "audio_end_ms": mention.audio_end_ms,
                    }
                )
            }
        )

    @staticmethod
    def _derive_pipeline_programs(mentions: list[EntityMention]) -> list[EntityMention]:
        grouped: dict[str, list[EntityMention]] = defaultdict(list)
        for mention in mentions:
            locator = mention.element_id or str(mention.metadata.get("utterance_id") or "")
            if locator:
                grouped[locator].append(mention)

        programs: list[EntityMention] = []
        for _locator, local_mentions in grouped.items():
            drugs = [item for item in local_mentions if item.entity_type == EntityType.DRUG]
            indications = [
                item for item in local_mentions if item.entity_type == EntityType.INDICATION
            ]
            for drug in drugs:
                nearby = sorted(
                    (
                        (EntityExtractAgent._mention_gap(drug, indication), indication)
                        for indication in indications
                    ),
                    key=lambda item: item[0],
                )
                if not nearby or nearby[0][0] > 240:
                    continue
                for _gap, indication in nearby[:1]:
                    starts = [
                        value
                        for value in (drug.char_start, indication.char_start)
                        if value is not None
                    ]
                    ends = [
                        value for value in (drug.char_end, indication.char_end) if value is not None
                    ]
                    programs.append(
                        EntityMention(
                            entity_type=EntityType.PIPELINE_PROGRAM,
                            original_text=f"{drug.original_text} / {indication.original_text}",
                            normalized_name=(
                                f"{drug.normalized_name}|{indication.normalized_name}|unspecified"
                            ),
                            element_id=drug.element_id or indication.element_id,
                            char_start=min(starts) if starts else None,
                            char_end=max(ends) if ends else None,
                            audio_start_ms=drug.audio_start_ms or indication.audio_start_ms,
                            audio_end_ms=drug.audio_end_ms or indication.audio_end_ms,
                            extraction_method="derived:pipeline_program",
                            confidence=min(drug.confidence, indication.confidence) * 0.9,
                            link_status=ReviewStatus.CANDIDATE,
                            metadata={
                                "drug_mention_id": drug.mention_id,
                                "indication_mention_id": indication.mention_id,
                                "region": "unspecified",
                                "utterance_id": drug.metadata.get("utterance_id"),
                            },
                        )
                    )
        return programs

    @staticmethod
    def _mention_gap(left: EntityMention, right: EntityMention) -> int:
        if left.char_start is None or right.char_start is None:
            return 10**9
        if (left.char_end or left.char_start) < right.char_start:
            return right.char_start - (left.char_end or left.char_start)
        if (right.char_end or right.char_start) < left.char_start:
            return left.char_start - (right.char_end or right.char_start)
        return 0
