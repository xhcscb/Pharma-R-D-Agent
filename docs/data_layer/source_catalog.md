# 受控数据源目录

| 数据类别 | 适配器 | 权威来源优先级 | 支持格式 | 默认策略 |
|---|---|---|---|---|
| 券商研报 | `ResearchReportManifestAdapter` | 已授权机构或明确授权文件 | PDF | `authorized_restricted / team_internal` |
| 国际临床 | `ClinicalTrialsGovAdapter` | ClinicalTrials.gov API v2 | 完整 JSON | `public` |
| 美国药品监管 | `OpenFdaDrugAdapter` | openFDA Drug API | 完整 JSON | `public` |
| 中国临床 | `ChinaDrugTrialsManifestAdapter` | 官方注册平台 URL 或经复核清单 | HTML、JSON | `public` |
| 药监文件 | `CdeManifestAdapter` | CDE/NMPA 官方发布 | PDF、HTML、JSON | `public` |
| 财务报告 | `FinancialReportAdapter` | 交易所、巨潮资讯、HKEX 或公司 IR | XBRL/XML、XLSX、PDF | `public` |
| 美股申报 | `SecEdgarFilingsAdapter` | SEC Submissions 与 Archives | HTML、Inline XBRL/XML | `public` |
| 美股财务事实 | `SecCompanyFactsAdapter` | SEC XBRL CompanyFacts | 完整 JSON | `public` |
| 新闻 | `NewsAdapter` | 监管机构、交易所或公司 IR | RSS、HTML、JSON | `public` |
| FDA 新闻 | `FdaNewsAdapter` | FDA 官方 RSS 与正文 | RSS、HTML | `public` |
| 电话会议 | `EarningsCallAdapter` | 公司官方文字稿、IR 记录或授权录音 | TXT、HTML、PDF、MP3、WAV、MP4 | 由清单声明 |

## 接入约束

每条来源记录都必须包含来源记录 ID、标题、许可状态和访问等级。标记为 `metadata_only`、`prohibited` 或 `unknown` 的记录只保留来源元数据，状态设为 `QUARANTINED`，不得抓取正文。

非公开许可不能声明公开访问。系统不提供无限制券商网站爬虫，也不得绕过登录、付费墙、验证码或访问控制。

清单字段、示例和导入命令见[数据清单编写指南](manifest_guide.md)。

可执行的完整来源目录位于 [`config/authoritative_sources.json`](../../config/authoritative_sources.json)。API 配置、访问规则和诊断命令见[权威数据源配置与接入说明](authoritative_sources.md)。
