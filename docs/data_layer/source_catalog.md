# 中国大陆受控数据源目录

支持范围固定为 `CN-MAINLAND`。完整的 31 项来源、域名白名单、访问方式、样本和再分发规则见
[`config/authoritative_sources.json`](../../config/authoritative_sources.json)。

| 数据类别 | 第一优先来源 | 接入方式 | 默认许可 |
|---|---|---|---|
| 券商研报 | 中国大陆持牌券商研究所或合法授权提供方 | 授权清单 | `authorized_restricted` |
| 药物临床 | 药物临床试验登记平台、ChiCTR | 人工查询/导出清单 | `public_access` |
| 药品监管 | NMPA、CDE、不良反应监测中心 | 官方页面、文件或查询清单 | `public_access` |
| 医保与集采 | 国家医保局、国家组织药品联合采购办公室 | 官方页面和附件 | `public_access` |
| 财务报表 | 巨潮资讯、上交所、深交所、北交所、全国股转系统 | 官方 PDF/XBRL/XLSX 清单 | `public_access` |
| 电话会议 | 巨潮投资者关系、上证路演、互动易、公司 IR | 官方记录或授权音视频 | `public_access` 或 `authorized_restricted` |
| 官方新闻 | 国务院部门、监管机构、交易所和公司第一方公告 | 官方 URL 清单 | `public_access` |
| 行业统计 | 国家统计局、卫健委、医保局、海关总署 | 官方查询或下载 | `public_access` |
| 专利 | 国家知识产权局 | 官方查询 | `public_access` |

## 接入约束

- 公众可访问不等于允许公开复制，官网材料默认 `public_access + team_internal`；
- 只有明确允许再分发的内容才能标为 `public`；
- `metadata_only`、`prohibited`、`unknown` 只保存元数据，不下载正文；
- 不调用未公开内部接口，不绕过登录、验证码、脚本校验或付费墙；
- 任何直连请求在跳转前后都必须落在该来源的域名白名单中；
- 境外来源不在 CLI、REST API 和当前来源目录的受支持范围内。

使用方法见[中国大陆权威数据源配置与接入说明](authoritative_sources.md)和[数据清单编写指南](manifest_guide.md)。
