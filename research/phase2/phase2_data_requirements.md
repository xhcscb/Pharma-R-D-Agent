# 第二阶段数据层输入要求（第一阶段待冻结）

本文是第一阶段向第二阶段的接口，不代表数据层已开始建设。

## 1. 预期语料范围

- 中国优先：A/H股医药公司公告、CDE公开信息、中国临床试验信息；
- 国际补充：ClinicalTrials.gov、公司公开披露；
- 券商研报：只处理公开或团队已获授权材料；
- 初始主题：PD-1/PD-L1、ADC、GLP-1；最终由D06冻结。

## 2. Gold PDF工作假设

- 30份精标PDF；
- 150–300份压力测试语料；
- 覆盖原生文本、扫描件、双栏、跨页表格、复杂图表、脚注、混合中英文和低质量页面；
- 每份文档记录来源、许可、哈希、发布日期、抓取日期、语言、页数和难度标签。

## 3. 解析评测接口

至少分项评价：

- 文本：字符/词错误、阅读顺序、标题层级；
- 表格：结构、单元格、跨页连接、单位和脚注绑定；
- 图表：图表类型、轴、图例、数据系列、数值和图注；
- 证据定位：页码、边界框、段落/表格/图形ID；
- 端到端：解析结果对Compare/Summarize任务的影响。

## 4. 数据契约候选

每个证据单元至少需要：

```text
document_id
source_id
license_status
published_at
retrieved_at
page_number
element_id
element_type
bbox
reading_order
text
table_or_chart_semantics
unit
footnote_links
parser_name
parser_version
confidence
content_hash
```

## 5. 第二阶段启动门

- D02、D04、D05、D06、D07、D10至少达到 `frozen` 或 `experiment_required`；
- Gold文档许可状态全部明确；
- 解析基线、分项指标、标注指南和误差分类完整；
- 任何待实验决策都具备明确对照和判定阈值；
- 第一阶段验证脚本通过，阶段标签已创建。
