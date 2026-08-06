# 医药行业券商分析师 Agent 平台研究仓库

This repository contains both the phase-one research protocol and the runnable data layer.

## 首要入口

- [第一阶段总计划](docs/research/phase1_literature_research_plan.md)
- [系统映射研究协议](research/protocol.md)
- [标准检索式](research/search/query_catalog.md)
- [种子与锚点文献](research/search/seed_set.csv)
- [证据矩阵](research/evidence/literature_matrix.csv)
- [决策登记](research/decisions/decision_register.md)

## 当前状态

截至 2026-08-06：

- Git 仓库与 `research/phase1-literature` 工作分支已建立；
- RQ1–RQ8、纳入排除规则和质量评价量表已冻结为 v2；
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

## Runnable data layer

The repository now includes a provenance-first, replayable implementation under `src/pharma_data`:

- Five controlled source families: licensed research reports, official clinical records, official financial filings, official news, and authorized earnings calls.
- PDF, HTML, JSON, XLSX, XBRL, image, text, audio, and video routing.
- Evidence-addressable entity, relation, financial-value, conflict, and review records.
- PostgreSQL canonical truth plus outbox-only Neo4j, Milvus, TimescaleDB, and Elasticsearch projections.
- FastAPI REST, GraphQL, `datactl`, Alembic, Docker Compose, dataset snapshots, and benchmark metrics.

Start with [data-layer operations](docs/data_layer/operations.md), [architecture](docs/data_layer/architecture.md), and [governance](docs/data_layer/governance.md).

Quick verification:

```powershell
uv sync --extra dev
uv run alembic upgrade head
uv run pytest -q
uv run datactl eval all
docker compose --profile full config --quiet
```

Heavy PDF/OCR and audio dependencies are locked in `uv.lock` and installed in the production container. Raw reports, recordings, model weights, database volumes, and unlicensed content remain outside Git.
