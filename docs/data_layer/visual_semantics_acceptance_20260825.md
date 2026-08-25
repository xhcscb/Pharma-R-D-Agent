# 视觉语义专项复核（2026-08-24）

## 结论

改造前的数据层不能完整理解临床管线矩阵。它能识别药品、适应症、地区和表格网格，
但有色进度条跨单元格表达的最远阶段会丢失。改造前的活动运行中，`SHR-1703`
所在第 43 页的阶段单元格没有形成可审计阶段事实。

改造后，MinerU 返回的图片资产会被解码归档并记录哈希。临床管线专用分析器将表格
行与有色条逐行配对，把条形最右端映射到 I/II/III/NDA 列，同时保留地区、颜色、
条形像素框、阶段列像素框、推导方法和置信度。无法验证的视觉元素进入硬复核队列。

## 真实样例验证

复核对象为三份当前报告中恒瑞医药管线页的 MinerU 裁剪图。实际检测到 24 条有色
进度条，与 24 个有效管线行一一对应；专项分析状态为 `verified`，无行数不匹配、
起点不齐或终点歧义。数据库实跑中，`SHR-1703` 两条观察置信度均为 `0.967971`，
`HRS-9231` 澳洲 I 期观察置信度为 `0.969116`。

代表性结果：

| 药品/代号 | 适应症 | 地区 | 几何推导阶段 | 颜色属性 |
|---|---|---|---|---|
| SHR-1703 | 嗜酸性肉芽肿性多血管炎 | 中国 | III期 | 蓝色系 |
| SHR-1905 | 特应性皮炎 | 中国 | II期 | 蓝色系 |
| SHR-1905 | 慢性阻塞性肺疾病 | 中国 | I期 | 蓝色系 |
| HRS-9231 | MRI检测 | 澳洲 | I期 | 红色系 |
| 阿托品滴眼液 | 延缓儿童近视 | 中国 | NDA | 蓝色系 |
| SHR7280 | 辅助生殖 | 中国 | NDA | 蓝色系 |

颜色不用于硬编码国家。地区来自条内 OCR/表格行结构，颜色作为独立视觉证据保存。

## 当前运行态

- 三份当前报告：418/418 页已用新链路重处理；
- MinerU GPU：3.4.0，RTX 3050 Laptop GPU，419 个任务完成、0 失败；
- 活动解析：5,887 个元素，其中 MinerU 5,840 个、视觉结构记录 47 个；
- 已验证两张临床管线图：第 35 页 23 条、第 43 页 24 条视觉观察；
- 物质性视觉元素：要求 13 个、已验证 2 个、覆盖率 `0.153846`，其余 11 个被阻断；
- 质量阻断：354 个开放硬门复核项、3 个活动事实冲突、0 条人工批准事实，Gold 未评估；
- 正式状态：`engineering_baseline_ready=true`，`formal_reasoning_ready=false`；
- 代码回归：74 项完整测试通过；新增 3 项视觉专项测试；
- Ruff：通过；
- 改动路径严格 mypy：通过；
- 真实裁剪图专项：24/24 行通过；
- 主 API 容器已重建，`127.0.0.1:8000/health` 返回版本 `0.3.0`；
- `/v2/reasoning/context` 已返回视觉覆盖率、视觉证据定位和
  `visual_semantics_incomplete` 阻断原因。

因此，代码能力和当前数据库已经补齐该类临床管线图，但任意图片的完整理解和正式
推理放行尚未完成。未验证的图片没有被静默当作已理解。

## 后续刷新与验收

以下命令已于本次验收执行；新增报告或升级解析器后再重复运行。先启动 GPU 服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_mineru_gpu.ps1
```

另开终端确认 GPU 后端：

```powershell
Invoke-RestMethod http://127.0.0.1:18010/gpu-health
Invoke-RestMethod http://127.0.0.1:18010/health
```

`.env` 至少保持：

```dotenv
MINERU_RETURN_IMAGES=true
VISUAL_SEMANTICS_ENABLED=true
VISUAL_SEMANTICS_REQUIRED=true
VISUAL_SEMANTICS_MIN_CONFIDENCE=0.85
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_local_worker.ps1
```

用新的唯一标签重跑并重建活动事实：

```powershell
.venv\Scripts\python.exe scripts\reprocess_current_documents.py `
  --run-tag visual-semantics-v1-20260825 --force --stop-on-error
.venv\Scripts\python.exe scripts\rebuild_active_facts.py
.venv\Scripts\python.exe scripts\audit_data_layer_quality.py
```

正式放行前仍必须确认 `/v2/reasoning/context` 中：

- `readiness.visual_semantic_required_count` 等于
  `readiness.visual_semantic_verified_count`；
- `readiness.blockers` 不含 `visual_semantics_incomplete`；
- 管线 `HAS_STAGE` 主张的 `evidence[].visual_context` 含资产 SHA-256、条形框和阶段列框；
- 所有 `visual_semantics_missing`、`visual_asset_missing`、
  `visual_semantics_low_confidence` 复核项均已处理。

其他任意复杂图片仍不能宣称“完美理解”。应按图表类型增加专用验证器或受控私有
多模态模型，并以人工 Gold 集验收；没有通过验证的结果继续阻断正式推理。
