import json
import re
from pathlib import Path
from typing import Any, Protocol

from pharma_data.contracts import (
    EntityMention,
    EntityType,
    ParsedDocument,
    ReviewStatus,
)
from pharma_data.utils.text import normalize_text


class MentionExtractor(Protocol):
    name: str

    def extract(self, document: ParsedDocument) -> list[EntityMention]: ...


class DictionaryExtractor:
    name = "dictionary"

    def __init__(self, lexicon_path: str | Path | None = None):
        self.entries: list[dict[str, Any]] = []
        if lexicon_path:
            payload = json.loads(Path(lexicon_path).read_text(encoding="utf-8"))
            for entity_type, entries in payload.items():
                for entry in entries:
                    self.entries.append(
                        {
                            "entity_type": EntityType(entity_type),
                            "canonical_name": entry["canonical_name"],
                            "external_ids": entry.get("external_ids", {}),
                            "aliases": sorted(
                                set(entry.get("aliases", []) + [entry["canonical_name"]]),
                                key=len,
                                reverse=True,
                            ),
                        }
                    )

    def extract(self, document: ParsedDocument) -> list[EntityMention]:
        mentions: list[EntityMention] = []
        for element in document.elements:
            mentions.extend(self._extract_text(element.text, element.element_id))
        for utterance in document.utterances:
            for mention in self._extract_text(utterance.normalized_transcript, None):
                mentions.append(
                    mention.model_copy(
                        update={
                            "audio_start_ms": utterance.start_ms,
                            "audio_end_ms": utterance.end_ms,
                            "metadata": {
                                **mention.metadata,
                                "utterance_id": utterance.utterance_id,
                            },
                        }
                    )
                )
        return mentions

    def _extract_text(self, text: str, element_id: str | None) -> list[EntityMention]:
        mentions: list[EntityMention] = []
        folded = text.casefold()
        for entry in self.entries:
            occupied: list[tuple[int, int]] = []
            for alias in entry["aliases"]:
                start = 0
                alias_folded = alias.casefold()
                while (index := folded.find(alias_folded, start)) >= 0:
                    end = index + len(alias)
                    start = end
                    if any(index < right and end > left for left, right in occupied):
                        continue
                    occupied.append((index, end))
                    mentions.append(
                        EntityMention(
                            entity_type=entry["entity_type"],
                            original_text=text[index:end],
                            normalized_name=entry["canonical_name"],
                            element_id=element_id,
                            char_start=index,
                            char_end=end,
                            extraction_method=self.name,
                            confidence=0.99,
                            link_status=ReviewStatus.PENDING,
                            metadata={
                                "external_ids": entry["external_ids"],
                                "matched_alias": alias,
                            },
                        )
                    )
        return mentions


class PatternExtractor:
    name = "pattern"

    PATTERNS: list[tuple[EntityType, re.Pattern[str], float]] = [
        (EntityType.CLINICAL_TRIAL, re.compile(r"\bNCT\d{8}\b", re.I), 0.99),
        (
            EntityType.CLINICAL_STAGE,
            re.compile(
                r"(?<![A-Za-z0-9])(?:I{1,3}|IV|1|2|3|4)\s*(?:\u671f|phase)(?![A-Za-z])",
                re.I,
            ),
            0.95,
        ),
        (
            EntityType.TARGET,
            re.compile(
                r"\b(?:PD-?1|PD-?L1|EGFR|HER2|BTK|VEGF|CD19|CD20|KRAS|ALK)\b",
                re.I,
            ),
            0.92,
        ),
        (
            EntityType.REGULATORY_AGENCY,
            re.compile(
                r"\b(?:NMPA|CDE|FDA|EMA|\u56fd\u5bb6\u836f\u76d1\u5c40|\u836f\u5ba1\u4e2d\u5fc3)\b",
                re.I,
            ),
            0.98,
        ),
        (
            EntityType.COMPANY,
            re.compile(
                r"[\u4e00-\u9fff]{2,16}(?:\u533b\u836f|\u751f\u7269|\u5236\u836f|\u836f\u4e1a|\u533b\u7597)(?:\u80a1\u4efd)?(?:\u6709\u9650\u516c\u53f8)?"
            ),
            0.78,
        ),
        (
            EntityType.FINANCIAL_METRIC,
            re.compile(
                r"(?:\u8425\u4e1a\u6536\u5165|\u7814\u53d1\u8d39\u7528|\u51c0\u5229\u6da6|\u6bdb\u5229\u7387|\u7ecf\u8425\u73b0\u91d1\u6d41|\u6bcf\u80a1\u6536\u76ca|EPS)"
            ),
            0.96,
        ),
    ]

    def extract(self, document: ParsedDocument) -> list[EntityMention]:
        mentions: list[EntityMention] = []
        for element in document.elements:
            mentions.extend(self._extract_text(element.text, element.element_id))
        for utterance in document.utterances:
            extracted = self._extract_text(utterance.normalized_transcript, None)
            mentions.extend(
                mention.model_copy(
                    update={
                        "audio_start_ms": utterance.start_ms,
                        "audio_end_ms": utterance.end_ms,
                        "metadata": {
                            **mention.metadata,
                            "utterance_id": utterance.utterance_id,
                        },
                    }
                )
                for mention in extracted
            )
        return mentions

    def _extract_text(self, text: str, element_id: str | None) -> list[EntityMention]:
        mentions: list[EntityMention] = []
        for entity_type, pattern, confidence in self.PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                mentions.append(
                    EntityMention(
                        entity_type=entity_type,
                        original_text=value,
                        normalized_name=normalize_text(value).upper()
                        if entity_type
                        in {
                            EntityType.TARGET,
                            EntityType.CLINICAL_TRIAL,
                            EntityType.REGULATORY_AGENCY,
                        }
                        else normalize_text(value),
                        element_id=element_id,
                        char_start=match.start(),
                        char_end=match.end(),
                        extraction_method=self.name,
                        confidence=confidence,
                        link_status=ReviewStatus.CANDIDATE,
                    )
                )
        return mentions


class TransformerNERExtractor:
    name = "transformer_ner"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name
        self._pipeline: Any | None = None

    def _load(self) -> Any:
        if not self.model_name:
            return None
        if self._pipeline is None:
            try:
                from transformers import pipeline
            except ImportError as exc:
                raise RuntimeError("Transformer NER requires the optional 'ml' dependency") from exc
            self._pipeline = pipeline(
                "token-classification",
                model=self.model_name,
                aggregation_strategy="simple",
            )
        return self._pipeline

    def extract(self, document: ParsedDocument) -> list[EntityMention]:
        model = self._load()
        if model is None:
            return []
        mentions: list[EntityMention] = []
        for element in document.elements:
            for item in model(element.text):
                try:
                    entity_type = EntityType(item["entity_group"])
                except ValueError:
                    continue
                mentions.append(
                    EntityMention(
                        entity_type=entity_type,
                        original_text=item["word"],
                        normalized_name=normalize_text(item["word"]),
                        element_id=element.element_id,
                        char_start=item["start"],
                        char_end=item["end"],
                        extraction_method=f"{self.name}:{self.model_name}",
                        confidence=float(item["score"]),
                    )
                )
        return mentions
