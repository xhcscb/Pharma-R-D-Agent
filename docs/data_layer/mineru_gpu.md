# MinerU GPU 解析服务

## 本机 RTX 3050（4 GB）

MinerU 与主应用使用独立环境。主应用监听 `127.0.0.1:8000`，MinerU 只监听
`127.0.0.1:18010`，两者不要使用同一个端口。

首次安装（需要联网，模型文件会占用数 GB）：

```powershell
Set-Location <项目的 github 目录>
powershell -ExecutionPolicy Bypass -File scripts\setup_mineru_gpu.ps1
```

启动解析服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_mineru_gpu.ps1
```

另开一个终端验证。只有 `cuda_available=true`、显卡名称正确且服务状态为 200，
才算 GPU 服务可用：

```powershell
Invoke-RestMethod http://127.0.0.1:18010/gpu-health
Invoke-RestMethod http://127.0.0.1:18010/health
```

然后启动主应用。若 8000 已被占用，先用 `Get-NetTCPConnection -LocalPort 8000`
查明旧进程，关闭旧实例，或临时把主应用改到 8001。修改 `.env` 后必须停止并
重新启动 Uvicorn；运行中的进程不会自动重新读取环境变量。

```powershell
.venv\Scripts\uvicorn.exe pharma_data.api.app:app --host 127.0.0.1 --port 8000
```

本机 GPU 模式的常驻 worker 也必须在 Windows 主机运行，因为 MinerU 只绑定回环
地址；不要为了让 Docker 访问而把 18010 暴露到 `0.0.0.0`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_local_worker.ps1
```

`compose.yaml` 中的容器 worker 使用独立 `remote-worker` profile，仅适用于已配置
HTTPS、API 鉴权和白名单的团队私有远程 GPU：

```powershell
docker compose --profile remote-worker up -d worker
```

项目客户端固定请求 `content_list.json`、`middle.json` 和模型输出，并将原始响应
按输入哈希和输出哈希归档到 `data/parser_outputs/mineru/`。

当前本机基线固定为 MinerU `3.4.0`、CUDA 版 PyTorch、`pdftext==0.6.3`。每次只
提交 1 页（`MINERU_PAGE_BATCH_SIZE=1`）：这是因为三份财务报告的整篇解析实测会
出现跨页表格漂移，单页解析可显著提高数字 token 对齐率。不得随意升级解析器或
依赖版本；升级必须以新的解析运行重跑并比较质量门，不能覆盖历史输出。

主应用侧关键配置如下：

```dotenv
MINERU_ENABLED=true
MINERU_REQUIRED=true
MINERU_EXECUTION_MODE=local
MINERU_API_URL=http://127.0.0.1:18010
MINERU_BACKEND=pipeline
MINERU_DEVICE=cuda
MINERU_PAGE_BATCH_SIZE=1
MINERU_MAX_CONCURRENCY=1
MINERU_ALLOWED_ACCESS_CLASSES=public,restricted
MINERU_RETURN_IMAGES=true
VISUAL_SEMANTICS_ENABLED=true
VISUAL_SEMANTICS_REQUIRED=true
VISUAL_SEMANTICS_MIN_CONFIDENCE=0.85
```

`MINERU_RETURN_IMAGES` 不得在正式质量模式关闭。MinerU 返回的表格/图表/图片裁剪会
解码到解析输出目录，记录 SHA-256、MIME、像素尺寸和原始 `img_path`。数据库中的
视觉主张引用该资产、页码和 PDF 坐标，不把一段 OCR 文本当作完整图表证据。

## 图表与图片语义

解析分为三个不同层次，不能混为一谈：

1. MinerU 负责页面布局、OCR、表格网格以及图/图表区域和裁剪图；
2. 可验证视觉分析器负责颜色、形状、终点、坐标轴/阶段列之间的几何关系；
3. 实体与关系层把已验证观察转换成带视觉证据的候选主张。

临床管线矩阵已经实现确定性分析：按表格行继承药品、靶点、适应症和地区，检测每条
有色进度条，将条形最右端映射到 I/II/III/NDA 列，并保存颜色、条形像素框、目标列
像素框、推导方法和置信度。颜色不被硬编码成国家；国家/地区来自条内文字或表格结构，
颜色只作为独立视觉属性保留。

任何行数与条数不一致、条形起点不齐、终点远离阶段边界、缺失裁剪图或低于阈值的
页面都会产生视觉硬门复核项。其他尚无专用验证器的复杂图表和实质性图片也会进入
`visual_semantics_missing` 复核，而不会静默进入正式推理。

## CPU OOM 降级

GPU OOM 不会被当成成功。若要自动降级，应另启一个 `MINERU_DEVICE_MODE=cpu` 的
同版本 pipeline 服务，并将其地址写入 `.env` 的 `MINERU_CPU_API_URL`。系统仅在
错误明确包含 out-of-memory 时重试，并记录原始失败原因和 CPU 节点。

## 团队私有 GPU

高显存节点可运行 `vlm-http-client` 或 `hybrid-http-client`。客户端只需修改：

```dotenv
MINERU_EXECUTION_MODE=remote
MINERU_API_URL=https://mineru.internal.example
MINERU_BACKEND=hybrid-http-client
MINERU_SERVER_URL=https://model.internal.example/v1
MINERU_TRUSTED_HOSTS=mineru.internal.example
MINERU_API_KEY=<仅保存在部署环境中>
```

远程地址必须使用 HTTPS、配置 bearer token，并显式加入白名单。受限报告禁止发送
到公共端点。数据库只保存节点、模型版本、参数和输出哈希，不保存 token。新增 GPU
后端不改变 `/v2/reasoning/context` 契约。

## 官方来源与全量重跑

三份样本的交易所/巨潮 PDF 必须先逐字节 SHA-256 核验，再更新正式 URL 和发布日期：

```powershell
.venv\Scripts\python.exe scripts\apply_verified_report_sources.py --dry-run
.venv\Scripts\python.exe scripts\apply_verified_report_sources.py
```

服务健康和单页冒烟通过后，使用唯一运行标签重跑当前文档；每个新运行都有独立元素
定位，旧解析只保留审计用途：

```powershell
.venv\Scripts\python.exe scripts\reprocess_current_documents.py `
  --run-tag mineru-page-v2-20260824 --force --stop-on-error
.venv\Scripts\python.exe scripts\rebuild_active_facts.py
.venv\Scripts\python.exe scripts\create_current_snapshots.py
.venv\Scripts\python.exe scripts\audit_data_layer_quality.py
```

## 质量边界

MinerU 是 PDF 主解析器，PP-StructureV3 只补救未通过硬门的页，PyMuPDF 只核对
页数、页面尺寸、原生字符、数字 token 和坐标。任何页面覆盖、坐标、数字、表格
网格、重复区域、视觉资产或视觉语义硬门失败都会进入 `parse_review_item`，不会静默
进入正式推理。
