import re
from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

from pharma_data.contracts import (
    AssertionCandidate,
    AssertionMode,
    DocumentElement,
    ElementType,
    EntityMention,
    EntityType,
    ParsedDocument,
    RelationType,
    TableCell,
)

FINANCIAL_METRICS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"被合并方(?:在合并前实现的|实现的)?净利润(?:[（(].*[）)])?"),
        "被合并方净利润",
    ),
    (re.compile(r"扣除非经常性损益后的净利润(?:[（(].*[）)])?"), "扣非净利润"),
    (re.compile(r"归属于(?:上市公司|母公司)股东的净利润(?:[（(].*[）)])?"), "归母净利润"),
    (
        re.compile(r"(?:经营活动产生的现金流量净额|经营现金流)(?:[（(].*[）)])?"),
        "经营活动现金流量净额",
    ),
    (re.compile(r"归属于母公司所有者权益(?:[（(].*[）)])?"), "归属于母公司所有者权益"),
    (re.compile(r"(?:所有者权益合计|股东权益合计)(?:[（(].*[）)])?"), "所有者权益合计"),
    (re.compile(r"基本每股收益(?:[（(].*[）)])?"), "基本每股收益"),
    (re.compile(r"稀释每股收益(?:[（(].*[）)])?"), "稀释每股收益"),
    (re.compile(r"(?:每股收益|EPS)(?:[（(].*[）)])?", re.I), "每股收益"),
    (re.compile(r"(?:资产总计|总资产)(?:[（(].*[）)])?"), "资产总计"),
    (re.compile(r"(?:负债合计|总负债)(?:[（(].*[）)])?"), "负债合计"),
    (re.compile(r"营业收入(?:[（(].*[）)])?"), "营业收入"),
    (re.compile(r"研发费用(?:[（(].*[）)])?"), "研发费用"),
    (re.compile(r"累计研发投入(?:[（(].*[）)])?"), "累计研发投入"),
    (re.compile(r"费用化研发投入(?:[（(].*[）)])?"), "费用化研发投入"),
    (re.compile(r"资本化研发投入(?:[（(].*[）)])?"), "资本化研发投入"),
    (re.compile(r"研发投入(?:[（(].*[）)])?"), "研发投入"),
    (re.compile(r"净利润(?:[（(].*[）)])?"), "净利润"),
    (re.compile(r"毛利率(?:[（(].*[）)])?"), "毛利率"),
    (re.compile(r"货币资金(?:[（(].*[）)])?"), "货币资金"),
    (re.compile(r"应收账款(?:[（(].*[）)])?"), "应收账款"),
    (re.compile(r"存货(?:[（(].*[）)])?"), "存货"),
    (re.compile(r"固定资产(?:[（(].*[）)])?"), "固定资产"),
    (re.compile(r"无形资产(?:[（(].*[）)])?"), "无形资产"),
)

CHANGE_COLUMN_PATTERN = re.compile(r"变动|增减|同比|增长(?:率)?|较上|百分比")
PERIOD_HEADER_PATTERN = re.compile(
    r"(?:20\d{2}|本报告期|本期|本年|期末|期初|年初|上年同期|上期同期|"
    r"上年末|上年度末|第一季度|半年度|年度|Q[1-4]|H1)",
    re.I,
)
PERCENT_METRICS = {"毛利率"}


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
        EntityType.CLINICAL_STAGE,
        RelationType.HAS_STAGE,
        ("试验", "研究", "期", "phase"),
        0.88,
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
        element_map = {item.element_id: item for item in document.elements}
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
            element = element_map.get(locator)
            visual_payload = (
                element.structured_payload.get("visual_semantics", {}) if element else {}
            )
            for rule in RULES:
                if (
                    isinstance(visual_payload, dict)
                    and visual_payload.get("observation")
                    and rule.predicate == RelationType.HAS_STAGE
                ):
                    continue
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
                    local_context = self._local_context(
                        text,
                        left,
                        right,
                        padding=120,
                        max_span=400,
                    )
                    if not local_context or not any(
                        word in local_context.casefold()
                        for word in ("\u5408\u4f5c", "\u6388\u6743", "license", "partner")
                    ):
                        continue
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
                            evidence_text=local_context,
                            extraction_method="schema_rule:PARTNERS_WITH",
                            confidence=min(0.86, left.confidence, right.confidence),
                        )
                    )
        table_element_ids = {
            item.element_id
            for item in document.elements
            if item.element_type == ElementType.TABLE
        }
        assertions.extend(
            self._numeric_assertions(
                grouped,
                element_text,
                utterance_text,
                excluded_element_ids=table_element_ids,
            )
        )
        assertions.extend(
            self._table_metric_assertions(document, mentions, element_map, grouped)
        )
        assertions.extend(self._visual_pipeline_assertions(element_map, grouped))
        return assertions

    @staticmethod
    def _visual_pipeline_assertions(
        element_map: dict[str, DocumentElement],
        grouped: dict[str, list[EntityMention]],
    ) -> list[AssertionCandidate]:
        results: list[AssertionCandidate] = []
        for element_id, element in element_map.items():
            visual = element.structured_payload.get("visual_semantics", {})
            if not isinstance(visual, dict) or visual.get("status") != "verified":
                continue
            observation = visual.get("observation")
            if not isinstance(observation, dict):
                continue
            local_mentions = grouped.get(element_id, [])
            programs = [
                item
                for item in local_mentions
                if item.entity_type == EntityType.PIPELINE_PROGRAM
            ]
            stage_candidates = [
                item
                for item in local_mentions
                if item.entity_type == EntityType.CLINICAL_STAGE
                and item.original_text == observation.get("stage_label")
            ]
            grounded_stages = [
                item
                for item in stage_candidates
                if item.metadata.get("visual_field") == "stage"
            ]
            stage = max(
                grounded_stages or stage_candidates,
                key=lambda item: item.confidence,
                default=None,
            )
            if len(programs) != 1 or stage is None:
                continue
            confidence = min(
                float(observation.get("confidence") or element.confidence),
                programs[0].confidence,
                stage.confidence,
            )
            results.append(
                AssertionCandidate(
                    subject_mention_id=programs[0].mention_id,
                    predicate=RelationType.HAS_STAGE,
                    object_mention_id=stage.mention_id,
                    qualifiers={
                        "region": observation.get("region"),
                        "stage_normalized": observation.get("stage"),
                        "source_structure": "visual_chart_geometry",
                        "bar_color": observation.get("bar_color"),
                        "bar_bbox_pixels": observation.get("bar_bbox_pixels"),
                        "stage_column_bbox_pixels": observation.get(
                            "stage_column_bbox_pixels"
                        ),
                        "derivation": observation.get("derivation"),
                        "visual_asset": visual.get("asset"),
                    },
                    assertion_mode=AssertionMode.DERIVED,
                    evidence_element_id=element_id,
                    evidence_text=element.text,
                    extraction_method="visual_geometry:PIPELINE_HAS_STAGE",
                    confidence=confidence,
                )
            )
        return results

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
        *,
        excluded_element_ids: set[str] | None = None,
    ) -> list[AssertionCandidate]:
        results: list[AssertionCandidate] = []
        for locator, local_mentions in grouped.items():
            if locator in (excluded_element_ids or set()):
                continue
            text = element_text.get(locator) or utterance_text.get(locator) or ""
            metrics = [
                item for item in local_mentions if item.entity_type == EntityType.FINANCIAL_METRIC
            ]
            companies = [item for item in local_mentions if item.entity_type == EntityType.COMPANY]
            canonical_counts = Counter(
                RelationExtractAgent._canonical_metric(item.original_text)
                or item.normalized_name
                for item in metrics
            )
            for metric in metrics:
                metric_name = (
                    RelationExtractAgent._canonical_metric(metric.original_text)
                    or metric.normalized_name
                )
                if canonical_counts[metric_name] > 1:
                    continue
                value_pattern = r".{0,24}?([+-]?\d[\d,.]*)"
                unit_pattern = (
                    r"(\s*(?:\u4ebf\u5143|\u4e07\u5143|\u4ebf|\u4e07|%|\u5143|\u80a1|\u624b))?"
                )
                pattern = re.compile(re.escape(metric.original_text) + value_pattern + unit_pattern)
                match = pattern.search(text, metric.char_start or 0)
                if match is None:
                    continue
                raw_unit = (match.group(2) or "").strip() or None
                normalized_number = match.group(1).replace(",", "")
                if (
                    raw_unit is None
                    and normalized_number.isdigit()
                    and 2000 <= int(normalized_number) <= 2100
                ):
                    continue
                if raw_unit == "%" and metric_name not in PERCENT_METRICS:
                    continue
                subject = companies[0] if companies else metric
                results.append(
                    AssertionCandidate(
                        subject_mention_id=subject.mention_id,
                        predicate=RelationType.REPORTS,
                        object_value=match.group(1),
                        object_unit=raw_unit,
                        qualifiers={
                            "metric_name": metric_name,
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

    @classmethod
    def _table_metric_assertions(
        cls,
        document: ParsedDocument,
        mentions: list[EntityMention],
        element_map: dict[str, DocumentElement],
        grouped: dict[str, list[EntityMention]],
    ) -> list[AssertionCandidate]:
        issuer = str(document.metadata.get("issuer") or "").strip()
        issuer_folded = re.sub(r"\s+", "", issuer).casefold()
        issuer_mentions = [
            item
            for item in mentions
            if item.entity_type == EntityType.COMPANY
            and issuer_folded
            and issuer_folded in re.sub(r"\s+", "", item.normalized_name).casefold()
        ]
        issuer_mention = max(issuer_mentions, key=lambda item: item.confidence, default=None)
        element_contexts = cls._table_contexts(document)
        results: list[AssertionCandidate] = []

        for element_id, element in element_map.items():
            if element.element_type != ElementType.TABLE or not element.table_cells:
                continue
            metric_mentions: dict[str, list[EntityMention]] = defaultdict(list)
            for mention in grouped.get(element_id, []):
                if mention.entity_type != EntityType.FINANCIAL_METRIC:
                    continue
                canonical = cls._canonical_metric(mention.original_text)
                if canonical:
                    metric_mentions[canonical].append(mention)
            for queue in metric_mentions.values():
                queue.sort(key=lambda item: item.char_start or -1)

            cells_by_row: dict[int, list[TableCell]] = defaultdict(list)
            for cell in element.table_cells:
                cells_by_row[cell.row_index].append(cell)
            for row_cells in cells_by_row.values():
                row_cells.sort(key=lambda item: item.column_index)

            for row_index in sorted(cells_by_row):
                row_cells = cells_by_row[row_index]
                label_candidates = [
                    (cell, cls._canonical_metric(cell.text))
                    for cell in row_cells
                    if cls._canonical_metric(cell.text)
                ]
                if not label_candidates:
                    continue
                label_cell, metric_name = label_candidates[0]
                if metric_name is None:
                    continue
                queue = metric_mentions.get(metric_name, [])
                metric_mention = queue.pop(0) if queue else None
                if metric_mention is None:
                    continue
                subject = issuer_mention or metric_mention
                candidate_values: list[tuple[TableCell, str, dict[str, str]]] = []
                for value_cell in row_cells:
                    if value_cell.column_index == label_cell.column_index:
                        continue
                    if not cls._is_numeric_cell(value_cell):
                        continue
                    header = cls._column_header(
                        element.table_cells,
                        value_cell,
                    )
                    # Without a recognized period header, adjacent financial
                    # values cannot be assigned to current/prior periods safely.
                    if not header:
                        continue
                    if CHANGE_COLUMN_PATTERN.search(header) and metric_name not in PERCENT_METRICS:
                        continue
                    raw_value = value_cell.text.strip()
                    if metric_name not in PERCENT_METRICS and (
                        raw_value.endswith(("%", "％"))
                        or re.search(r"占.*(?:比例|比重)|(?:比例|比重)\s*[%％]?", header)
                    ):
                        continue
                    candidate_values.append(
                        (value_cell, header, cls._period_details(header))
                    )
                period_counts = Counter(
                    (header.casefold(), tuple(sorted(period_details.items())))
                    for _, header, period_details in candidate_values
                )

                for value_cell, header, period_details in candidate_values:
                    period_key = (header.casefold(), tuple(sorted(period_details.items())))
                    if period_counts[period_key] > 1:
                        # Several amounts under the same period usually encode an
                        # unmodelled category dimension. Do not collapse them into
                        # one canonical metric fact.
                        continue
                    unit, currency, inference = cls._infer_unit(
                        metric_name,
                        label_cell.text,
                        header,
                        element_contexts.get(element_id, ""),
                    )
                    raw_value = value_cell.text.strip()
                    results.append(
                        AssertionCandidate(
                            subject_mention_id=subject.mention_id,
                            predicate=RelationType.REPORTS,
                            object_value=raw_value,
                            object_unit=unit,
                            qualifiers={
                                "metric_name": metric_name,
                                "raw_value": raw_value,
                                "value_kind": "reported",
                                "source_structure": "table_cell",
                                "row_index": value_cell.row_index,
                                "column_index": value_cell.column_index,
                                "header_path": value_cell.header_path,
                                "reported_column": header or None,
                                "period_label": header or None,
                                **period_details,
                                "consolidation_scope": cls._consolidation_scope(
                                    element_contexts.get(element_id, "")
                                ),
                                "currency": currency,
                                "unit_inference": inference,
                                "cell_confidence": value_cell.confidence,
                            },
                            evidence_element_id=element_id,
                            evidence_table_cell=(
                                value_cell.row_index,
                                value_cell.column_index,
                            ),
                            evidence_text=raw_value,
                            extraction_method="schema_rule:FINANCIAL_TABLE_CELL",
                            confidence=min(
                                0.94,
                                subject.confidence,
                                metric_mention.confidence,
                                value_cell.confidence,
                            ),
                        )
                    )
        return results

    @staticmethod
    def _canonical_metric(text: str) -> str | None:
        compact = re.sub(r"\s+", "", text)
        compact = re.sub(r"^(?:其中|加|减)[:：]", "", compact)
        compact = re.sub(r"^(?:[一二三四五六七八九十]+|\d+)[、.]", "", compact)
        for pattern, canonical in FINANCIAL_METRICS:
            if pattern.fullmatch(compact):
                return canonical
        return None

    @staticmethod
    def _is_numeric_cell(cell: TableCell) -> bool:
        if cell.numeric_value is not None:
            return True
        compact = cell.text.replace(",", "").replace(" ", "")
        return bool(re.fullmatch(r"[（(]?[+-]?\d+(?:\.\d+)?[%％]?[）)]?", compact))

    @staticmethod
    def _column_header(cells: list[TableCell], value_cell: TableCell) -> str:
        structured = [
            text.strip()
            for text in value_cell.header_path
            if text.strip() and PERIOD_HEADER_PATTERN.search(text)
        ]
        if structured:
            return " / ".join(structured)
        prior = [
            cell
            for cell in cells
            if cell.column_index == value_cell.column_index
            and cell.row_index < value_cell.row_index
            and cell.text.strip()
            and cell.numeric_value is None
            and PERIOD_HEADER_PATTERN.search(cell.text)
        ]
        if prior:
            return prior[-1].text.strip()
        return ""

    @staticmethod
    def _table_contexts(document: ParsedDocument) -> dict[str, str]:
        by_page: dict[int | None, list[DocumentElement]] = defaultdict(list)
        for element in document.elements:
            by_page[element.page_number].append(element)
        contexts: dict[str, str] = {}
        for page_elements in by_page.values():
            ordered = sorted(page_elements, key=lambda item: item.reading_order)
            for index, element in enumerate(ordered):
                if element.element_type != ElementType.TABLE:
                    continue
                prior: list[str] = []
                for neighbor in reversed(ordered[max(0, index - 6) : index]):
                    if neighbor.element_type == ElementType.TABLE:
                        break
                    if neighbor.text.strip():
                        prior.append(neighbor.text)
                mineru = element.structured_payload.get("mineru_content", {})
                captions = mineru.get("table_caption", []) if isinstance(mineru, dict) else []
                caption_text = " ".join(str(item) for item in captions)
                contexts[element.element_id] = "\n".join(
                    [*reversed(prior), caption_text, element.text]
                )
        return contexts

    @staticmethod
    def _infer_unit(
        metric_name: str,
        label: str,
        header: str,
        page_context: str,
    ) -> tuple[str | None, str | None, str]:
        combined = f"{label} {header}"
        if "元/股" in combined or "元／股" in combined:
            return "元/股", "CNY", "label"
        if metric_name in PERCENT_METRICS or "%" in combined or "％" in combined:
            return "%", None, "label_or_header"
        unit_match = re.search(
            r"(?:单位|金额单位)\s*[：:]?\s*(?:人民币)?\s*(亿元|万元|千元|元)",
            page_context,
        )
        if unit_match:
            return unit_match.group(1), "CNY", "page_context"
        return "元", "CNY", "financial_report_default"

    @staticmethod
    def _period_details(header: str) -> dict[str, str]:
        compact = re.sub(r"\s+", "", header)
        date_match = re.search(
            r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日",
            compact,
        )
        if date_match:
            date_value = (
                f"{int(date_match.group('year')):04d}-"
                f"{int(date_match.group('month')):02d}-"
                f"{int(date_match.group('day')):02d}T00:00:00+00:00"
            )
            return {"period_semantics": "explicit_date", "period_end": date_value}
        year_match = re.search(r"(?P<year>20\d{2})年", compact)
        if year_match:
            year = int(year_match.group("year"))
            month_end_match = re.search(r"(?P<month>\d{1,2})月(?:末|底)", compact)
            if month_end_match:
                month = int(month_end_match.group("month"))
                day = monthrange(year, month)[1]
                return {
                    "period_semantics": "explicit_date",
                    "period_end": (
                        f"{year:04d}-{month:02d}-{day:02d}T00:00:00+00:00"
                    ),
                }
            if re.search(r"年(?:期)?末", compact):
                return {
                    "period_semantics": "explicit_date",
                    "period_end": f"{year:04d}-12-31T00:00:00+00:00",
                }
            if (
                "第一季度" in compact
                or "Q1" in compact.upper()
                or re.search(r"1(?:-|—|至)3月", compact)
            ):
                return {
                    "period_semantics": "explicit_period",
                    "period_start": f"{year:04d}-01-01T00:00:00+00:00",
                    "period_end": f"{year:04d}-03-31T00:00:00+00:00",
                }
            if (
                "半年度" in compact
                or "H1" in compact.upper()
                or re.search(r"1(?:-|—|至)6月", compact)
            ):
                return {
                    "period_semantics": "explicit_period",
                    "period_start": f"{year:04d}-01-01T00:00:00+00:00",
                    "period_end": f"{year:04d}-06-30T00:00:00+00:00",
                }
            if "年度" in compact:
                return {
                    "period_semantics": "explicit_period",
                    "period_start": f"{year:04d}-01-01T00:00:00+00:00",
                    "period_end": f"{year:04d}-12-31T00:00:00+00:00",
                }
        if re.search(r"上年同期|上期同期", compact):
            return {"period_semantics": "prior_year_same_period"}
        if re.search(r"上年末|上年度末|上年期末", compact):
            return {"period_semantics": "prior_year_end"}
        if re.search(r"期初|年初", compact):
            return {"period_semantics": "period_start"}
        if re.search(r"本报告期|本期|期末|本年", compact):
            return {"period_semantics": "current_period"}
        return {"period_semantics": "unspecified"}

    @staticmethod
    def _consolidation_scope(page_context: str) -> str:
        if "合并" in page_context:
            return "consolidated"
        if "母公司" in page_context:
            return "parent_company"
        return "unspecified"

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
