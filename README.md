# 医药行业券商分析师 Agent 平台研究仓库

本仓库当前只实施第一阶段：文献调研与研究设计冻结。当前阶段不包含爬虫、PDF 解析器、数据库或 Agent 运行代码。

## 首要入口

- [第一阶段总计划](docs/research/phase1_literature_research_plan.md)
- [系统映射研究协议](research/protocol.md)
- [标准检索式](research/search/query_catalog.md)
- [种子与锚点文献](research/search/seed_set.csv)
- [证据矩阵](research/evidence/literature_matrix.csv)
- [决策登记](research/decisions/decision_register.md)

## 当前状态

截至 2026-08-05：

- Git 仓库与 `research/phase1-literature` 工作分支已建立；
- RQ1–RQ8、纳入排除规则和质量评价量表已冻结为 v1；
- 已建立首批种子论文元数据及所有阶段数据模板；
- 正式数据库检索、双人筛选和全文深读仍应按照六周计划由团队执行；
- 任何机器生成的论文摘要、实验数字和评价结论都必须由成员对照原文复核。

## 数据管理原则

- 不提交未授权券商研报、付费论文或其他受版权保护全文；
- Git 中只保存公开元数据、链接、检索协议、派生标注、论文卡片和团队原创综合；
- 论文统一使用 `LIT-YYYY-NNN` 编号；
- 缺失值保持为空，不使用未经核验的推测值填充；
- CSV 使用 UTF-8 编码，多个标签用英文分号 `;` 分隔。

## 验证

在 PowerShell 中运行：

```powershell
./scripts/validate_phase1.ps1
```

验证脚本检查必需文件、CSV 表头、文献编号、种子/锚点数量、枚举值和受版权文件误提交风险。
