# 数据清单编写指南

数据清单用于受控导入本地文件或官方 URL，支持 CSV、JSON 和 JSONL。清单既是导入输入，也是来源、许可和责任追踪记录。

## 1. 通用必填字段

| 字段 | 含义 | 规则 |
|---|---|---|
| `source_record_id` | 来源内稳定编号 | 必填；同一来源内不可重复 |
| `title` | 文档标题 | 必填；使用来源原始标题 |
| `license_status` | 许可状态 | 必填；取受控枚举 |
| `access_class` | 访问等级 | 必填；不得与许可冲突 |
| `published_at` | 发布时间 | 建议必填；ISO 8601 |
| `canonical_url` | 规范来源页 | 建议填写官方落地页 |
| `local_path` | 本地文件 | 与 `content_url` 至少填一个 |
| `content_url` | 正文下载地址 | 与 `local_path` 至少填一个 |

`published_at` 示例：`2026-08-08`、`2026-08-08T09:30:00+08:00`。不要把财务报告期或临床事件时间误填为发布时间。

## 2. 许可状态

| `license_status` | 含义 | 是否抓取正文 |
|---|---|---|
| `public` | 有明确依据允许公开再分发 | 是 |
| `public_access` | 公众可访问；是否对外展示仍由 `access_class` 和再分发依据决定 | 是 |
| `authorized_restricted` | 已授权，但仅限受控内部使用 | 是 |
| `metadata_only` | 只允许记录元数据 | 否 |
| `prohibited` | 明确禁止处理 | 否 |
| `unknown` | 许可尚未确认 | 否 |

访问等级：

- `public`：无需 API Key，可参与公开查询和公开快照；
- `restricted`：需要 `INTERNAL_API_KEY`，仅指定人员或流程使用。

非公开许可不能填写 `public` 访问等级。系统会拒绝该组合。

## 3. 文件路径与 URL

- 相对 `local_path` 以清单文件所在目录为基准；
- 路径指向实际文件，不能指向目录；
- CSV 建议使用 UTF-8 with BOM，JSON/JSONL 使用 UTF-8；
- URL 必须是官方或已授权地址；
- 不得填写需要绕过登录、付费墙、验证码或访问控制的链接；
- 同一条记录存在多个附件时，可拆成多条稳定记录，并在自定义字段中保存关联 ID。

系统会保存原始文件哈希。文件内容变化会形成新文档版本，不应复用编号伪装为旧版本。

## 4. 可用的 source-type

| CLI 值 | 数据类型 |
|---|---|
| `research_reports` | 券商研报 |
| `china_drug_trials` | 中国药物临床试验记录 |
| `cde` | CDE/NMPA 文件 |
| `clinical_documents` | 临床结果和附件 |
| `financial_reports` | 财务报告 |
| `news` | 新闻 |
| `earnings_calls` | 电话会议 |
| `market_data` | 已授权中国大陆证券行情 |

中国大陆临床注册平台没有被官方承诺稳定的批量 API。先从官网查询或导出，再使用 `china_drug_trials` 清单导入。

## 5. 五类清单示例

### 5.1 券商研报

~~~csv
source_record_id,title,published_at,canonical_url,local_path,license_status,access_class,institution,analyst,stock_code,rating
REPORT-2026-001,某公司创新药深度报告,2026-08-01,,../../data/restricted/report-001.pdf,authorized_restricted,restricted,示例证券,张三,600000.SH,买入
~~~

必须保留机构、分析师、证券代码、评级和授权依据。原始 PDF 只能放在受控数据目录，不得提交 Git。

### 5.2 临床文件

~~~csv
source_record_id,title,published_at,canonical_url,local_path,license_status,access_class,registry_id
CTR20260083,CTR20260083临床试验登记导出,2026-08-09,https://www.chinadrugtrials.org.cn/clinicaltrials.searchlist.dhtml?keywords=CTR20260083,../../data/restricted/CTR20260083.html,public_access,restricted,CTR20260083
~~~

临床和 CDE 文件必须保存官方登记号或受理号、查询日期和详情页。不要把搜索结果页的当前状态当作永久属性。

### 5.3 财务报告

~~~csv
source_record_id,title,published_at,canonical_url,local_path,license_status,access_class,exchange,stock_code,report_period
CNINFO-1225032585,恒瑞医药2025年年度报告,2026-03-26,https://static.cninfo.com.cn/finalpage/2026-03-26/1225032585.PDF,../../data/restricted/1225032585.PDF,public_access,restricted,SSE,600276.SH,2025
~~~

`report_period` 与 `published_at` 必须分开。自定义列会进入原始元数据，可以补充币种、审计状态和合并范围。

### 5.4 新闻

~~~csv
source_record_id,title,published_at,canonical_url,local_path,license_status,access_class,publisher
NHSA-DRUG-CATALOG-2025,2025年国家医保药品目录通知,2025-12-07,https://www.nhsa.gov.cn/art/2025/12/7/art_104_18970.html,../../data/restricted/nhsa-2025.html,public_access,restricted,国家医疗保障局
~~~

如正文被修订或撤回，不要覆盖旧文件；保留新版本并记录修订关系。

### 5.5 电话会议

~~~csv
source_record_id,title,published_at,canonical_url,local_path,license_status,access_class,company,report_period
CALL-2026-001,某公司2026年中期业绩说明会,2026-08-05,https://official.example/call,../../data/restricted/call-001.mp3,authorized_restricted,restricted,某公司,2026H1
~~~

录音必须有明确授权。建议同时提供官方参与者名单、文字稿和演示材料，并用自定义字段记录关联编号。

### 5.6 证券行情

~~~csv
source_record_id,title,published_at,canonical_url,local_path,license_status,access_class,document_type,provider,authorization_reference,exchange,stock_code,adjustment
SSE-600276-20260821,600276 2026-08-21日行情,2026-08-21T15:00:00+08:00,https://www.sse.com.cn/,../../data/restricted/600276-20260821.xlsx,authorized_restricted,restricted,market_data,授权提供方,内部授权编号,SSE,600276.SH,unadjusted
~~~

行情文件支持 JSON、CSV、XLSX。字段至少包含 `company`、`stock_code`、`trade_date` 和一个行情指标；支持 `open/high/low/close/volume/turnover/market_cap` 或对应中文列名。接口技术规范不等于数据使用许可；必须保存提供方、产品、授权编号、导出人、导出时间、授权截止日和复权口径。原始行情不得进入公开快照。

## 6. JSON 与 JSONL

JSON 可直接使用记录数组，也可使用 `{"records": [...]}`。JSONL 每行一条 JSON 对象。

~~~json
{
  "source_record_id": "NHSA-DRUG-CATALOG-2025",
  "title": "2025年国家医保药品目录通知",
  "published_at": "2025-12-07",
  "canonical_url": "https://www.nhsa.gov.cn/art/2025/12/7/art_104_18970.html",
  "content_url": "https://www.nhsa.gov.cn/art/2025/12/7/art_104_18970.html",
  "license_status": "public_access",
  "access_class": "restricted",
  "publisher": "国家医疗保障局"
}
~~~

额外列会写入 `raw_metadata`。复杂自定义元数据可放入 `metadata_json`。

## 7. 导入前检查

- 每条记录的 ID 和标题非空；
- ID 在当前清单中唯一；
- 日期可按 ISO 8601 解析；
- 本地路径存在，或正文 URL 可访问；
- 许可状态有书面依据；
- 非公开许可没有使用公开访问等级；
- 内容类型属于对应适配器允许范围；
- 随机抽取至少 10 条核对标题、来源和文件；
- 清单不包含密码、Cookie、Token 或个人敏感信息。

导入命令：

~~~powershell
datactl ingest manifest PATH_TO_MANIFEST --source-type SOURCE_TYPE
~~~

导入后对比发现、抓取、隔离和失败数量，并保留该批次的清单版本。
