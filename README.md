# 医药行业券商分析师 Agent 平台

本仓库包含两部分：可运行的数据层工程，以及用于冻结后续 Agent 任务、指标和实验设计的论文调研模块。生产数据范围限定为中国大陆公开或已获授权来源。

## 从哪里开始

- 项目文档总导航：[docs/README.md](docs/README.md)
- 论文调研执行入口：[research/README.md](research/README.md)
- 第一阶段详细计划：[docs/research/phase1_literature_research_plan.md](docs/research/phase1_literature_research_plan.md)
- 数据层文档入口：[docs/data_layer/README.md](docs/data_layer/README.md)
- 数据层可视化：[docs/data_layer/visualization.md](docs/data_layer/visualization.md)
- 团队协作规范：[CONTRIBUTING.md](CONTRIBUTING.md)

远程仓库：[xhcscb/Pharma-R-D-Agent](https://github.com/xhcscb/Pharma-R-D-Agent)。长期分支为 `main`、`develop` 和 `research/phase1-literature`；短期功能分支合并后删除。

## 当前真实状态

截至 2026-08-09：

| 模块 | 已完成 | 尚未完成 |
|---|---|---|
| 论文调研 | RQ1—RQ8、协议、检索模板、18 篇种子元数据、15 篇锚点队列、证据与评测模板 | 正式检索、种子召回测试、50 篇筛选校准、双人全文筛选、40 篇深读和 D01—D10 冻结 |
| 数据层 | 五类接入、文档解析、实体/关系抽取、清洗、复核、统一事实库、四类投影接口、REST、GraphQL、CLI 和可视化 | 真实 Gold 语料质量门、生产级模型调优、四类外部数据库的正式在线验收 |

当前 Python 包版本为 `0.2.0`。`data-layer-v1.0.0` 和 `research-phase1-v1.0` 均未达到创建条件；通过脚手架测试或演示数据不等于完成正式验收。

## 数据层最短演示

本机使用 SQLite，不需要把数据库地址写成 `postgres`：

~~~powershell
Copy-Item .env.example .env
uv sync --extra dev
uv run datactl db migrate
uv run datactl source demo
uv run uvicorn pharma_data.api.app:app --host 127.0.0.1 --port 8000
~~~

打开 `http://127.0.0.1:8000/demo/data-layer`，选择“团队内部”，并填写 `.env` 中的 `INTERNAL_API_KEY`。页面可查看解析元素、实体高亮、候选关系图、证据位置和复核状态。

Docker 核心服务：

~~~powershell
Copy-Item .env.example .env
docker compose --profile core up -d --build
docker compose --profile core exec api alembic upgrade head
Invoke-RestMethod http://127.0.0.1:8000/health
~~~

本机 CLI 使用 SQLite 或 `localhost`；`postgres`、`neo4j` 等名称只在 Compose 网络内部可解析。完整说明见[快速启动](docs/data_layer/quickstart.md)。

## 论文调研最短流程

1. 阅读[研究模块入口](research/README.md)和[执行协议](research/protocol.md)。
2. 按[检索式目录](research/search/query_catalog.md)执行试检索，将实际查询写入 `search_log.csv`。
3. 种子组合召回率达到 100% 后，完成 50 篇校准并计算 Cohen's κ。
4. 通过质量门后，才能开展正式检索、筛选、深读、综合和决策冻结。

论文元数据已登记不代表全文主张已核验。只有状态达到 `full_text_verified` 的卡片才能支撑确定性研究结论。

## 验证

~~~powershell
python scripts/validate_docs.py
./scripts/validate_phase1.ps1
uv run pytest -q
uv run ruff check .
uv run mypy scripts/validate_docs.py
docker compose --profile full config --quiet
~~~

`validate_phase1.ps1` 验证研究文件和数据接口，不证明 100 篇矩阵、40 篇深读等阶段数量门已经达成。全量 `mypy src` 仍有可选依赖类型存根和旧标注问题，当前只要求对本次改动模块做定向检查，详见[已知限制](docs/data_layer/known_limitations.md)。

## 数据与版权边界

- 生产数据只使用中国大陆权威公开来源或已获明确授权的来源；
- 不提交未授权券商研报、付费论文、私人录音、Cookie、Token、模型权重或数据库卷；
- `public_access` 只表示公众可访问，不等于允许公开再分发全文；
- Git 只保存来源元数据、链接、检索日志、团队原创标注、配置和可授权内容；
- PostgreSQL 是唯一事实主库，Neo4j、Milvus、TimescaleDB 和 Elasticsearch 只能由 Outbox 投影重建。

发布门详见[数据层验收说明](docs/data_layer/acceptance.md)和[第一阶段最终验收](docs/research/phase1_literature_research_plan.md#12-最终验收)。
