# 数据层查询接口

API 启动后，可通过以下地址访问：

- REST 交互文档：`http://127.0.0.1:8000/docs`
- GraphQL：`http://127.0.0.1:8000/graphql`
- 健康检查：`http://127.0.0.1:8000/health`
- 数据层看板：`http://127.0.0.1:8000/demo/data-layer`

## 权限规则

公开查询只读取 `public` 数据且无需 Key。读取 `restricted` 数据时，必须在请求头中提供与环境变量 `INTERNAL_API_KEY` 一致的 `X-Internal-API-Key`。

所有管理和写操作——导入、重处理、提交复核、投影重建/状态、创建快照——无论数据访问等级如何，都必须提供内部密钥。CLI 应在受控主机或容器内运行，不对公网暴露。

鉴权失败返回 403；资源存在但调用者无权访问时返回 404，避免泄露受限资源是否存在。GraphQL 当前只提供公开读取能力。

## REST 接口

- `POST /v1/ingestions`：创建导入任务；
- `GET /v1/inbox/status`：查看投递箱、归档回执和 metadata 复核状态；
- `POST /v1/inbox/run`：立即扫描投递箱并可选同步运行流水线；
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
- `POST /v1/reasoning/compare`：把比较意图编译为 DSL，并返回逐实体、逐指标的主张和证据；
- `POST /v1/reasoning/summarize`：返回共识、冲突、待复核三层同源摘要。
- `POST /v1/reasoning/context`：向下一层返回 Claim Graph、Evidence Gate、Metric Ontology 和就绪度契约。
- `POST /v2/reasoning/context`：在 v1 基础上返回活动解析运行、视觉语义覆盖率与视觉证据定位；视觉主张的 `evidence[].visual_context` 包含裁剪图哈希、颜色/几何观察和推导方法。

可视化接口默认只计算文档当前版本的元素、实体和主张，历史版本只进入版本、任务和运行统计。完整操作方法见[数据层可视化操作说明](visualization.md)。

## GraphQL 字段

GraphQL 提供 `document`、`entity`、`entityNeighbors`、`entityTimeline`、`searchDocuments`、`searchEvidence`、`assertion` 和 `conflictGroup`。

完整请求示例见[数据层操作手册](operations.md)。

## 推理接口

三个推理接口默认使用 `restricted`，因此必须提供内部密钥。默认只读取 `approved` 主张；只有受限复核场景可以显式设置 `include_candidates=true`，候选结果仍会被 Evidence Gate 标记为 `revise`，不会自动升级为事实。

~~~json
{
  "query": "比较恒瑞医药和另一家公司营业收入",
  "objects": ["恒瑞医药", "另一家公司"],
  "dimensions": ["company.revenue"],
  "time": "2025",
  "scope": "合并口径",
  "access_class": "restricted",
  "include_candidates": false
}
~~~

比较响应包含 DSL、每个单元格的 claim/evidence ID、证据门动作、覆盖率、冲突 ID 和警告。摘要的 `tldr`、`key_points`、`full` 共享同一批主张和证据，不能分别生成互不一致的事实。

`/v1/reasoning/context` 的响应固定包含 `schema_version`、权限/复核范围、`readiness`、完整指标本体、`claim_graph` 和逐主张 `gate_decisions`。这是下一层智能体的首选批量接口；正式生成时应保持 `include_candidates=false`。

视觉事实应使用 `/v2/reasoning/context`。当任一实质性图表/图片尚未验证时，
`readiness.blockers` 包含 `visual_semantics_incomplete`，且
`can_use_for_formal_reasoning=false`。推理层不得绕过该门禁自行把 OCR 空单元格解释成阶段。
视觉证据对象遵循 `schemas/visual-semantics.schema.json`；阶段主张同时保留规范化阶段、
原始标签、地区、颜色、条形框、阶段列框、资产哈希和确定性推导方法。
