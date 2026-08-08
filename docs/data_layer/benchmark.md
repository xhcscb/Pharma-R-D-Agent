# Gold 基准格式与质量门

运行：

~~~powershell
datactl eval benchmark path/to/gold-benchmark.json
~~~

Gold JSON 包含以下数组：

`native_pdf_text`、`scanned_pdf_text`、`tables`、`entities`、`entity_links`、`relations`、`deduplicated_relations`、`dates`、`units`、`conflicts`、`projection_ids`。

## 字段约定

- 文本任务：`{"gold": "...", "predicted": "..."}`；
- 集合任务：`gold` 和 `predicted` 均为数组；
- 实体链接、日期、单位和投影 ID：`gold` 与 `predicted` 为标量；
- 表格任务：`gold` 与 `predicted` 保存 HTML。

## 发布阈值

| 指标 | 阈值 |
|---|---:|
| 原生 PDF 字符错误率 | ≤ 0.01 |
| 扫描 PDF 字符错误率 | ≤ 0.05 |
| 表格结构 TEDS | ≥ 0.85 |
| 核心实体微平均 F1 | ≥ 0.90 |
| 实体链接准确率 | ≥ 0.90 |
| 关系抽取微平均 F1 | ≥ 0.85 |
| 关系去重精确率 | ≥ 0.98 |
| 日期规范化准确率 | ≥ 0.95 |
| 单位规范化准确率 | ≥ 0.98 |
| 冲突检测召回率 | ≥ 0.90 |
| 主库与投影 ID 一致率 | 1.00 |

评测器输出字符错误率、确定性 DOM 树表格相似度、微平均 Precision/Recall/F1、配对准确率、冲突召回率和投影 ID 一致率。任一已声明发布门不通过时，命令以非零状态退出。

空基准只能验证 Schema 和命令是否可运行，不能证明经验质量达标。正式发布证据必须来自人工复核且许可清晰的 Gold 标注。
