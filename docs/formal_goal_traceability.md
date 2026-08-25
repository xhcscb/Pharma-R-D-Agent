# 正式研究目标符合性与验收矩阵

## 1. 控制基线

本矩阵以立项申报书和《面向医药投研的多智能体结构化推理系统研究》中的正式研究目标为控制基线。仓库早期《医药行业券商分析师 Agent 平台设计方案》中的五层架构、QA、Risk、Canvas 等内容属于后续扩展，不得替代正式目标，也不得用扩展模块的完成度掩盖核心机制缺口。

正式框架为四层：数据接入层、公共机制层、智能体层、应用输出层。研究阶段的 D01—D10 决策冻结和 Gold 实验是机制定型的前置条件。

## 2. 目标到实现的逐项映射

| 正式目标 | 仓库实现证据 | 自动检查 | 当前判定 |
|---|---|---|---|
| 中国大陆权威或已授权多源数据接入 | `config/authoritative_sources.json`、文件投递箱/自动 metadata/哈希归档、各 Manifest 适配器、统一事实库与证据定位 | 来源目录、投递去重、侧车核验、权限、解析、治理测试 | 三份财报机械批次已通过；官方 URL 与其他类别真实授权覆盖待完成 |
| Metric Ontology | `config/metric_ontology.json`、`reasoning/metric_ontology.py` | 本体唯一性、别名解析、数值/阶段规范化测试 | 最小可运行基线已实现；D02/D04/D06/D07 待冻结 |
| Claim Graph | `reasoning/claim_graph.py` | 权限过滤、来源权威等级与证据保留测试 | 最小可运行基线已实现；图关系学习方法待实验 |
| Evidence Gate | `reasoning/evidence_gate.py` | `pass/revise/flag_conflict/abstain` 四动作测试 | 规则基线已实现；D05/D10 待冻结 |
| Compare Agent | `reasoning/compare.py`、`POST /v1/reasoning/compare`、`datactl reasoning compare` | DSL、覆盖率、缺失与冲突测试 | 结构化基线已实现；学习型方法待研究证据与实验 |
| Summarize Agent | `reasoning/summarize.py`、`POST /v1/reasoning/summarize`、`datactl reasoning summarize` | 共识/冲突/待复核三层同源测试 | 结构化基线已实现；重要性学习待实验 |
| 可追溯输出 | 每个结果返回 claim ID、evidence ID、门控动作和警告；`POST /v1/reasoning/context` 提供批量交接契约 | 推理单元测试、REST 鉴权测试 | 已实现基线 |
| 图、向量、时序、全文投影 | Neo4j、Milvus、TimescaleDB、Elasticsearch 投影器 | Compose 配置与投影单元测试 | 接口已实现；四服务在线验收未完成 |
| 医药投研案例与效果评价 | `research/` 协议、证据矩阵、基准与数据快照接口 | `validate_phase1`、Gold benchmark | 未完成；不得宣称正式达标 |

“最小可运行基线”表示代码路径和契约存在且可测试，不表示论文中提出的方法优于基线，也不表示阶段研究任务已经验收。

## 3. 强制门禁

正式目标只有在下列门禁全部通过后才算完成：

| 门禁 | 通过条件 | 当前状态 |
|---|---|---|
| G0 工程门 | 全量测试、Ruff、文档、Compose 配置通过 | 已通过：2026-08-24，60 项测试；Ruff、文档、阶段校验和 Compose 配置通过 |
| G1 来源与许可门 | 每类关键数据至少一个真实来源；授权号/合同/公开依据可审计 | 未通过 |
| G2 机械端到端门 | 真实批次从导入到候选主张、证据和复核队列完整跑通 | 三份 2026 年财报真实批次已通过；其他关键数据类别仍待批次覆盖 |
| G3 Gold 质量门 | 非空 Gold 达到 `benchmark.md` 阈值并完成双人复核 | 未通过 |
| G4 基础设施门 | PostgreSQL、Neo4j、Milvus、TimescaleDB、Elasticsearch 在线重建并核对数量 | Compose 配置通过；Docker daemon 未运行，在线验收未通过 |
| G5 研究冻结门 | D02、D04、D05、D06、D07、D10 达到 `frozen` 或 `experiment_required`，检索与证据卡达标 | 未通过 |
| G6 正式案例门 | 完成 3—5 个医药投研案例、消融/基线对比、误差分析和签字报告 | 未通过 |

任一门禁未通过时，项目只能标记为“工程基线/内部试运行”，不能创建 `data-layer-v1.0.0` 或写成“完全达成正式研究目标”。

## 4. 与研究进度的对应关系

截至 2026-08-22，研究模块仍有以下硬缺口：正式检索、50 篇筛选校准、40 篇深读、非空证据卡、15 篇锚点全文核验和 D01—D10 冻结尚未完成。第二阶段智能体实验必须遵守 `research/phase2/phase2_data_requirements.md` 的交接门，不得用本次新增的规则基线跳过研究冻结。

下一次复核时应更新本矩阵的“当前状态”，并把验收报告、数据快照哈希和负责人签字链接到对应门禁。
