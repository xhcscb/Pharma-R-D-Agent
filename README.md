# 医药行业券商分析师 Agent 平台研究仓库

本仓库同时包含第一阶段研究协议和可运行的数据层工程。

## 首要入口

研究工作：

- [第一阶段总计划](docs/research/phase1_literature_research_plan.md)
- [系统映射研究协议](research/protocol.md)
- [标准检索式](research/search/query_catalog.md)
- [种子与锚点文献](research/search/seed_set.csv)
- [证据矩阵](research/evidence/literature_matrix.csv)
- [决策登记](research/decisions/decision_register.md)

数据层：

- [数据层文档导航](docs/data_layer/README.md)
- [权威数据源配置](docs/data_layer/authoritative_sources.md)
- [权威数据源演示](docs/data_layer/authoritative_source_demo.md)
- [快速启动](docs/data_layer/quickstart.md)
- [完整操作手册](docs/data_layer/operations.md)
- [数据清单编写指南](docs/data_layer/manifest_guide.md)
- [运维与恢复手册](docs/data_layer/maintenance_and_recovery.md)

## 当前状态

截至 2026-08-08：

- RQ1–RQ8、纳入排除规则和质量评价量表已冻结；
- 已建立首批种子论文元数据和阶段数据模板；
- 数据层已实现五类受控数据接入、文档解析、实体抽取、关系抽取、清洗、复核和统一事实库；
- 已提供 Neo4j、Milvus、TimescaleDB、Elasticsearch 投影，以及 REST、GraphQL、CLI、Alembic 和 Docker Compose；
- 正式数据库检索、双人筛选、全文深读和 Gold 语料实测仍需由团队按计划执行；
- 机器生成的论文摘要、实验数字、实体、关系和评价结论必须由成员对照原文复核。

## 数据管理原则

- 不提交未授权券商研报、付费论文、私人录音或其他受版权保护全文；
- Git 只保存公开元数据、链接、检索协议、派生标注、论文卡片、配置和团队原创综合；
- 论文统一使用 `LIT-YYYY-NNN` 编号；
- 缺失值保持为空，不用未经核验的推测值填充；
- CSV 使用 UTF-8 编码，多个标签用英文分号 `;` 分隔；
- PostgreSQL 是唯一事实主库，其他知识存储均通过 Outbox 投影。

## 数据层能力

`src/pharma_data` 提供：

- 五类来源：授权研报、官方临床记录、官方财务报告、官方新闻和授权电话会议；
- 文件路由：PDF、HTML、JSON、XLSX、XBRL、图片、文本、音频和视频；
- 证据可定位的实体、关系、财务数值、冲突和复核记录；
- PostgreSQL 统一事实库，以及只读主库事件的四类投影；
- FastAPI REST、GraphQL、`datactl`、Alembic、Docker Compose、数据集快照和基准评测。

快速启动：

~~~powershell
Copy-Item .env.example .env
docker compose --profile core up -d --build
docker compose --profile core exec api alembic upgrade head
Invoke-RestMethod http://127.0.0.1:8000/health
~~~

本地开发验证：

~~~powershell
uv sync --extra dev
uv run alembic upgrade head
uv run pytest -q
uv run datactl eval all
docker compose --profile full config --quiet
~~~

重型 PDF/OCR、音频和机器学习依赖已锁定在 `uv.lock`，并由生产镜像安装。原始研报、录音、模型权重、数据库卷和未授权内容均保留在 Git 之外。

## 研究协议验证

在 PowerShell 中运行：

~~~powershell
./scripts/validate_phase1.ps1
~~~

验证脚本检查必需文件、CSV 表头、文献编号、种子与锚点数量、枚举值和受版权文件误提交风险。

## 发布说明

`data-layer-v1.0.0` 标签只能在自动化检查和真实 Gold 语料验收均通过后创建，不能以空基准或仅通过脚手架测试代替。详见[数据层验收说明](docs/data_layer/acceptance.md)。
