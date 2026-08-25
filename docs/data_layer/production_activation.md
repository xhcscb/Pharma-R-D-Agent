# 正式数据接入与生产启用步骤

本文给出从“工程基线”进入“内部试运行”的操作顺序。它不授权任何数据；授权必须由数据提供方、学校或项目负责人取得。

## 1. 先准备四类真实数据

至少准备以下最小批次，每条都要有稳定来源编号、规范 URL、获取日期和许可依据：

1. 临床：从药物临床试验登记与信息公示平台人工导出 20—50 条真实 CTR 记录；
2. 财务与公告：从巨潮资讯或交易所下载 2—3 家医药公司的最近 3 年定期报告；
3. 行情：从上证信息、深圳证券信息、中证股转科技或团队已有合规终端导出 2—3 家公司的日行情；
4. 研报/投资者关系：取得书面授权后导入 10—20 份研报，以及交易所或公司官方活动记录。真实音频不是首批上线的必要条件。

未取得授权的研报和行情不得下载正文；先只登记元数据并把 `license_status` 设为 `metadata_only`。

## 2. 权威源的外部办理

### 2.1 临床登记

1. 打开药物临床试验登记与信息公示平台；
2. 按药物、企业或登记号查询并打开详情；
3. 使用官网允许的打印/导出功能保存 HTML、PDF 或 JSON；若无导出功能，保存详情页 PDF，并记录查询时间；
4. 不绕过验证码、脚本校验或登录；
5. 将 CTR 编号、详情页 URL、导出日期和文件哈希写入清单。

### 2.2 券商研报

1. 由学校或项目主体联系持牌券商研究所或合法数据提供方；
2. 书面确认允许的用户、期限、用途、存储位置、模型处理、派生结果和再分发范围；
3. 保存合同号或授权函编号，不把合同正文写进公开仓库；
4. 只从授权渠道导出，并使用 `authorized_restricted + restricted`；
5. 授权未覆盖模型处理时，不得导入正文。

### 2.3 证券行情

上交所的行情服务页面提供产品、授权许可、收费与办理入口；北交所明确要求行情信息使用许可。深交所技术接口规范仅说明格式，不能代替使用许可。

1. 确认团队已有的终端/数据商合同是否允许研究、批量导出和本地存储；
2. 没有许可时，分别按上证信息、深圳证券信息有限公司或中证股转科技的办理入口申请；
3. 要求导出字段至少包含 `trade_date`、`exchange`、`stock_code`、`company`、`open`、`high`、`low`、`close`、`volume`、`turnover`、`currency`、`adjustment`；
4. 保存产品名、合同/账号、导出时间、导出人、授权截止日和可再分发范围；
5. 原始文件使用 `authorized_restricted`，默认 `restricted`，不得提交 Git。

官方办理入口见[权威数据源配置](authoritative_sources.md)中的“证券行情”。

## 3. 建立受控文件和清单

把原始文件放入受控且被 Git 忽略的目录，例如 `data/restricted/BATCH_ID/`。在受限清单目录创建 JSON：

~~~json
[
  {
    "source_record_id": "SSE-600276-20260821",
    "title": "600276 2026-08-21 日行情",
    "published_at": "2026-08-21T15:00:00+08:00",
    "canonical_url": "https://www.sse.com.cn/",
    "local_path": "../restricted/BATCH_ID/600276-20260821.xlsx",
    "license_status": "authorized_restricted",
    "access_class": "restricted",
    "document_type": "market_data",
    "provider": "上证信息或授权数据商名称",
    "authorization_reference": "内部授权编号",
    "stock_code": "600276.SH",
    "exchange": "SSE",
    "adjustment": "unadjusted"
  }
]
~~~

清单可以进入私有数据治理仓库，但含内部授权编号的清单不建议进入本公开代码仓库。

## 4. 启动、导入和处理

~~~powershell
Copy-Item .env.example .env
docker compose --profile full up -d --build
docker compose --profile full exec api alembic upgrade head
docker compose --profile full ps

docker compose --profile core exec api datactl ingest manifest PATH_TO_CLINICAL_MANIFEST --source-type china_drug_trials
docker compose --profile core exec api datactl ingest manifest PATH_TO_FINANCIAL_MANIFEST --source-type financial_reports
docker compose --profile core exec api datactl ingest manifest PATH_TO_MARKET_MANIFEST --source-type market_data
docker compose --profile core exec api datactl ingest manifest PATH_TO_RESEARCH_MANIFEST --source-type research_reports
~~~

Worker 应把任务推进到 `NEEDS_REVIEW`。用日志和数据库查询核对发现数、版本数、解析元素数、实体数、主张数、证据数和失败数。任何正文为空、证据定位为空或来源不符的批次都要隔离，不能直接复核通过。

## 5. 人工复核、Gold 与门控

~~~powershell
docker compose --profile core exec api datactl review list --limit 100
docker compose --profile core exec api datactl review approve assertion ASSERTION_ID --reviewer "姓名" --rationale "已核对来源、页码/单元格、日期、单位和口径"
docker compose --profile core exec api datactl eval all
docker compose --profile core exec api datactl eval benchmark PATH_TO_NON_EMPTY_GOLD.json
~~~

数字必须核对币种、单位、数量级、报告期、合并范围和复权口径；临床阶段必须核对适应症、地区和时点。Gold 必须非空并经过双人复核。

## 6. 投影和推理验收

~~~powershell
docker compose --profile full exec api datactl projection dispatch --limit 1000
docker compose --profile full exec api datactl projection rebuild neo4j
docker compose --profile full exec api datactl projection rebuild milvus
docker compose --profile full exec api datactl projection rebuild timescale
docker compose --profile full exec api datactl projection rebuild elasticsearch

docker compose --profile core exec api datactl reasoning compare "比较恒瑞医药和另一家公司营业收入" --objects "恒瑞医药,另一家公司" --dimensions "company.revenue"
docker compose --profile core exec api datactl reasoning summarize --entity "恒瑞医药"
~~~

核对四类投影的主张 ID 和数量与 PostgreSQL 一致。比较结果必须报告缺失值和冲突；摘要必须把候选主张放入待复核层，不得生成无证据的确定性结论。

## 7. 允许上线的最低结论

完成上述操作但尚未通过研究冻结和正式案例门时，只能写“内部试运行”。只有[正式研究目标符合性与验收矩阵](../formal_goal_traceability.md)的 G0—G6 全部通过，才能声明正式目标完成。
