# 论文调研模块

本目录用于执行第一阶段“系统映射研究 + 核心论文深读”。目标不是堆积论文链接，而是把可核验的论文证据转化为任务定义、评价指标、数据要求、基线、消融和架构决策。

## 1. 当前状态

截至 2026-08-09：

| 项目 | 当前数量 | 状态 |
|---|---:|---|
| 种子论文 | 18 | 元数据已建档，召回测试未执行 |
| 锚点论文 | 15 | 已分配主读/复核队列，全文深读未完成 |
| 检索式批次 | 8 | 均为 `not_run` |
| 证据矩阵 | 18 | 仅元数据级，不是正式证据综合结果 |
| 筛选决定 | 0 | 尚未开始 |
| 质量评价 | 0 | 尚未开始 |
| 已核验深读卡片 | 0 | 尚未开始 |
| D01—D10 | 10 | 均未冻结 |

数据层已经并行实现，但不能倒推文献结论已经成立。当前工程机制只作为待验证对象，见[实施—证据映射](synthesis/implementation_evidence_map.md)。

## 2. 必读顺序

1. [第一阶段详细计划](../docs/research/phase1_literature_research_plan.md)：理解目标、产物和质量门；
2. [执行协议](protocol.md)：按固定规则进行检索、筛选和复核；
3. [执行看板](workboard.md)：领取任务并更新状态；
4. [检索式目录](search/query_catalog.md)：改写并执行数据库查询；
5. [深读卡片模板](evidence/cards/_template.md)：完成全文证据提取；
6. [决策登记](decisions/decision_register.md)：将综合结论转化为 D01—D10。

## 3. 目录与唯一事实来源

| 路径 | 保存内容 | 何时更新 |
|---|---|---|
| `search/seed_set.csv` | 种子、锚点、命中来源和复核分工 | 试检索或锚点调整时 |
| `search/search_log.csv` | 每次实际查询、日期、命中数和导出哈希 | 每执行一次查询立即新增 |
| `screening/screening_decisions.csv` | 标题摘要、全文、分歧和裁决 | 每完成一条筛选决定 |
| `screening/calibration_log.csv` | 50 篇校准和 Cohen's κ | 每轮校准后 |
| `screening/prisma_flow.csv` | PRISMA 流程数量 | 每个筛选阶段结束后 |
| `screening/quality_appraisal.csv` | 七项双人质量评分 | 全文纳入后 |
| `evidence/literature_matrix.csv` | 跨论文证据矩阵 | 提取并复核全文时 |
| `evidence/cards/` | 40 篇核心论文深读卡片 | 主读与复核时 |
| `evidence/metric_candidates.csv` | 指标定义、公式、Gold 和聚合 | 发现或修正指标时 |
| `evidence/baseline_candidates.csv` | 各组件最低基线、强基线和配置 | 综合方法与设计消融时 |
| `evidence/error_taxonomy.csv` | 解析、抽取、证据、冲突和Agent错误 | 深读、Gold标注和误差分析时 |
| `synthesis/` | 七主题综合、研究空白和实施映射 | 第五周证据综合时 |
| `decisions/decision_register.md` | D01—D10 状态和证据 | 评审决策时 |
| `protocol_deviations.csv` | 协议冻结后的变更 | 先登记，再修改规则 |

原始数据库导出和论文全文不进入 Git；仓库只保留日志、哈希、合法短摘录和团队原创内容。

## 4. 一篇论文怎样进入结论

~~~text
发现 → 去重 → 标题/摘要筛选 → 全文双审 → 双人质量评价
→ 证据矩阵 → 深读卡片 → 第二人核验 → 主题综合 → 决策登记
~~~

必须同时满足以下条件，论文才能支撑确定性综合结论：

- 来源和版本可确认；
- 全文纳入决定已完成双审；
- 数据、方法、指标、结果和局限已提取；
- 关键数字能定位到页码、表格、图或章节；
- 深读卡片状态为 `full_text_verified`；
- 质量等级允许用于对应结论。

只有元数据、摘要或 LLM 草稿时，状态必须保持 `metadata_verified` 或 `draft`。

## 5. 每次工作的标准动作

开始前：

1. 在 `workboard.md` 找到任务 ID 和负责人；
2. 阅读协议对应章节；
3. 确认输入文件没有被他人占用；
4. 检查论文访问权限和版本。

完成后：

1. 更新对应 CSV 或卡片；
2. 填写执行人、日期、状态和原文定位；
3. 运行校验；
4. 由复核者检查后提交 Git。

~~~powershell
python scripts/validate_docs.py
./scripts/validate_phase1.ps1
~~~

## 6. 当前最近任务

必须按顺序完成：

1. 将七个主题的抽象检索式改写为各数据库实际语法；
2. 执行 8 组试检索并填写 `search_log.csv`；
3. 为 18 篇种子填写实际命中来源，证明组合召回率为 100%；
4. 抽取 50 篇校准样本；
5. 五人独立筛选并计算两两 Cohen's κ；
6. 质量门通过后才进入正式检索。

禁止根据当前 18 条元数据直接撰写“文献证明了……”之类的确定性结论。

## 7. 完成判定

阶段完成必须同时达到：证据矩阵不少于 100 篇、深读不少于 40 篇、15 篇锚点全部双审、种子召回率 100%、筛选校准达标、指标/基线/错误分类可操作、D01—D10 均有明确状态，并且数据层验收与 Agent 实验要求可以直接执行。

详细阈值见[第一阶段最终验收](../docs/research/phase1_literature_research_plan.md#12-最终验收)。
