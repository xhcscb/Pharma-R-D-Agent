# 权威数据源配置与接入说明

本文说明数据从哪里来、哪些来源可以自动同步、哪些来源必须人工建清单，以及如何验证来源没有被错误配置。

## 1. 权威性分级

本工程只启用两个来源等级：

- `A1`：监管机构、临床注册机构、证券交易所等第一方官方数据；
- `A2`：上市公司投资者关系网站、券商研究所或获得合法授权的提供方。

聚合网站、转载媒体和来源不明的数据不能冒充 `A1/A2`。全部已配置来源见 [`config/authoritative_sources.json`](../../config/authoritative_sources.json)。

## 2. 已可自动同步的来源

| 数据 | 官方来源 | 接入方式 | 密钥或身份 | 当前命令 |
|---|---|---|---|---|
| 临床试验 | ClinicalTrials.gov | API v2 完整 JSON | 无 | `clinicaltrials` |
| 药品标签、审批、召回、短缺 | openFDA | REST API | 小规模可无密钥；生产建议 API Key | `openfda` |
| 财务申报正文 | SEC EDGAR Submissions | REST API + 官方 Archives | 必须提供项目联系邮箱 | `sec-filings` |
| 标准化财务事实 | SEC EDGAR CompanyFacts | REST API 完整 JSON | 必须提供项目联系邮箱 | `sec-companyfacts` |
| 药品、疫苗、生物制品和新闻稿 | FDA | 官方 RSS + 官方网页 | 无 | `fda-news` |

官方依据：

- [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/about-api)提供现代 JSON API 和 OpenAPI 规范；
- [SEC EDGAR 数据 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)公开 Submissions 和 XBRL CompanyFacts，访问不需要 API Key；
- [SEC 自动访问政策](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits)要求自动工具可识别，并限制过高请求速率；
- [openFDA 药品端点](https://open.fda.gov/apis/drug/)覆盖标签、Drugs@FDA、召回和短缺；[认证说明](https://open.fda.gov/apis/authentication/)给出无 Key 和有 Key 的调用限额；
- [FDA 官方订阅页](https://www.fda.gov/about-fda/contact-fda/subscribe-podcasts-and-news-feeds)列出药品、生物制品、MedWatch 和新闻稿 RSS。

## 3. 必须使用官方清单的来源

以下来源没有被官方承诺为稳定的跨站点公开 API，工程不调用网页内部接口：

| 数据 | 权威来源 | 接入方式 | 原因 |
|---|---|---|---|
| 中国临床试验 | 药物临床试验登记与信息公示平台 | 官方 URL/导出文件清单 | 未提供稳定公开 API |
| CDE/NMPA 文件 | CDE、NMPA 官方网站 | 官方 URL/文件清单 | 只读取公开页面，不绕过验证码 |
| A 股财报与公告 | 巨潮资讯、上交所、深交所 | 官方公告 URL/导出清单 | 网页内部接口不等于公开 API |
| 港股公告 | HKEXnews | 官方公告 URL/导出清单 | 保留公告编号和原始链接 |
| 券商研报 | 券商研究所或合法授权提供方 | 授权文件清单 | 版权和订阅边界不同，不存在统一开放 API |
| 电话会议 | 公司 IR、交易所投资者关系记录 | 官方 URL 或已授权音视频清单 | 不存在统一官方 API，录音权利需逐份确认 |

清单字段和许可规则见[数据清单编写指南](manifest_guide.md)。

## 4. 环境配置

复制示例配置：

~~~powershell
Copy-Item .env.example .env
~~~

必须人工填写：

~~~dotenv
PROJECT_CONTACT_EMAIL=团队真实可联系邮箱
~~~

SEC 要求自动工具具有可联系身份。未配置时，`sec-filings`、`sec-companyfacts` 和真实演示会明确返回 `NOT_CONFIGURED`，不会匿名请求。

可选配置：

~~~dotenv
OPENFDA_API_KEY=申请到的免费Key
SEC_USER_AGENT=项目名/版本 (团队联系邮箱)
~~~

`SEC_USER_AGENT` 与 `PROJECT_CONTACT_EMAIL` 二选一。若二者都填，优先使用 `SEC_USER_AGENT`。`.env` 不得提交 Git。

## 5. 列出和检查来源

列出全部来源及接入方式：

~~~powershell
.venv\Scripts\datactl.exe source list
~~~

只检查本地配置：

~~~powershell
.venv\Scripts\datactl.exe source doctor
~~~

执行只读网络探测：

~~~powershell
.venv\Scripts\datactl.exe source doctor --live
~~~

状态含义：

| 状态 | 含义 | 处理 |
|---|---|---|
| `OK` | 官方端点可访问 | 可以同步 |
| `READY` | 配置完整，但未执行联网测试 | 需要时加 `--live` |
| `NOT_CONFIGURED` | 缺少联系身份或密钥 | 补充 `.env` |
| `UNAVAILABLE` | 网络、限流或官方服务临时异常 | 保留错误，稍后重试 |
| `MANUAL_REQUIRED` | 只能通过官方/授权清单接入 | 按清单指南操作 |

## 6. 同步命令

### 6.1 ClinicalTrials.gov

~~~powershell
.venv\Scripts\datactl.exe source sync clinicaltrials `
  --condition "non-small cell lung cancer" `
  --intervention pembrolizumab `
  --page-size 10 --max-pages 1 --run-pipeline
~~~

保存每条研究的完整官方 JSON，不只截取项目当前使用的字段。

### 6.2 openFDA

药品标签：

~~~powershell
.venv\Scripts\datactl.exe source sync openfda `
  --dataset label `
  --search "openfda.generic_name:pembrolizumab" `
  --page-size 5 --max-pages 1 --run-pipeline
~~~

`--dataset` 支持：

- `label`：药品标签；
- `drugsfda`：Drugs@FDA 审批记录；
- `enforcement`：召回执法记录；
- `shortages`：药品短缺记录。

### 6.3 SEC EDGAR

财务事实：

~~~powershell
.venv\Scripts\datactl.exe source sync sec-companyfacts `
  --cik 0000310158 --run-pipeline
~~~

申报正文：

~~~powershell
.venv\Scripts\datactl.exe source sync sec-filings `
  --cik 0000310158 `
  --forms "10-K,10-Q,8-K" `
  --after-date 2025-01-01 `
  --page-size 3 --max-pages 1 --run-pipeline
~~~

`CIK` 是 SEC 公司标识，系统会自动补足为 10 位。申报正文来自 SEC Archives，记录 accession number、表单类型、报告期和官方证据 URL。

### 6.4 FDA 官方新闻

~~~powershell
.venv\Scripts\datactl.exe source sync fda-news `
  --feed drugs --page-size 3 --run-pipeline
~~~

`--feed` 支持 `drugs`、`biologics` 和 `press-releases`。

## 7. 同步后的数据流

自动来源与清单来源使用同一条流水线：

```text
官方发现接口
→ 原始响应/正文按 SHA-256 存档
→ 文档版本
→ 解析元素
→ 实体提及
→ 带证据主张
→ 清洗与冲突检测
→ 人工复核
→ 四类投影
```

API 返回的原始 JSON、SEC 申报正文和 FDA 新闻 HTML 都会先进入对象存储。规范化结果不能覆盖或替代原始证据。

## 8. 生产使用限制

- 演示默认每个来源只取 1 条，不能把演示参数直接改成无界批量抓取；
- SEC 请求必须带真实联系身份，速率保持低于官方上限；
- openFDA 大批量任务应申请 API Key，并优先考虑官方批量下载；
- 官方服务临时返回 429 或 5xx 时有限重试，最终失败会保留错误，不会伪造空结果；
- 中国监管、交易所和 IR 网站如无公开 API，只使用官方清单；
- 研报和电话会议始终逐份核验许可，受限内容不得进入公开快照。
