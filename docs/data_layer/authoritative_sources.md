# 中国大陆权威数据源配置与接入说明

## 1. 当前范围

数据层的受支持入口只接入中国大陆来源。来源目录位于
[`config/authoritative_sources.json`](../../config/authoritative_sources.json)，每条记录都固定包含
`jurisdiction=CN-MAINLAND`。CLI 和 REST API 不再提供 ClinicalTrials.gov、FDA、SEC 或港交所同步入口。

当前登记 34 个来源，覆盖券商研报、临床、药品监管、医保支付、财务报表、证券行情、新闻、电话会议、行业统计、进出口、专利和药物安全。

来源分级：

- `A1`：国务院部门、监管机构、交易所、法定披露平台和国家级注册平台；
- `A2`：中国大陆上市公司第一方材料、持牌证券公司研究所或已获合法授权的提供方。

聚合网站、转载媒体、自媒体和来源不明数据库不能冒充 `A1/A2`。

## 2. 接入方式必须如实标记

| 接入方式 | 含义 | 系统动作 |
|---|---|---|
| `official_direct_document` | 官方页面或文件存在稳定直链 | 可小批量自动读取，并校验请求前后域名 |
| `official_download` | 官网提供下载文件 | 人工确认下载项后接入 |
| `official_query` | 官网提供公开查询，但没有稳定公开 API | 人工查询、导出或登记详情页 |
| `official_manifest` | 逐项登记官方 URL 或本地文件 | 使用清单导入 |
| `authorized_manifest` | 内容受版权或订阅约束 | 核验授权后使用受限清单 |

截至 2026-08-22，未发现能够同时满足“官方文档、稳定、跨主体批量查询”三个条件的中国大陆临床、A 股公告、研报和电话会议统一开放 API。部分官网前端存在查询端点，但官方没有承诺其稳定性；项目不会把网页内部端点写成“公开 API”。

## 3. 核心来源

### 3.1 临床与药品监管

| 来源 | 可获得数据 | 当前接入 |
|---|---|---|
| [药物临床试验登记与信息公示平台](https://www.chinadrugtrials.org.cn/) | CTR 登记号、药物、适应症、申办者、阶段和状态 | 人工查询/导出 |
| [中国临床试验注册中心](https://www.chictr.org.cn/about.html) | ChiCTR 登记、研究设计、机构和结局 | 人工查询/导出 |
| [药审中心](https://www.cde.org.cn/main/guide/contentpage/545cf855a50574699b46b26bcb165f32) | 受理、公示、上市药品、审评报告和说明书 | 官方文件清单 |
| [国家药监局数据查询](https://www.nmpa.gov.cn/datasearch/home-index.html) | 药品批准、持有人、生产企业和器械批准 | 官方查询/导出 |
| [国家药监局政务服务](https://zwfw.nmpa.gov.cn/web/taskview/11100000MB0341032Y100207202900001) | 临床试验登记与审批事项、材料和法定依据 | 稳定页面直连 |
| [国家药品不良反应监测中心](https://www.cdr-adr.org.cn/) | 药物警戒、风险沟通和年度报告 | 官方文件清单 |
| [医疗器械唯一标识数据库](https://udi.nmpa.gov.cn/) | 器械标识、注册人和产品信息 | 官方查询 |

药物临床试验平台和 CDE 对部分自动请求返回校验页；ChiCTR 检索页对自动 GET 有访问限制。系统不得绕过验证码、脚本校验或登录。

### 3.2 医保、市场空间与行业统计

| 来源 | 可获得数据 | 当前接入 |
|---|---|---|
| [国家医保药品目录](https://www.nhsa.gov.cn/art/2025/12/7/art_104_18970.html) | 目录准入、支付范围、谈判和创新药目录 | 页面/附件直连 |
| [国家组织集中采购](https://www.nhsa.gov.cn/col/col187/index.html) | 集采批次、品种、中选企业、价格和采购量 | 官方下载 |
| [国家医保局统计](https://www.nhsa.gov.cn/) | 参保、基金支出、结算人次和谈判药使用 | 页面/附件直连 |
| [国家卫健委统计年鉴](https://www.nhc.gov.cn/wjw/tjnj/list.shtml) | 医疗机构、患者、卫生费用和资源 | 人工下载 |
| [国家数据](https://data.stats.gov.cn/) | 人口、医药制造业、价格和工业利润 | 官方查询/下载 |
| [海关统计](https://stats.customs.gov.cn/) | 药品、原料药和器械进出口 | 官方查询/下载 |
| [国家知识产权局](https://www.cnipa.gov.cn/) | 专利、申请人、法律状态和期限 | 官方查询 |
| [中国疾控中心](https://www.chinacdc.cn/) | 疾病监测、流行病学和疫苗信息 | 官方报告清单 |

### 3.3 财务报表与证券监管

| 来源 | 用途 | 当前接入 |
|---|---|---|
| [巨潮资讯](https://www.cninfo.com.cn/new/index) | 沪深京法定公告、定期报告和临时公告 | 官方 PDF 直连/清单 |
| [上海证券交易所](https://www.sse.com.cn/disclosure/listedinfo/announcement/) | 沪市公告和监管问询 | 官方清单 |
| [深圳证券交易所](https://www.szse.cn/disclosure/listed/notice/) | 深市公告和监管问询 | 官方清单 |
| [北京证券交易所](https://www.bse.cn/disclosure/announcement.html) | 北交所上市公司公告 | 官方清单 |
| [全国股转系统](https://www.neeq.com.cn/) | 新三板挂牌公司公告 | 官方清单 |
| [中国证监会](https://www.csrc.gov.cn/) | 监管政策、处罚、IPO 和执法 | 官方清单 |

结构化 XBRL/XLSX 优先于 PDF；没有结构化文件时，PDF 是原始证据。报告期、发布日期、币种、单位、合并范围、审计和重述必须分别保存。

### 3.4 电话会议和投资者关系

| 来源 | 可获得材料 | 当前接入 |
|---|---|---|
| [巨潮投资者关系](https://irm.cninfo.com.cn/) | 活动记录表、分析师会议、业绩说明会和问答 | 官方 PDF/页面 |
| [上证路演中心](https://www.sseinfo.com/services/roadshow/showcenter/) | 业绩说明会、路演、图文和音视频 | 清单，音视频逐项核验 |
| [深交所互动易](https://www.szse.cn/aboutus/trends/news/t20190517_567238.html) | 投资者问答和调研活动记录 | 官方清单 |
| [北交所](https://www.bse.cn/disclosure/announcement.html) | 业绩说明会材料 | 官方清单 |
| 上市公司 IR 官网 | 演示稿、文字稿、录音和公告 | 逐家公司建立域名白名单 |

“电话会议”数据优先采用交易所披露的活动记录表和公司官方文字稿。录音只有在来源、参与者和使用授权均明确时才允许导入。

### 3.5 证券行情

| 来源 | 官方依据 | 当前接入 |
|---|---|---|
| [上交所行情服务](https://www.sse.com.cn/transparency/services/index.shtml) | 产品、授权许可、收费标准和办理入口 | 授权文件清单 |
| [深交所行情接口规范](https://www.szse.cn/marketServices/technicalservice/interface/index.html) | 行情数据接口与技术规范；规范本身不等于使用许可 | 授权文件清单 |
| [北交所境内行情授权指南](https://www.bse.cn/application/guide.html) | 明确的许可使用申请和使用边界 | 授权文件清单 |

交易所网页展示只能用于人工核验。批量行情、历史行情和内部模型处理必须由交易所信息公司或合同允许的合规数据终端提供。原始行情默认 `authorized_restricted + restricted`，并使用 `market_data` 清单导入。

### 3.6 券商研报与官方新闻

券商研报只允许来自中国大陆持牌证券公司研究所或合法授权提供方。中国证券业协会的[发布证券研究报告执业规范](https://www.sac.net.cn/sjb/flfg_949/zlgz/202005/t20200525_14376.html)要求研究机构管理信息来源和发布流程；该规范不等于允许第三方复制全文。

官方新闻和政策来源包括中国政府网、国家药监局、药审中心、国家医保局、国家卫健委、证监会、交易所、工信部和市场监管总局。公司事件优先使用法定公告，其次才是公司官网新闻。

## 4. 许可和公开边界

新增许可状态：

- `public_access`：公众能访问，允许项目内部解析，但不能据此认定可再分发全文；
- `public`：有明确依据允许公开分发，才可进入公开快照；
- `authorized_restricted`：已有授权，但仅限受限范围；
- `metadata_only`、`prohibited`、`unknown`：不下载正文。

大陆官网直连样本默认使用 `public_access + restricted`；只有确认可对外展示的内容才放入 `data/public` 并标记 `public`。

## 5. 检查来源

列出全部大陆来源：

~~~powershell
.venv\Scripts\datactl.exe source list
~~~

检查目录配置：

~~~powershell
.venv\Scripts\datactl.exe source doctor
~~~

只探测一个来源：

~~~powershell
.venv\Scripts\datactl.exe source doctor --live --source-id cninfo_disclosures
~~~

不建议第一次就探测全部来源。官网返回 `202`、`405` 或 `412` 时，应转为人工导出，不能更换为转载站点或尝试绕过保护。

## 6. 同步已登记直连样本

~~~powershell
.venv\Scripts\datactl.exe source sync cninfo_disclosures --run-pipeline
.venv\Scripts\datactl.exe source sync cninfo_investor_relations --run-pipeline
.venv\Scripts\datactl.exe source sync nhsa_drug_catalog --run-pipeline
.venv\Scripts\datactl.exe source sync nmpa_government_service --run-pipeline
~~~

这些命令读取来源目录中的真实官方样本，用于联调，不等于全量抓取。

没有直连样本的来源会拒绝 `source sync`，并要求使用清单：

~~~powershell
.venv\Scripts\datactl.exe ingest manifest PATH_TO_MANIFEST --source-type china_drug_trials
.venv\Scripts\datactl.exe ingest manifest PATH_TO_MANIFEST --source-type cde
.venv\Scripts\datactl.exe ingest manifest PATH_TO_MANIFEST --source-type financial_reports
.venv\Scripts\datactl.exe ingest manifest PATH_TO_MANIFEST --source-type market_data
.venv\Scripts\datactl.exe ingest manifest PATH_TO_MANIFEST --source-type news
~~~

## 7. 推荐更新频率

| 数据 | 建议频率 | 去重主键 |
|---|---|---|
| 法定公告、监管和安全事件 | 每日 | 公告编号/官方 URL/内容哈希 |
| 临床登记 | 每周；关键项目每日 | CTR/ChiCTR 编号 + 版本日期 |
| 财务定期报告 | 披露季每日 | 证券代码 + 报告期 + 公告编号 |
| 证券行情 | 每个交易日或研究批次 | 交易所 + 证券代码 + 交易日 + 复权口径 |
| 投资者关系记录 | 每周 | 证券代码 + 活动编号 + 日期 |
| 医保、集采和目录 | 事件触发 | 文件编号 + 发布日期 |
| 卫生、医保、统计年鉴 | 月度或年度 | 指标代码 + 统计期 + 地区 |
| 研报 | 授权源到达时 | 机构 + 报告编号 + 内容哈希 |

所有更新都保留旧版本，不用“最新值”覆盖历史事实。
