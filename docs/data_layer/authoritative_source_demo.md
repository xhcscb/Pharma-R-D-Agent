# 中国大陆权威数据源调试与演示

演示使用五条真实的中国大陆官方材料，验证“下载—原始存档—解析—实体/关系抽取—清洗”链路。数据库和文件位于 `data/demo/`，不会进入 Git。

## 1. 演示样本

| 来源 | 样本 | 验证内容 |
|---|---|---|
| 国家药监局政务服务 | 药物临床试验登记事项页面 | 临床监管、HTML 解析和证据保留 |
| 巨潮资讯 | 恒瑞医药 2025 年年度报告 | 财报 PDF、表格、公司和财务实体 |
| 巨潮投资者关系 | 艾迪药业分析师会议活动记录 | 电话会议文字材料、参与者和管理层主张 |
| 国家医保局 | 2025 年医保药品目录通知 | 医保目录、监管事件和政策证据 |
| 国家医保局 | 2025 年医保事业统计快报 | 行业规模、时间和数值证据 |

这些材料只用于技术验证，不构成投资建议或医学建议。

## 2. 运行前检查

~~~powershell
Copy-Item .env.example .env
.venv\Scripts\datactl.exe db doctor
.venv\Scripts\datactl.exe source doctor
~~~

可先逐个验证稳定直连来源：

~~~powershell
.venv\Scripts\datactl.exe source doctor --live --source-id cninfo_disclosures
.venv\Scripts\datactl.exe source doctor --live --source-id nhsa_drug_catalog
.venv\Scripts\datactl.exe source doctor --live --source-id nmpa_government_service
~~~

## 3. 一键运行

~~~powershell
.venv\Scripts\datactl.exe source demo
~~~

Docker 中运行：

~~~powershell
docker compose --profile core run --rm api datactl source demo
~~~

输出：

- `data/demo/china-mainland-demo.db`：隔离 SQLite 事实库；
- `data/demo/china-mainland-objects/`：按 SHA-256 保存的原始 PDF/HTML；
- `data/demo/china-mainland-demo-report.json`：各来源的导入与流水线结果。

报告根节点必须显示：

~~~json
{
  "jurisdiction": "CN-MAINLAND",
  "mainland_only": true
}
~~~

## 4. 单独同步一个样本

~~~powershell
.venv\Scripts\datactl.exe source sync cninfo_disclosures --run-pipeline
.venv\Scripts\datactl.exe source sync cninfo_investor_relations --run-pipeline
.venv\Scripts\datactl.exe source sync nhsa_drug_catalog --run-pipeline
~~~

`source sync` 只读取来源目录中经过复核的样本，不执行无限制站点抓取。没有直连样本的来源会要求改用清单。

## 5. 结果判读

成功来源应出现：

~~~json
{
  "source": "cninfo_disclosures",
  "status": "OK",
  "ingestion": {
    "records_discovered": 1,
    "artifacts_stored": 1,
    "quarantined_records": 0
  }
}
~~~

流水线最终为 `NEEDS_REVIEW` 是正常结果。自动抽取只能成为 Silver 或 Candidate，不能自动升级为 Gold。重复运行时，内容哈希和幂等键会阻止重复文档版本和任务。

官网材料默认显示：

~~~text
license_status = public_access
access_class   = team_internal
~~~

这表示可以在团队内部解析，但不能仅凭“官网公开”将全文放进公开数据集。

## 6. 查询演示数据库

~~~powershell
@'
import sqlite3
db = sqlite3.connect("data/demo/china-mainland-demo.db")
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

## 7. 常见故障

### 返回 202、405 或 412

这通常是官网访问保护，不是“零条数据”。将该来源转为人工查询/导出清单，不得绕过验证码、脚本校验或登录。

### PDF 下载成功但抽取较慢

年度报告页数较多。首次运行需要建立页面和表格元素，属于正常现象。可先运行不带 `--run-pipeline` 的单源同步，仅验证下载和原始存档。

### `UNAVAILABLE`

检查网络和官方站点是否维护，稍后重试。不要自动改用转载页面替代官方证据。

### 研报没有自动样本

券商研报受版权和订阅约束。先取得授权，再用：

~~~powershell
.venv\Scripts\datactl.exe ingest manifest manifests/examples/research_reports.csv --source-type research_reports
~~~
