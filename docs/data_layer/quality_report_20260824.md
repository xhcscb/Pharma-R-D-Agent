# 数据层质量改造报告

生成时间：`2026-08-24T15:11:27.140104+00:00`

## 结论

当前结论为 **质量优先工程基线 / 内部试运行**。正式研究目标仍未通过；人工 Gold、G3 指标和主张审批不得由自动检查替代。

## 当前活动数据

- 数据库完整性：`not_applicable`；迁移：`0004_fact_evidence_integrity`
- 文档：3；页面：418/418 (100.00%)
- 元素：5887；字符 span：7671；表格单元格：24088（数字 6530）
- 活动主张：265；活动事实键：265；重复键：0
- 活动事实冲突组：3
- 指标观测：137；活动证据：299；定位完整率：100.00%
- 已批准主张：0；开放解析硬门：354；快照：2
- MinerU GPU：ready；设备：NVIDIA GeForce RTX 3050 Laptop GPU；累计服务失败：0
- 投影 ID 验收：passed

## 正式目标阻断项

- `parse_hard_gate_review_open`
- `approved_claims_missing`
- `active_fact_conflicts_open`
- `human_gold_missing`
- `g3_gold_gate_not_evaluated`

## 改造前基线

```json
{
  "elements": 14187,
  "titles": 9274,
  "assertions": 255,
  "approx_distinct_fact_keys": 83,
  "approved_assertions": 0,
  "metric_observations": 0,
  "projection_events": 0,
  "dataset_snapshots": 0,
  "evidence_with_character_locator": 0
}
```

完整机器可读结果见同名 JSON。
