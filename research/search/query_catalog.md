# 检索式目录 v1.0

## 1. 使用方法

下列是与数据库无关的标准概念块。执行人必须根据数据库语法改写，并把“实际执行式”写入 `search_log.csv`。不得只记录本文件中的抽象模板。

## 2. 概念块

```text
DOMAIN_FINANCE =
(financial OR finance OR investment OR "equity research" OR "analyst report"
 OR "securities research" OR 医药投研 OR 券商研报 OR 投资研究)

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
