# 数据层查询接口

API 启动后，可通过以下地址访问：

- REST 交互文档：`http://127.0.0.1:8000/docs`
- GraphQL：`http://127.0.0.1:8000/graphql`
- 健康检查：`http://127.0.0.1:8000/health`
- 数据层看板：`http://127.0.0.1:8000/demo/data-layer`

## 权限规则

公开查询默认只能读取 `public` 数据。读取 `team_internal` 或 `restricted` 数据时，必须在请求头中提供与环境变量 `INTERNAL_API_KEY` 一致的 `X-Internal-API-Key`。

鉴权失败返回 403；资源存在但调用者无权访问时返回 404，避免泄露受限资源是否存在。GraphQL 当前只提供公开读取能力。

## REST 接口

- `POST /v1/ingestions`：创建导入任务；
- `GET /v1/ingestions/{id}`：查看导入状态；
- `POST /v1/documents/{id}/reprocess`：重新处理文档；
- `GET /v1/documents/{id}`：查看文档；
- `GET /v1/documents/{id}/elements`：查看文档元素；
- `GET /v1/entities/{id}`：查看实体；
- `GET /v1/assertions/{id}`：查看主张及证据；
- `GET /v1/conflicts`：查看冲突；
- `GET /v1/review-queue`：查看人工复核队列；
- `POST /v1/reviews` 或 `POST /v1/reviews/{target_type}/{target_id}`：提交复核决定；
- `POST /v1/search`：检索文档或证据；
- `POST /v1/projections/{name}/rebuild`：重建投影；
- `GET /v1/projections/{name}/status`：查看投影状态；
- `POST /v1/dataset-snapshots`：创建数据集快照。
- `GET /v1/visualizations/data-layer`：返回按权限过滤的数据处理、质量和证据链统计。

可视化接口默认只计算文档当前版本的元素、实体和主张，历史版本只进入版本、任务和运行统计。完整操作方法见[数据层可视化操作说明](visualization.md)。

## GraphQL 字段

GraphQL 提供 `document`、`entity`、`entityNeighbors`、`entityTimeline`、`searchDocuments`、`searchEvidence`、`assertion` 和 `conflictGroup`。

完整请求示例见[数据层操作手册](operations.md)。
