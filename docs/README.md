# 项目文档导航

本目录按“研究设计”和“数据层工程”两条线组织。第一次接触项目时，先阅读仓库根目录的[总览](../README.md)。

## 论文调研

- [论文调研模块入口](../research/README.md)：当前状态、目录、日常流程和完成判定；
- [第一阶段详细计划](research/phase1_literature_research_plan.md)：目标、十二步流程、六周质量门和团队分工；
- [系统映射研究协议](../research/protocol.md)：检索、去重、筛选、质量评价和决策冻结规则；
- [执行看板](../research/workboard.md)：各任务的负责人、产物和状态。

## 数据层

- [数据层文档导航](data_layer/README.md)：按角色选择阅读路径；
- [快速启动](data_layer/quickstart.md)：最短运行步骤；
- [完整操作手册](data_layer/operations.md)：导入、处理、复核、投影和验收；
- [中国大陆权威来源](data_layer/authoritative_sources.md)：来源等级、许可、配置和同步方式；
- [文件投递箱](data_layer/inbox.md)：自动 metadata、哈希归档、来源侧车和推理层交接；
- [三份真实财报验收](data_layer/inbox_acceptance_20260823.md)：实际运行数量和未通过门禁；
- [可视化说明](data_layer/visualization.md)：解析元素、实体高亮、关系图和证据链演示；
- [验收说明](data_layer/acceptance.md)：自动测试与 Gold 语料质量门。
- [已知限制](data_layer/known_limitations.md)：当前 Gold、可选依赖、投影和类型检查边界。

## 正式目标复核

- [正式研究目标符合性与验收矩阵](formal_goal_traceability.md)：正式四层框架、代码证据、研究门禁与当前差距；
- [正式数据接入与生产启用步骤](data_layer/production_activation.md)：临床、财务、行情和研报授权后的落地流程。

## 文档状态

文档中的状态词含义如下：

| 状态 | 含义 |
|---|---|
| 已实现 | 代码和接口已存在，并通过相应自动化检查 |
| 演示可用 | 可用受控样本运行，但不代表真实 Gold 质量达标 |
| 待复核 | 已有自动结果或论文元数据，尚未人工核验 |
| 待冻结 | 已有候选方案，研究证据或实验尚不足以作最终决定 |
| 已验收 | 数量门、质量门、权限和人工签字全部满足 |

不要把“已实现”或“演示可用”解释为“已验收”。
