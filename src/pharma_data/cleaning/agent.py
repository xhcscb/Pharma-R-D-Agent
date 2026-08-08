from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil import parser as date_parser  # type: ignore[import-untyped]

from pharma_data.contracts import (
    AssertionCandidate,
    CleanResult,
    ConflictRecord,
    ConflictType,
    EntityMention,
    QualityLevel,
    RelationType,
)
from pharma_data.utils.hashing import stable_hash, stable_uuid
from pharma_data.utils.text import normalize_alias, normalize_text


class DataCleanAgent:
    name = "DataClean"
    version = "0.2.0"

    def clean(
        self,
        *,
        document_version_id: str,
        mentions: list[EntityMention],
        assertions: list[AssertionCandidate],
    ) -> CleanResult:
        normalized_mentions, normalization_log = self._normalize_mentions(mentions)
        normalized_assertions, assertion_log = self._normalize_assertions(assertions)
        normalization_log.extend(assertion_log)
        deduplicated_assertions = self._deduplicate_assertions(normalized_assertions)
        conflicts = self._detect_conflicts(deduplicated_assertions)
        if conflicts:
            quality = QualityLevel.CONFLICT
        elif deduplicated_assertions and all(
            item.evidence_element_id or item.evidence_utterance_id
            for item in deduplicated_assertions
        ):
            quality = QualityLevel.SILVER
        else:
            quality = QualityLevel.CANDIDATE
        return CleanResult(
            document_version_id=document_version_id,
            mentions=normalized_mentions,
            assertions=deduplicated_assertions,
            conflicts=conflicts,
            quality_level=quality,
            normalization_log=normalization_log,
        )

    def _normalize_mentions(
        self, mentions: list[EntityMention]
    ) -> tuple[list[EntityMention], list[dict[str, Any]]]:
        unique: dict[tuple[Any, ...], EntityMention] = {}
        log: list[dict[str, Any]] = []
        for mention in mentions:
            normalized_name = normalize_text(mention.normalized_name)
            key = (
                mention.entity_type,
                normalize_alias(normalized_name),
                mention.element_id,
                mention.audio_start_ms,
                mention.char_start,
                mention.char_end,
            )
            candidate = mention.model_copy(update={"normalized_name": normalized_name})
            existing = unique.get(key)
            if existing is None or candidate.confidence > existing.confidence:
                unique[key] = candidate
            if mention.normalized_name != normalized_name:
                log.append(
                    {
                        "type": "entity_text_normalization",
                        "mention_id": mention.mention_id,
                        "before": mention.normalized_name,
                        "after": normalized_name,
                    }
                )
        return list(unique.values()), log

    def _normalize_assertions(
        self, assertions: list[AssertionCandidate]
    ) -> tuple[list[AssertionCandidate], list[dict[str, Any]]]:
        unit_map = {
            "\u4ebf\u5143": ("CNY", Decimal("100000000")),
            "\u4e07\u5143": ("CNY", Decimal("10000")),
            "\u5143": ("CNY", Decimal("1")),
            "\u4ebf": ("count", Decimal("100000000")),
            "\u4e07": ("count", Decimal("10000")),
            "%": ("percent", Decimal("0.01")),
        }
        normalized: list[AssertionCandidate] = []
        log: list[dict[str, Any]] = []
        for assertion in assertions:
            raw_unit = normalize_text(assertion.object_unit or "")
            canonical_unit, scale = unit_map.get(raw_unit, (raw_unit or None, Decimal("1")))
            qualifiers = dict(assertion.qualifiers)
            if assertion.object_value is not None:
                numeric = self._normalize_number(assertion.object_value)
                if isinstance(numeric, Decimal):
                    qualifiers["normalized_numeric_value"] = str(numeric * scale)
                    qualifiers["scale"] = str(scale)
                    if canonical_unit == "CNY":
                        qualifiers["currency"] = "CNY"
            if raw_unit:
                qualifiers["raw_unit"] = raw_unit
            candidate = assertion.model_copy(
                update={"object_unit": canonical_unit, "qualifiers": qualifiers}
            )
            normalized.append(candidate)
            if assertion.object_unit != canonical_unit:
                log.append(
                    {
                        "type": "unit_normalization",
                        "assertion_id": assertion.assertion_id,
                        "before": assertion.object_unit,
                        "after": canonical_unit,
                        "scale": str(scale),
                    }
                )
        return normalized, log

    def _deduplicate_assertions(
        self, assertions: list[AssertionCandidate]
    ) -> list[AssertionCandidate]:
        unique: dict[str, AssertionCandidate] = {}
        for assertion in assertions:
            key = stable_hash(
                {
                    "subject": assertion.subject_mention_id,
                    "predicate": assertion.predicate.value,
                    "object": assertion.object_mention_id or assertion.object_value,
                    "unit": assertion.object_unit,
                    "qualifiers": assertion.qualifiers,
                    "valid_from": assertion.valid_from,
                    "valid_to": assertion.valid_to,
                }
            )
            candidate = assertion.model_copy(update={"assertion_id": stable_uuid(key)})
            existing = unique.get(key)
            if existing is None or candidate.confidence > existing.confidence:
                unique[key] = candidate
        return list(unique.values())

    def _detect_conflicts(self, assertions: list[AssertionCandidate]) -> list[ConflictRecord]:
        groups: dict[tuple[str, str], list[AssertionCandidate]] = defaultdict(list)
        for assertion in assertions:
            if assertion.predicate not in {RelationType.HAS_STAGE, RelationType.REPORTS}:
                continue
            groups[(assertion.subject_mention_id, assertion.predicate.value)].append(assertion)

        conflicts: list[ConflictRecord] = []
        for (_, _), values in groups.items():
            if len(values) < 2:
                continue
            normalized_objects = {
                (
                    item.object_mention_id,
                    self._normalize_number(item.object_value),
                    item.object_unit,
                )
                for item in values
            }
            if len(normalized_objects) <= 1:
                continue
            units = {item.object_unit for item in values if item.object_unit}
            as_of_dates = {item.as_of_date for item in values if item.as_of_date}
            scopes = {stable_hash(item.qualifiers) for item in values}
            if len(units) > 1:
                conflict_type = ConflictType.UNIT_DIFFERENCE
                rationale = "Assertions use different units and cannot be compared directly"
            elif len(as_of_dates) > 1:
                conflict_type = ConflictType.TEMPORAL_DIFFERENCE
                rationale = "Assertions refer to different as-of dates"
            elif len(scopes) > 1:
                conflict_type = ConflictType.SCOPE_DIFFERENCE
                rationale = "Assertions have different qualifiers or business scopes"
            else:
                conflict_type = ConflictType.TRUE_CONTRADICTION
                rationale = "Assertions share subject, predicate, time and scope but disagree"
            conflicts.append(
                ConflictRecord(
                    conflict_type=conflict_type,
                    conflict_id=stable_uuid(
                        [conflict_type.value, sorted(item.assertion_id for item in values)]
                    ),
                    assertion_ids=[item.assertion_id for item in values],
                    rationale=rationale,
                )
            )
        return conflicts

    @staticmethod
    def _normalize_number(value: str | None) -> Decimal | str | None:
        if value is None:
            return None
        candidate = normalize_text(value).replace(",", "")
        multipliers = {"\u4e07": Decimal("10000"), "\u4ebf": Decimal("100000000")}
        multiplier = Decimal("1")
        for suffix, factor in multipliers.items():
            if candidate.endswith(suffix):
                candidate = candidate[: -len(suffix)]
                multiplier = factor
                break
        try:
            return Decimal(candidate.rstrip("%")) * multiplier
        except InvalidOperation:
            return candidate

    @staticmethod
    def normalize_date(value: str) -> str:
        return str(date_parser.parse(value).isoformat())
