# 权威数据源调试与演示

本演示用四个小样本验证“官方发现—原始存档—解析—实体/关系抽取—清洗”链路。演示数据库与对象文件位于 `data/demo/`，已加入 `.gitignore`。

## 1. 演示内容

| 来源 | 默认样本 | 验证能力 |
|---|---|---|
| ClinicalTrials.gov | pembrolizumab 与非小细胞肺癌研究 1 条 | 临床 API、完整 JSON、临床实体 |
| openFDA | pembrolizumab 标签 1 条 | 监管 JSON、药品名称和证据保留 |
| SEC CompanyFacts | Merck CIK `0000310158` | 财务事实、报告时间和完整官方 JSON |
| FDA 药品 RSS | 最新记录 1 条 | RSS 发现、官方 HTML、新闻解析 |

默认公司和药物仅用于技术演示，不构成投资建议或医学建议。

## 2. 准备

~~~powershell
Copy-Item .env.example .env
~~~

在 `.env` 中填写团队真实联系邮箱：

~~~dotenv
PROJECT_CONTACT_EMAIL=team@example.org
~~~

未填写时，前三个非 SEC 来源仍会继续演示，SEC 会记录为 `FAILED` 并说明缺少配置。

## 3. 一键运行

本地虚拟环境：

~~~powershell
.venv\Scripts\datactl.exe source demo
~~~

Docker 核心服务：

~~~powershell
docker compose --profile core run --rm api datactl source demo
~~~

输出文件：

- `data/demo/authoritative-demo.db`：隔离的 SQLite 事实库；
- `data/demo/objects/`：按哈希保存的原始 JSON/HTML；
- `data/demo/authoritative-demo-report.json`：每个来源的导入与流水线结果。

演示可重复执行。相同内容不会创建重复文档版本或重复任务。

## 4. 结果判读

来源成功示例：

~~~json
{
  "source": "openfda",
  "status": "OK",
  "ingestion": {
    "records_discovered": 1,
    "artifacts_stored": 1,
    "versions_created": 1,
    "jobs_enqueued": 1,
    "quarantined_records": 0
  },
  "pipeline": [
    {
      "status": "NEEDS_REVIEW",
      "elements": 55,
      "quality_level": "Silver"
    }
  ]
}
~~~

`NEEDS_REVIEW` 是预期状态：自动抽取不能自动升级为 Gold。首次运行应创建版本和任务；重复运行时 `versions_created`、`jobs_enqueued` 可以为 0。

## 5. 查询演示数据库

使用 Python 查看汇总：

~~~powershell
@'
import sqlite3
db = sqlite3.connect("data/demo/authoritative-demo.db")
for table in ("source_registry", "source_record", "document", "document_version", "document_element", "entity_mention", "assertion"):
    count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"{table}: {count}")
'@ | .venv\Scripts\python.exe -
~~~

查看来源和文档：

~~~powershell
@'
import sqlite3
db = sqlite3.connect("data/demo/authoritative-demo.db")
for row in db.execute("""
SELECT s.name, d.document_type, d.title, v.license_status, v.access_class
FROM document d
JOIN document_version v ON v.id = d.current_version_id
JOIN source_record r ON r.id = v.source_record_id
JOIN source_registry s ON s.id = r.source_id
ORDER BY s.name, d.title
"""):
    print(row)
'@ | .venv\Scripts\python.exe -
~~~

## 6. 常见故障

### ClinicalTrials.gov 返回 5xx

连接器会有限重试。官方服务仍不可用时，本次来源显示 `FAILED`，其他来源继续运行。稍后重新执行即可，不能把失败当成“零记录”。

### SEC 显示未配置

检查：

~~~powershell
.venv\Scripts\datactl.exe source doctor --live
~~~

确认 `.env` 中 `PROJECT_CONTACT_EMAIL` 是真实邮箱，或 `SEC_USER_AGENT` 含真实邮箱。

### openFDA 返回 429

等待限流窗口恢复；生产批量任务申请 `OPENFDA_API_KEY`，并控制调用频率。

### RSS 能读取但正文抓取失败

保留 RSS 元数据和错误。检查官方页面是否临时维护或发生重定向，不得改用转载页面替代官方证据。

## 7. 五类来源如何演示

自动演示覆盖临床、监管/药品、财务和新闻。券商研报与电话会议必须使用团队实际获授权材料：

~~~powershell
.venv\Scripts\datactl.exe ingest manifest manifests/examples/research_reports.csv --source-type research_reports
.venv\Scripts\datactl.exe ingest manifest manifests/examples/earnings_calls.csv --source-type earnings_calls
~~~

示例清单只是字段模板。必须先替换成真实官方/授权路径和许可状态，不能将测试占位文件当作真实数据。
