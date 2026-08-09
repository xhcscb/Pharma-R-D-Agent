# 数据层可视化操作说明

数据层看板用于观察“来源接入—文档解析—实体抽取—关系抽取—证据绑定—人工复核”的实际处理结果。它只读取统一事实库，不直接查询 Neo4j、Milvus、TimescaleDB 或 Elasticsearch，因此四类投影被删除或重建时，看板统计仍然可用。

## 1. 看板内容

看板展示：

- 权威来源、来源记录、原始制品、文档和历史版本数量；
- 标题、段落、表格、脚注和图形等解析元素；
- 实体类型、实体链接数量和抽取置信度；
- 关系类型、候选主张、证据覆盖率和人工复核状态；
- 每份文档的元素、实体提及和关系主张数量；
- 主张对应的原文片段、文档标题和 PDF 页码；
- 许可状态、访问等级、任务状态和冲突数量。

默认采用以下统计口径：

- 业务统计只计算每份文档的当前版本，避免动态网页的历史版本重复放大结果；
- 版本、任务和运行统计保留历史记录，用于检查幂等性和处理血缘；
- 可视范围始终受 `access_class` 和内部 API Key 约束；
- `Candidate` 主张只用于复核演示，不代表已确认事实，也不会直接投影为正式图谱边。

## 2. 使用现有中国大陆演示库

在仓库根目录执行：

~~~powershell
Copy-Item .env.example .env
~~~

将 `.env` 中的 `DATABASE_URL` 临时改为：

~~~text
sqlite:///./data/demo/china-mainland-demo.db
~~~

同时将 `INTERNAL_API_KEY` 改为仅供本机演示的长随机值，然后启动 API：

~~~powershell
.venv\Scripts\uvicorn.exe pharma_data.api.app:app --host 127.0.0.1 --port 8000
~~~

浏览器打开：

~~~text
http://127.0.0.1:8000/demo/data-layer
~~~

演示库中的文档是 `team_internal`。在页面选择“团队内部”，输入 `.env` 中的 `INTERNAL_API_KEY`，再单击“刷新数据”。API Key 只用于当前浏览器请求，页面不会把它写入数据库或本地存储。

如果演示库还不存在，先执行：

~~~powershell
.venv\Scripts\datactl.exe source demo
~~~

## 3. 使用 Docker 主库

启动核心服务：

~~~powershell
docker compose --profile core up -d --build
docker compose --profile core exec api alembic upgrade head
~~~

打开 `http://127.0.0.1:8000/demo/data-layer`。容器内 API 使用 `CONTAINER_DATABASE_URL`，不要把本机 `.env` 的 `DATABASE_URL` 改成 `postgres:5432`。

## 4. 直接读取统计接口

公开范围：

~~~powershell
Invoke-RestMethod "http://127.0.0.1:8000/v1/visualizations/data-layer?caller_access=public"
~~~

团队内部范围：

~~~powershell
$headers = @{ "X-Internal-API-Key" = "YOUR_INTERNAL_API_KEY" }
Invoke-RestMethod `
  "http://127.0.0.1:8000/v1/visualizations/data-layer?caller_access=team_internal" `
  -Headers $headers
~~~

接口响应中的主要字段：

| 字段 | 含义 |
|---|---|
| `summary` | 来源、文档、元素、实体、主张、证据、冲突和覆盖率 |
| `pipeline` | 数据处理链路各层数量 |
| `sources` | 权威来源和来源等级 |
| `documents` | 当前文档版本的处理结果 |
| `element_types` | 解析元素分布及平均置信度 |
| `entity_types` | 实体提及、链接数量及平均置信度 |
| `predicates` | 关系类型、数量、置信度和复核状态 |
| `jobs`、`runs` | 流水线任务与运行状态 |
| `licenses` | 许可状态与访问等级 |
| `evidence_examples` | 可定位到原文的主张证据样例 |

## 5. 结果判读

看板中“证据覆盖率 100%”只表示每条可见主张都绑定了证据记录，不表示关系本身一定正确。必须同时检查：

1. 主体和客体是否来自同一句或同一表格语境；
2. PDF 页码、元素坐标和原文片段是否定位准确；
3. 日期、地区、适应症和临床阶段等限定条件是否完整；
4. `review_status` 是否已由 `candidate` 变为 `approved`；
5. 许可是否允许当前范围的查询或派生发布。

当前演示中的关系仍是 `Candidate`，其用途是暴露抽取错误、验证 Evidence Gate 和组织人工复核，不能作为投资结论直接使用。

## 6. 常见问题

### 页面只有零数据

先确认 API 使用的 `DATABASE_URL` 指向正确数据库，再确认页面选择的访问范围。中国大陆真实来源演示默认是 `team_internal`，公开范围不会显示这些文档。

### 返回 403

所选范围不是 `public`，但页面中的 API Key 与环境变量 `INTERNAL_API_KEY` 不一致。修改后重启 API。

### 本机报错无法解析 `postgres`

`postgres` 是 Compose 内部服务名。本机运行 API 时应使用 SQLite，或把 PostgreSQL 地址写为 `localhost:5432`。详细排查见[数据层操作手册](operations.md)。

### 数据看起来重复

文档和抽取结果按当前版本统计；`versions`、`jobs` 和 `runs` 故意保留历史。动态官方网页内容哈希变化时可能产生新版本，这是版本血缘，不是文档重复。
