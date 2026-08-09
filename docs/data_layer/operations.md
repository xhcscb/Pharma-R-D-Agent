# 数据层操作手册

本文面向数据管理员、标注复核人员和开发人员，覆盖从环境准备、五类数据导入到复核、投影、验收和停止服务的完整操作。第一次部署建议先阅读[快速启动](quickstart.md)，字段不清楚时查阅[数据清单编写指南](manifest_guide.md)。

## 1. 操作边界

开始前必须确认：

- 数据来自官方公开渠道，或团队已获得明确授权；
- `license_status` 和 `access_class` 已填写且相互一致；
- 受版权保护的研报、录音和原始数据库文件不进入 Git；
- `metadata_only`、`prohibited`、`unknown` 记录只保留元数据，不下载正文；
- 生产环境已替换默认密码和 `INTERNAL_API_KEY`；
- 操作人员知道本次导入的负责人、用途和预期数量。

严禁绕过登录、付费墙、验证码或访问控制，也不得导入来源不明的私人电话录音。

## 2. 环境准备

### 2.1 推荐环境

- Windows 10/11 或 Linux；
- Docker Desktop / Docker Engine，建议至少 16 GB 内存；
- Git；
- 本地开发可选 Python 3.12 与 uv。

在仓库根目录执行：

~~~powershell
Copy-Item .env.example .env
~~~

至少修改：

- `INTERNAL_API_KEY`：长随机值；
- `PROJECT_CONTACT_EMAIL`：团队来源管理联系人，可选但建议填写；
- `HF_TOKEN`：仅在所选模型确实需要时填写。

仓库中的数据库口令只适合本地开发。部署到共享环境前，必须同时修改 `compose.yaml` 中的服务端口令和 `.env` 中的连接 URL 或客户端口令，确保两侧一致。例如修改 `NEO4J_PASSWORD` 时，也要同步修改 `NEO4J_AUTH`。

不要提交 `.env`。

### 2.2 本机地址与容器地址

同一服务在两种运行环境中使用不同地址：

| 服务 | Windows 本机 | Compose 容器内部 |
|---|---|---|
| 事实库 | `sqlite:///./data/runtime/pharma.db`，或 `localhost:5432` | `postgres:5432` |
| Neo4j | `localhost:7687` | `neo4j:7687` |
| Milvus | `localhost:19530` | `milvus:19530` |
| TimescaleDB | `localhost:5433` | `timescaledb:5432` |
| Elasticsearch | `localhost:9200` | `elasticsearch:9200` |

`.env` 中的普通变量供本机 CLI 使用；`CONTAINER_*` 变量由 Compose 注入容器。不要让本机 CLI 使用 `postgres`、`neo4j` 等 Compose 服务名。

诊断本机数据库配置：

~~~powershell
.venv\Scripts\datactl.exe db doctor
~~~

检查已登记来源和联网状态：

~~~powershell
.venv\Scripts\datactl.exe source list
.venv\Scripts\datactl.exe source doctor
.venv\Scripts\datactl.exe source doctor --live --source-id cninfo_disclosures
~~~

来源依据、API 限制和配置项见[权威数据源配置与接入说明](authoritative_sources.md)。

### 2.3 服务组合

| Profile | 服务 | 用途 |
|---|---|---|
| `core` | API、Worker、PostgreSQL | 日常导入、处理和复核 |
| `graph` | Neo4j | 实体关系图 |
| `vector` | Milvus、etcd、MinIO | 向量检索 |
| `timeseries` | TimescaleDB | 时序事实 |
| `search` | Elasticsearch | 全文检索 |
| `full` | 全部服务 | 完整联调与发布验收 |

笔记本首次运行建议先启 `core`，确认正常后再启 `full`。

## 3. 启动与初始化

启动核心服务：

~~~powershell
docker compose --profile core up -d --build
docker compose --profile core exec api alembic upgrade head
docker compose --profile core ps
~~~

启动完整环境：

~~~powershell
docker compose --profile full up -d --build
docker compose --profile full exec api alembic upgrade head
docker compose --profile full ps
~~~

检查 API：

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/health
~~~

常用入口：

- REST 文档：`http://127.0.0.1:8000/docs`；
- GraphQL：`http://127.0.0.1:8000/graphql`；
- Neo4j：`http://127.0.0.1:7474`；
- Elasticsearch：`http://127.0.0.1:9200`。

如果 Docker 服务未就绪，先运行 `docker compose --profile full ps` 和 `docker compose --profile full logs --tail 200 SERVICE_NAME`。

## 4. 导入五类数据

清单可以是 CSV、JSON 或 JSONL。相对 `local_path` 按清单文件所在目录解析。正式导入前先人工抽查 URL、许可、访问等级和文件哈希。

### 4.1 券商研报

只导入公开或已授权 PDF：

~~~powershell
docker compose --profile core exec api datactl ingest manifest manifests/examples/research_reports.csv --source-type research_reports
~~~

默认应使用 `authorized_restricted` 和 `team_internal`。示例路径只是格式模板；运行前须替换为团队实际获授权文件。

### 4.2 临床数据

从药物临床试验登记平台或 ChiCTR 人工查询并导出，保留 CTR/ChiCTR 登记号、详情页、查询日期和导出文件。按清单导入：

~~~powershell
docker compose --profile core exec api datactl ingest manifest PATH_TO_MANIFEST --source-type china_drug_trials
docker compose --profile core exec api datactl ingest manifest PATH_TO_MANIFEST --source-type cde
docker compose --profile core exec api datactl ingest manifest PATH_TO_MANIFEST --source-type clinical_documents
~~~

可用国家药监局政务服务官方页面验证临床监管文档解析：

~~~powershell
.venv\Scripts\datactl.exe source sync nmpa_government_service --run-pipeline
~~~

药物临床试验平台、CDE 和 ChiCTR 没有被官方承诺稳定的批量 API，且存在访问保护。不得调用未公开内部接口或绕过校验。

### 4.3 财务报告

先用真实大陆官方财报样本验证：

~~~powershell
.venv\Scripts\datactl.exe source sync cninfo_disclosures --run-pipeline
~~~

正式数据从巨潮资讯、上交所、深交所、北交所或全国股转系统导出后使用官方清单：

~~~powershell
docker compose --profile core exec api datactl ingest manifest manifests/examples/financial_reports.csv --source-type financial_reports
~~~

优先选择交易所、巨潮资讯或公司 IR 的 XBRL/XML、XLSX；PDF 作为证据或降级来源。报告期、发布日期、币种、单位、合并范围、审计和重述状态必须分开保存。

### 4.4 新闻

国家医保局真实政策样本：

~~~powershell
.venv\Scripts\datactl.exe source sync nhsa_drug_catalog --run-pipeline
~~~

其他新闻只使用中国政府网、国家药监局、CDE、国家医保局、国家卫健委、证监会、交易所、工信部、市场监管总局或上市公司第一方页面：

~~~powershell
docker compose --profile core exec api datactl ingest manifest manifests/examples/news.csv --source-type news
~~~

Gold 新闻优先使用监管机构、交易所或公司法定公告。普通媒体只能作为线索，不能替代关键主张的官方证据。

### 4.5 电话会议

~~~powershell
docker compose --profile core exec api datactl ingest manifest manifests/examples/earnings_calls.csv --source-type earnings_calls
~~~

可导入官方文字稿、投资者关系活动记录、演示材料和已授权 MP3/WAV/MP4。说话人身份必须来自官方参与名单、主持人介绍或人工确认。

真实大陆投资者关系样本：

~~~powershell
.venv\Scripts\datactl.exe source sync cninfo_investor_relations --run-pipeline
~~~

### 4.6 一键真实来源演示

~~~powershell
.venv\Scripts\datactl.exe source demo
~~~

该命令用隔离 SQLite 数据库下载国家药监局、国家医保局和巨潮资讯的五条真实大陆样本，并立即执行解析、抽取和清洗。操作与结果解释见[中国大陆权威数据源调试与演示](authoritative_source_demo.md)。

## 5. 观察流水线

Worker 会自动领取导入任务。正常状态依次为：

`DISCOVERED → FETCHED → PARSED → ENTITY_EXTRACTED → RELATION_EXTRACTED → CLEANED → NEEDS_REVIEW → APPROVED → PROJECTED`

查看 Worker 日志：

~~~powershell
docker compose --profile core logs --tail 200 worker
~~~

查询最近文档和任务：

~~~powershell
docker compose --profile core exec postgres psql -U pharma -d pharma -c "SELECT id,title,current_version_id FROM document ORDER BY created_at DESC LIMIT 20;"
docker compose --profile core exec postgres psql -U pharma -d pharma -c "SELECT id,pipeline_step,status,attempts,last_error FROM processing_job ORDER BY created_at DESC LIMIT 20;"
~~~

手工重新执行某一文档：

~~~powershell
docker compose --profile core exec api datactl pipeline run DOCUMENT_ID
~~~

修复来源文件或配置后重试可恢复任务：

~~~powershell
docker compose --profile core exec api datactl pipeline retry JOB_ID
~~~

不要在未查明原因时反复重试 `FAILED_FINAL`。

## 6. 人工复核

查看待复核队列：

~~~powershell
docker compose --profile core exec api datactl review list --limit 100
~~~

复核每条主张时至少检查：

1. 主体、谓词和客体是否正确；
2. 药物、适应症、地区和时间范围是否匹配；
3. 数字、币种、单位和数量级是否与原文一致；
4. PDF 页码、坐标、字符区间或音频时间段能否定位原文；
5. 是否存在时间、口径、重述或估计值与实际值差异；
6. 许可和访问等级是否允许该用途。

批准主张：

~~~powershell
docker compose --profile core exec api datactl review approve assertion ASSERTION_ID --reviewer "成员姓名" --rationale "已核对第 12 页表 3，主体、单位和报告期一致"
~~~

只有有完整证据的已批准主张才能成为 Gold 并进入投影。自动抽取结果不能自行升级为 Gold。

## 7. 投影分发与重建

启动完整或对应 Profile 后分发 Outbox：

~~~powershell
docker compose --profile full exec api datactl projection dispatch --limit 100
docker compose --profile full exec api datactl projection dispatch --name neo4j --limit 100
~~~

单独重建投影：

~~~powershell
docker compose --profile full exec api datactl projection rebuild neo4j
docker compose --profile full exec api datactl projection rebuild milvus
docker compose --profile full exec api datactl projection rebuild timescale
docker compose --profile full exec api datactl projection rebuild elasticsearch
~~~

投影数据库不是事实主库。发生投影异常时先恢复目标服务，再重放 Outbox 或重建投影，禁止绕过 PostgreSQL 直接修正式事实。

## 8. 查询与权限

公开健康检查：

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/health
~~~

带内部密钥查询受限资源：

~~~powershell
$headers = @{ "X-Internal-API-Key" = "YOUR_INTERNAL_API_KEY" }
Invoke-RestMethod -Headers $headers http://127.0.0.1:8000/v1/documents/DOCUMENT_ID
~~~

所有公开导出都必须重新执行权限过滤。内部查询成功不代表内容可以公开。

## 9. 构建数据集快照

准备 JSON 规格文件：

~~~json
{
  "name": "phase2-validation-v1",
  "document_version_ids": ["VERSION_ID_1", "VERSION_ID_2"],
  "access_class": "team_internal",
  "created_by": "成员姓名",
  "specification": {
    "purpose": "机制验证",
    "schema_version": "1.0"
  }
}
~~~

执行：

~~~powershell
docker compose --profile core exec api datactl dataset build PATH_TO_SPEC.json
~~~

公开快照只能包含 `public` 文档版本；系统会拒绝混入非公开数据。

## 10. 质量验证

代码和契约检查：

~~~powershell
uv sync --extra dev
uv run ruff check src tests
uv run pytest -q
uv run datactl eval all
docker compose --profile full config --quiet
~~~

Gold 基准：

~~~powershell
uv run datactl eval benchmark path/to/gold-benchmark.json
~~~

阈值和数据格式见[Gold 基准说明](benchmark.md)。空基准只能做冒烟测试，不能作为正式验收结论。

## 11. 日常操作清单

每次导入前：

- 确认来源、许可、访问等级和负责人；
- 备份统一事实库；
- 抽查清单路径和 URL；
- 记录预计记录数与批次名称。

每次导入后：

- 对比发现、抓取、隔离和失败数量；
- 检查 Worker 错误日志；
- 抽查解析元素及证据坐标；
- 完成人工复核；
- 分发投影并检查 ID 一致性；
- 保存质量报告和审计记录。

## 12. 停止服务

保留数据卷并停止：

~~~powershell
docker compose --profile full down
~~~

`docker compose down -v` 会删除数据库卷，不属于日常停止操作。只有在已确认目标、完成备份且明确需要重建测试环境时才能使用。

备份、恢复、故障分级和投影灾难恢复见[运维与恢复手册](maintenance_and_recovery.md)。
