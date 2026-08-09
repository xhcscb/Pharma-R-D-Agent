# 数据层研究验收与 Agent 交接要求（第一阶段待冻结）

数据层工程已提前实现，本文件不再描述“从零建设数据层”，而是规定第一阶段研究结束后必须补齐的证据化验收、数据集冻结和 Agent 输入接口。当前内容均为工作假设，最终由 D02、D04—D07 和 D10 决定。

## 1. 数据范围

生产和 Gold 数据只选择中国大陆公开或已获授权来源：

- 券商研报：中国大陆持牌证券公司研究所或合法授权提供方；
- 临床：药物临床试验登记与信息公示平台、ChiCTR、CDE、NMPA；
- 财务：巨潮资讯、上交所、深交所、北交所、全国股转系统和公司 IR；
- 新闻与监管：国务院部门、NMPA、CDE、国家医保局、国家卫健委、证监会、交易所和公司法定披露；
- 电话会议：交易所投资者关系记录、公司官方文字稿或授权音视频。

国际论文和基准可以用于方法比较，但境外业务数据不进入本阶段生产库或 Gold 集。

## 2. Gold 语料设计

工作量假设：

- 30份精标PDF；
- 150—300份压力测试文档；
- 至少覆盖研报、临床、财报、官方新闻和投资者关系记录五类来源；
- 覆盖原生文本、扫描件、双栏、跨页表格、复杂图表、脚注、混合中英文和低质量页面。

每份文档必须记录：来源、官方URL、许可、访问等级、SHA-256、发布日期、获取日期、语言、页数、难度、标注者、复核者和版本。

抽样必须按“来源类型 × 版面难度 × 业务任务”分层，不能只选择解析容易的PDF。具体数量由 D06 冻结。

## 3. 解析与抽取标注

### 文档解析

- 文本：字符、阅读顺序、标题层级、段落边界；
- 表格：行列、合并单元格、多级表头、单位、跨页连接和脚注；
- 图表：类型、标题、坐标轴、图例、序列、数值、单位和图注；
- 证据：页码、bbox、元素ID、字符区间或音频时间段。

### 实体与关系

- 实体：Company、Drug、Target、Indication、ClinicalTrial、PipelineProgram、ClinicalStage、RegulatoryAgency、Person、FinancialMetric、Event、Market、Region；
- 链接：规范实体ID、别名、来源ID、链接状态和歧义原因；
- 关系：主体、谓词、客体、限定条件、有效时间、主张模式和证据；
- 冲突：冲突类型、涉及主张、来源、解决状态和人工判定。

实体边界、关系方向、跨句关系、表格关系和“不足以判断”的标注规则必须写入独立指南，并用双人标注一致性验证。

## 4. 数据契约

每个证据单元至少需要：

~~~text
document_id
document_version_id
source_record_id
source_name
license_status
access_class
published_at
retrieved_at
page_number
element_id
element_type
bbox
reading_order
char_span
text
structured_payload
parser_name
parser_version
confidence
content_hash
~~~

Agent 使用的每条主张至少需要：

~~~text
assertion_id
subject_id
predicate
object_entity_id_or_value
unit
qualifiers
valid_from
valid_to
as_of_date
assertion_mode
review_status
evidence_id
source_authority
access_class
~~~

## 5. 基线和消融

至少比较：

- PDF：PyMuPDF 原生文本、OCR 基线、版面模型和混合选择器；
- 实体：词典、规则、NER 模型和融合方案；
- 实体链接：精确匹配、别名匹配、文本相似度和上下文联合链接；
- 关系：规则、句内模型、跨句/表格模型和人工复核门；
- 检索：纯向量、向量+元数据、扁平图和分层图；
- Evidence Gate：无门控、生成后检查和生成前/中门控。

所有模型基线必须记录版本、配置、随机种子、运行次数、硬件、时延和成本。

## 6. 质量门

最终阈值由 D02 和 D07 根据文献与小规模标注试验冻结。当前工程验收候选值见[Gold 基准格式与质量门](../../docs/data_layer/benchmark.md)，不能在没有真实 Gold 报告时宣称达标。

除准确率外必须报告：

- 按数据来源、版面难度和实体类型分层的结果；
- 95%置信区间或重复运行波动；
- 失败类型和高风险错误；
- 人工复核工作量；
- 各处理阶段的时延、成本和失败恢复率；
- 主库到投影的ID与权限一致性。

## 7. Agent 交接门

数据层进入 Compare/Summarize Agent 实验前，必须满足：

- D02、D04、D05、D06、D07、D10 为 `frozen` 或 `experiment_required`；
- Gold 文档来源、许可和访问等级全部明确；
- 数据层能按时间、口径、来源和证据位置返回主张；
- Candidate、Conflict 和 Approved 可以被 Agent 明确区分；
- 每条 Agent 可用事实均能回到原始证据；
- 解析、实体、关系和冲突的基线与误差分类完整；
- 第一阶段验证脚本通过，阶段标签已创建。

已有演示数据库只能用于联调，不满足上述交接门。
