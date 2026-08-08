import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from pharma_data.contracts import (
    AssertionCandidate,
    AssertionMode,
    EntityMention,
    EntityType,
    ParsedDocument,
    RelationType,
)


@dataclass(frozen=True)
class RelationRule:
    subject_type: EntityType
    object_type: EntityType
    predicate: RelationType
    keywords: tuple[str, ...]
    confidence: float


RULES = [
    RelationRule(
        EntityType.COMPANY,
        EntityType.DRUG,
        RelationType.DEVELOPS,
        ("\u7814\u53d1", "\u5f00\u53d1", "develop"),
        0.88,
    ),
    RelationRule(
        EntityType.COMPANY,
        EntityType.CLINICAL_TRIAL,
        RelationType.SPONSORS,
        ("\u7533\u529e", "sponsor"),
        0.90,
    ),
    RelationRule(
        EntityType.DRUG,
        EntityType.TARGET,
        RelationType.TARGETS,
        ("\u9776\u5411", "\u6291\u5236\u5242", "target"),
        0.90,
    ),
    RelationRule(
        EntityType.DRUG,
        EntityType.INDICATION,
        RelationType.TREATS,
        ("\u6cbb\u7597", "\u9002\u5e94\u75c7", "\u7528\u4e8e", "treat"),
        0.87,
    ),
    RelationRule(
        EntityType.DRUG,
        EntityType.CLINICAL_TRIAL,
        RelationType.IN_TRIAL,
        ("\u8bd5\u9a8c", "\u7814\u7a76", "trial"),
        0.84,
    ),
    RelationRule(
        EntityType.CLINICAL_TRIAL,
        EntityType.PIPELINE_PROGRAM,
        RelationType.STUDIES,
        ("\u8bd5\u9a8c", "\u7814\u7a76", "trial"),
        0.82,
    ),
    RelationRule(
        EntityType.PIPELINE_PROGRAM,
        EntityType.CLINICAL_STAGE,
        RelationType.HAS_STAGE,
        ("\u5904\u4e8e", "\u8fdb\u5165", "\u9636\u6bb5", "phase"),
        0.90,
    ),
    RelationRule(
        EntityType.PERSON,
        EntityType.COMPANY,
        RelationType.REPRESENTS,
        ("\u8463\u4e8b\u957f", "\u603b\u7ecf\u7406", "\u9996\u5e2d", "\u4ee3\u8868", "CEO", "CFO"),
        0.83,
    ),
]


class RelationExtractAgent:
    name = "RelationExtract"
    version = "0.2.0"

    def extract(
        self, document: ParsedDocument, mentions: list[EntityMention]
    ) -> list[AssertionCandidate]:
        element_text = {item.element_id: item.text for item in document.elements}
        utterance_text = {
            item.utterance_id: item.normalized_transcript for item in document.utterances
        }
        grouped: dict[str, list[EntityMention]] = defaultdict(list)
        for mention in mentions:
            locator = mention.element_id or str(mention.metadata.get("utterance_id") or "")
            if locator:
                grouped[locator].append(mention)

        assertions: list[AssertionCandidate] = []
        seen: set[tuple[str, str, str, str]] = set()
        for locator, local_mentions in grouped.items():
            text = element_text.get(locator) or utterance_text.get(locator) or ""
            folded = text.casefold()
            for rule in RULES:
                if not any(keyword.casefold() in folded for keyword in rule.keywords):
                    continue
                subjects = [
                    mention
                    for mention in local_mentions
                    if mention.entity_type == rule.subject_type
                ]
                objects = [
                    mention for mention in local_mentions if mention.entity_type == rule.object_type
                ]
                for subject in subjects:
                    for obj in objects:
                        local_context = self._local_context(text, subject, obj)
                        if not any(
                            keyword.casefold() in local_context.casefold()
                            for keyword in rule.keywords
                        ):
                            continue
                        key = (
                            subject.mention_id,
                            rule.predicate.value,
                            obj.mention_id,
                            locator,
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        assertions.append(
                            AssertionCandidate(
                                subject_mention_id=subject.mention_id,
                                predicate=rule.predicate,
                                object_mention_id=obj.mention_id,
                                evidence_element_id=locator if locator in element_text else None,
                                evidence_utterance_id=locator
                                if locator in utterance_text
                                else None,
                                evidence_text=local_context,
                                extraction_method=f"schema_rule:{rule.predicate.value}",
                                confidence=min(
                                    rule.confidence,
                                    subject.confidence,
                                    obj.confidence,
                                ),
                            )
                        )

            companies = [
                mention for mention in local_mentions if mention.entity_type == EntityType.COMPANY
            ]
            if len(companies) >= 2 and any(
                word in folded for word in ("\u5408\u4f5c", "\u6388\u6743", "license", "partner")
            ):
                for left, right in combinations(companies, 2):
                    key = (
                        left.mention_id,
                        RelationType.PARTNERS_WITH.value,
                        right.mention_id,
                        locator,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    assertions.append(
                        AssertionCandidate(
                            subject_mention_id=left.mention_id,
                            predicate=RelationType.PARTNERS_WITH,
                            object_mention_id=right.mention_id,
                            evidence_element_id=locator if locator in element_text else None,
                            evidence_utterance_id=locator if locator in utterance_text else None,
                            evidence_text=text,
                            extraction_method="schema_rule:PARTNERS_WITH",
                            confidence=min(0.86, left.confidence, right.confidence),
                        )
                    )
        assertions.extend(self._numeric_assertions(grouped, element_text, utterance_text))
        return assertions

    @staticmethod
    def _local_context(
        text: str,
        subject: EntityMention,
        obj: EntityMention,
        padding: int = 240,
        max_span: int = 800,
    ) -> str:
        if subject.char_start is None or obj.char_start is None:
            return text[: max_span + 2 * padding]
        left = min(subject.char_start, obj.char_start)
        right = max(subject.char_end or subject.char_start, obj.char_end or obj.char_start)
        if right - left > max_span:
            return ""
        return text[max(0, left - padding) : min(len(text), right + padding)]

    @staticmethod
    def _numeric_assertions(
        grouped: dict[str, list[EntityMention]],
        element_text: dict[str, str],
        utterance_text: dict[str, str],
    ) -> list[AssertionCandidate]:
        results: list[AssertionCandidate] = []
        for locator, local_mentions in grouped.items():
            text = element_text.get(locator) or utterance_text.get(locator) or ""
            metrics = [
                item for item in local_mentions if item.entity_type == EntityType.FINANCIAL_METRIC
            ]
            companies = [item for item in local_mentions if item.entity_type == EntityType.COMPANY]
            for metric in metrics:
                value_pattern = r".{0,24}?([+-]?\d[\d,.]*)"
                unit_pattern = r"(\s*(?:\u4ebf\u5143|\u4e07\u5143|\u4ebf|\u4e07|%|\u5143))?"
                pattern = re.compile(re.escape(metric.original_text) + value_pattern + unit_pattern)
                match = pattern.search(text, metric.char_start or 0)
                if match is None:
                    continue
                subject = companies[0] if companies else metric
                results.append(
                    AssertionCandidate(
                        subject_mention_id=subject.mention_id,
                        predicate=RelationType.REPORTS,
                        object_value=match.group(1),
                        object_unit=(match.group(2) or "").strip() or None,
                        qualifiers={
                            "metric_name": metric.normalized_name,
                            "raw_value": match.group(0),
                            "value_kind": "reported",
                        },
                        evidence_element_id=locator if locator in element_text else None,
                        evidence_utterance_id=locator if locator in utterance_text else None,
                        evidence_text=text,
                        extraction_method="schema_rule:FINANCIAL_METRIC",
                        confidence=min(0.86, subject.confidence, metric.confidence),
                    )
                )
        return results

    def derive_competition(
        self,
        assertions: list[AssertionCandidate],
        mentions: list[EntityMention],
    ) -> list[AssertionCandidate]:
        mention_map = {item.mention_id: item for item in mentions}
        target_to_drugs: dict[str, set[str]] = defaultdict(set)
        evidence: dict[tuple[str, str], AssertionCandidate] = {}
        for assertion in assertions:
            if (
                assertion.predicate == RelationType.TARGETS
                and assertion.object_mention_id
                and assertion.subject_mention_id in mention_map
                and assertion.object_mention_id in mention_map
            ):
                target_name = mention_map[assertion.object_mention_id].normalized_name
                drug_id = assertion.subject_mention_id
                target_to_drugs[target_name].add(drug_id)
                evidence[(target_name, drug_id)] = assertion

        derived: list[AssertionCandidate] = []
        for target_name, drug_ids in target_to_drugs.items():
            for left, right in combinations(sorted(drug_ids), 2):
                source = evidence[(target_name, left)]
                derived.append(
                    AssertionCandidate(
                        subject_mention_id=left,
                        predicate=RelationType.COMPETES_WITH,
                        object_mention_id=right,
                        qualifiers={
                            "derivation_rule": "shared_target",
                            "shared_target": target_name,
                            "requires_indication_region_validation": True,
                        },
                        assertion_mode=AssertionMode.DERIVED,
                        evidence_element_id=source.evidence_element_id,
                        evidence_utterance_id=source.evidence_utterance_id,
                        evidence_text=source.evidence_text,
                        extraction_method="derived:shared_target",
                        confidence=0.55,
                    )
                )
        return derived
