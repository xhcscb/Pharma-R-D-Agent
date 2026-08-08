# 数据层文档导航

本目录记录数据层的架构、操作、治理、接口和验收规则。所有正文使用简体中文；英文只保留在代码标识、数据库名称、协议字段和业界通用缩写中。

## 按角色阅读

数据管理员：

1. [快速启动](quickstart.md)
2. [权威数据源配置](authoritative_sources.md)
3. [权威数据源演示](authoritative_source_demo.md)
4. [数据层操作手册](operations.md)
5. [数据清单编写指南](manifest_guide.md)
6. [运维与恢复手册](maintenance_and_recovery.md)

复核与标注人员：

1. [数据治理](governance.md)
2. [统一数据模型](data_model.md)
3. [Gold 基准格式与质量门](benchmark.md)
4. [数据层验收说明](acceptance.md)

开发与集成人员：

1. [数据层架构](architecture.md)
2. [数据层查询接口](api.md)
3. [受控数据源目录](source_catalog.md)
4. [数据层操作手册](operations.md)

## 文档用途

| 文档 | 主要内容 |
|---|---|
| [quickstart.md](quickstart.md) | 从空环境到完成首批导入的最短路径 |
| [authoritative_sources.md](authoritative_sources.md) | 官方 API、许可边界、配置、诊断和同步命令 |
| [authoritative_source_demo.md](authoritative_source_demo.md) | 四个真实小样本的一键调试和结果判读 |
| [operations.md](operations.md) | 启动、五类导入、处理、复核、投影、查询和验收 |
| [manifest_guide.md](manifest_guide.md) | CSV/JSON/JSONL 字段、许可、路径与五类示例 |
| [maintenance_and_recovery.md](maintenance_and_recovery.md) | 监控、备份、恢复、任务故障和投影重建 |
| [architecture.md](architecture.md) | 数据流、状态机、解析器和四类投影 |
| [data_model.md](data_model.md) | 稳定 ID、主张、证据、冲突和质量分层 |
| [governance.md](governance.md) | 来源分级、许可、权限、复核和审计原则 |
| [source_catalog.md](source_catalog.md) | 权威来源、适配器、格式和默认策略 |
| [api.md](api.md) | REST、GraphQL 和鉴权规则 |
| [benchmark.md](benchmark.md) | Gold 文件结构、指标和发布阈值 |
| [acceptance.md](acceptance.md) | 自动化覆盖、真实语料验收和版本标签条件 |

## 安全提醒

- 未授权研报、私人录音、数据库卷、模型权重和 `.env` 不得提交到 Git。
- 公开数据快照只能包含 `public` 文档版本。
- PostgreSQL 是唯一事实主库，Neo4j、Milvus、TimescaleDB 和 Elasticsearch 均可由主库重建。
- 删除数据库卷、覆盖恢复和公开发布属于高风险操作，必须先备份并由负责人确认。
