# 检索式目录 v1.1

## 1. 使用方法

下列是与数据库无关的标准概念块。执行人必须根据数据库语法改写，并把“实际执行式”写入 `search_log.csv`。不得只记录本文件中的抽象模板。

## 2. 概念块

```text
DOMAIN_FINANCE =
(financial OR finance OR investment OR "equity research" OR "analyst report"
 OR "securities research" OR 医药投研 OR 券商研报 OR 投资研究)

DOMAIN_PHARMA =
(pharmaceutical OR biopharma OR biotechnology OR drug OR "clinical trial"
 OR pipeline OR 医药 OR 生物医药 OR 药物 OR 临床试验 OR 研发管线)

TASK_DOCUMENT =
("document understanding" OR "question answering" OR summarization
 OR "comparative reasoning" OR "numerical reasoning" OR "report generation")

EVALUATION =
(evaluation OR metric OR benchmark OR factuality OR attribution
 OR evidence OR faithfulness OR "human evaluation")

KNOWLEDGE =
("knowledge graph" OR ontology OR taxonomy OR "hierarchical retrieval"
 OR "graph RAG" OR "claim graph" OR "metric ontology")

AGENT =
(agent OR "multi-agent" OR "tool use" OR orchestration
 OR planning OR "agent evaluation")

PDF =
("PDF parsing" OR "document layout" OR "table extraction"
 OR "chart understanding" OR OCR OR "multimodal document")
```

## 3. 七个主题查询模板

| 查询ID | 主题 | 标准组合 | 对应RQ |
|---|---|---|---|
| Q-A01 | 数据集/方法写作 | `(dataset OR benchmark) AND (documentation OR reproducibility OR datasheet OR "data statement")` | RQ2 |
| Q-B01 | 金融文档推理 | `DOMAIN_FINANCE AND TASK_DOCUMENT AND (table OR text OR numerical)` | RQ1,RQ2 |
| Q-C01 | 比较推理 | `(comparative OR "multi-entity" OR comparison) AND (question answering OR summarization) AND EVALUATION` | RQ3 |
| Q-D01 | 事实与归因 | `(summarization OR generation) AND (factuality OR attribution OR citation OR conflict) AND EVALUATION` | RQ1,RQ4 |
| Q-E01 | 图谱和分层检索 | `KNOWLEDGE AND (retrieval OR generation OR reasoning) AND EVALUATION` | RQ5 |
| Q-F01 | PDF解析 | `PDF AND (financial OR scientific OR report) AND (benchmark OR evaluation)` | RQ6 |
| Q-G01 | Agent评测 | `AGENT AND (benchmark OR evaluation OR trajectory OR collaboration OR recovery)` | RQ7 |

各主题至少补做一条与医药迁移直接相关的查询。B—F主题推荐在标准式后追加 `AND DOMAIN_PHARMA`，并将加限制和不加限制的结果分别记录，避免过早收窄而漏掉可迁移方法。

## 4. 中文查询模板

```text
(金融 OR 投研 OR 券商研报 OR 医药研报)
AND (文档理解 OR 问答 OR 摘要 OR 比较推理 OR 数值推理)
AND (评价 OR 指标 OR 基准 OR 事实一致性 OR 证据归因)
```

```text
(知识图谱 OR 本体 OR 分类体系 OR 分层检索)
AND (金融 OR 医药 OR 文档)
AND (检索 OR 推理 OR 问答 OR 摘要)
```

```text
(智能体 OR 多智能体 OR 工具调用)
AND (评价 OR 基准 OR 协作 OR 错误恢复)
```

## 5. 试检索通过规则

- 组合检索必须召回 `seed_set.csv` 中全部 `is_seed=true` 的文献。
- 对没有覆盖全部领域的单一数据库，使用预先声明的数据库组合测试。
- 每次改写查询式都创建新的 `search_id`。
- 查询过宽时优先增加任务/评价概念块，不通过事后主观删除来伪造精度。
- 查询过窄时先检查字段限制和同义词，再考虑扩大年份。

## 6. 从模板到可复现查询

`search_log.csv` 现有8行都是待执行模板，不能直接标记为完成。每位执行人必须：

1. 在数据库界面确认支持的字段、布尔运算和日期过滤语法；
2. 保存粘贴到数据库中的完整查询，而不是只写 `DOMAIN_FINANCE` 等变量名；
3. 记录数据库或索引版本、执行日期、命中数和语言；
4. 导出 RIS、BibTeX 或 CSV 到 Git 忽略目录，并记录文件名与 SHA-256；
5. 在 `seed_set.csv` 填写每篇种子的实际命中来源；
6. 修改查询时新增 `v2` 行，旧行标为 `superseded`，不得覆盖。

### 数据库执行注意

| 数据库 | 记录重点 | 常见风险 |
|---|---|---|
| ACL Anthology | 搜索词、年份、结果页或导出方式 | 页面检索能力有限，必要时结合正式元数据索引 |
| PubMed | 完整字段标签、日期过滤和查询历史编号 | MeSH与自由词覆盖不同 |
| Web of Science/Scopus | 检索字段、索引范围、文献类型和机构订阅状态 | 同一查询在不同订阅范围结果不同 |
| IEEE/ACM | 元数据字段、内容类型和会议/期刊过滤 | 全文检索可能造成大量噪声 |
| Semantic Scholar/Crossref | API或页面参数、分页和结果上限 | 适合补充元数据，不替代领域数据库 |
| CNKI/万方 | 检索字段、同义词、学科与来源类别 | 中文分词和机构权限影响结果 |

无法合法导出全文时，只保存元数据和访问状态，不使用截图或手工转录来伪装完整数据导出。

## 7. 查询结果验收

试检索只有同时满足以下条件才通过：

- 18篇种子在声明的数据库组合中全部命中；
- 每个RQ至少覆盖一个同行评审主来源和一个综合索引或官方规范来源；
- 中文与英文查询均已执行；
- 每条日志有执行人、日期、命中数、导出文件和哈希；
- 随机抽查20条结果，主题相关性足以进入标题摘要筛选。
