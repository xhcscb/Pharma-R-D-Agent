# 文件投递箱、自动 metadata 与归档

## 1. 使用方式

投递目录只有两类：可无 Key 公开的文件放入 `data/public`，需要内部 Key 的文件放入 `data/restricted`。目录强制决定 `access_class`；常驻 worker 每 10 秒同时扫描两个目录，等待文件写入稳定后自动完成：

1. 计算 SHA-256，按文件名、PDF 首页和可选侧车信息识别资料类型；
2. 提取标题、发行主体、股票代码、报告期、页数、PDF 内置属性等 metadata；
3. 写入来源记录、不可变原件、文档版本和处理任务；
4. 执行 PDF/HTML/表格/文本等解析，进入实体、关系、冲突和人工复核队列；
5. 将原件移动到对应目录的 `_archive/<类型>/<年份>/<哈希前缀>/<完整哈希>.<扩展名>`；
6. 将逐文件回执写入 `_metadata/<sha256>.metadata.json`，将批次 Manifest 写入 `_metadata/manifests/`；
7. 同一内容再次投递时按 SHA-256 去重；如果同时提供了新的来源侧车信息，则原地更新来源与治理 metadata，不重复建立文档。

同一哈希同时存在于 `public` 和 `restricted` 时，两份原件分别归档，主库只保留一个解析版本并标记为 `public`。受限视图包含公开文档，因此同一数据不会重复生成元素、实体和主张。

默认支持 PDF、HTML、TXT、Markdown、JSON/JSONL、CSV、XLSX、XML/XBRL、PNG/JPEG、WAV/MP3/M4A。无法识别或损坏的文件移动到 `_quarantine`，错误写入回执，不会阻塞同批其他文件。

## 2. 启动和检查

一次性处理并立即跑完整流水线：

~~~powershell
.venv\Scripts\datactl.exe inbox status
.venv\Scripts\datactl.exe inbox run
~~~

持续自动处理：

~~~powershell
.venv\Scripts\python.exe -m pharma_data.orchestration.worker
~~~

Docker `worker` 使用同一逻辑，`./data` 已挂载到容器内。关键环境变量如下：

~~~dotenv
INBOX_ENABLED=true
PUBLIC_INBOX_ROOT=./data/public
PUBLIC_INBOX_ARCHIVE_ROOT=./data/public/_archive
PUBLIC_INBOX_METADATA_ROOT=./data/public/_metadata
PUBLIC_INBOX_QUARANTINE_ROOT=./data/public/_quarantine
RESTRICTED_INBOX_ROOT=./data/restricted
RESTRICTED_INBOX_ARCHIVE_ROOT=./data/restricted/_archive
RESTRICTED_INBOX_METADATA_ROOT=./data/restricted/_metadata
RESTRICTED_INBOX_QUARANTINE_ROOT=./data/restricted/_quarantine
INBOX_ARCHIVE_MODE=move
INBOX_POLL_SECONDS=10
INBOX_SETTLE_SECONDS=5
~~~

如果不希望移动投递原件，可把 `INBOX_ARCHIVE_MODE` 改成 `copy`；生产环境推荐 `move`，避免同一目录长期混放“待处理”和“已处理”文件。

## 3. 为什么文件可以自动入库，却不能自动成为 A1/A2 证据

文件内容和文件来源是两个不同事实。系统可以从报告正文识别公司、代码和报告期，但不能仅凭一个 PDF 证明它确实来自交易所、巨潮资讯、公司官网或合法订阅。因此：

- 没有侧车 metadata 的文件使用 `local_inbox_unverified`和 `B2`；`public` 目录生成 `public_access + public`，`restricted` 目录生成 `authorized_restricted + restricted`；
- 原件仍会解析并生成 Candidate，但 Evidence Gate 不会把高风险数值当作 A1/A2 事实；
- 只有来源编号属于 `config/authoritative_sources.json`，且官方 URL 域名或授权依据通过目录校验，才登记为 A1/A2；
- 来源核验不会自动批准抽取主张，人工复核仍是独立门禁。

## 4. 为公开法定报告补充权威来源

在投递文件旁创建 `<完整文件名>.metadata.json`。例如：

`恒瑞医药2026Q1报告.pdf.metadata.json`

~~~json
{
  "title": "江苏恒瑞医药股份有限公司2026年第一季度报告",
  "document_type": "financial_report",
  "source_id": "cninfo_disclosures",
  "canonical_url": "https://static.cninfo.com.cn/finalpage/实际日期/实际文件.PDF",
  "published_at": "2026-04-22T00:00:00+08:00",
  "issuer": "江苏恒瑞医药股份有限公司",
  "stock_code": "600276",
  "report_period": "2026-Q1",
  "license_status": "public_access",
  "access_class": "public"
}
~~~

操作步骤：

1. 在巨潮资讯、上交所或深交所的公告检索页查到同一报告；
2. 复制公告详情页或官方 PDF 直链，核对公司代码、报告期、页数和文件哈希；
3. 巨潮资讯使用 `cninfo_disclosures`；上交所链接使用 `sse_disclosures`；深交所链接使用 `szse_disclosures`；
4. 填写公告实际发布日期，不能把 PDF 创建时间当作发布日期；
5. 将 PDF 和侧车文件一起放入 `data/public`，执行 `datactl inbox run`，或等待 worker；
6. 查看回执中的 `provenance_status`。只有 `catalog_verified` 且 `missing_formal_fields` 为空，`metadata_review_required` 才会变为 `false`。

对于已经归档的同一文件，可以重新下载或从归档复制一份，以原文件名再次投递，并同时放入侧车。内容哈希相同会返回 `operation=metadata_updated`，原地升级来源信息；哈希不同则被视为新的文档版本，不会覆盖旧证据。

## 5. 为授权券商研报补充许可依据

券商研报没有统一公开全文接口。必须使用已授权材料，并在侧车中填写：

~~~json
{
  "title": "报告正式标题",
  "document_type": "research_report",
  "source_id": "authorized_mainland_broker_research",
  "authorization_reference": "合同、机构订阅或公开许可的内部登记编号",
  "published_at": "2026-08-01T00:00:00+08:00",
  "license_status": "authorized_restricted",
  "access_class": "restricted"
}
~~~

不要在仓库里提交合同、账号、Cookie 或报告全文。`authorization_reference` 应指向团队受控台账；系统只保留可审计编号。

## 6. API 与下游推理

- `GET /v1/inbox/status`：查看待处理、回执、隔离和 metadata 复核状态；
- `POST /v1/inbox/run`：立即触发一批，默认只入库排队，传 `{"run_pipeline": true}` 可同步跑完整流水线；
- `GET /v1/visualizations/data-layer`：看板聚合投递箱、来源核验、候选/已批准主张和推理就绪度；
- `POST /v1/reasoning/context`：返回版本化 Claim Graph、证据定位、Metric Ontology 和逐主张 Evidence Gate 决策。

这些接口访问受限文件时必须提供 `X-Internal-API-Key`。下游推理默认只读取 `approved`；内部调试设置 `include_candidates=true` 时也会保留 `revise`、`flag_conflict` 等门控结果，不会静默升级候选事实。
