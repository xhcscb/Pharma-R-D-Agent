# 数据层快速启动

本指南用于在本地快速验证“导入—解析—抽取—清洗—复核—投影”链路。完整生产操作见[数据层操作手册](operations.md)。

## 1. 前置条件

- Docker Desktop 已启动；
- Git 已安装；
- 建议可用内存不少于 16 GB；
- 当前目录为仓库根目录；
- 待导入数据公开或已获授权。

## 2. 创建配置

~~~powershell
Copy-Item .env.example .env
~~~

编辑 `.env`，至少替换：

- `INTERNAL_API_KEY`；
- `PROJECT_CONTACT_EMAIL`：团队来源管理联系人，可选但建议填写。

`.env` 已被忽略，不要提交。

默认配置同时支持两种运行方式：

- Windows 本机运行 `.venv\Scripts\datactl.exe`：使用 `DATABASE_URL=sqlite:///./data/runtime/pharma.db`；
- Docker 运行：Compose 自动使用 `CONTAINER_DATABASE_URL`，容器内数据库主机为 `postgres`。

不要把本机 `DATABASE_URL` 写成 `@postgres:5432`。`postgres` 只能在 Compose 网络内部解析；本机若要连接容器 PostgreSQL，应使用 `@localhost:5432`。

本地快速验证可暂时使用 Compose 示例口令。共享部署前必须同时修改 `compose.yaml` 的服务端口令和 `.env` 的连接口令，不能只改一侧。

## 3. 检查并启动核心服务

先检查本机 CLI 数据库：

~~~powershell
.venv\Scripts\datactl.exe db doctor
.venv\Scripts\datactl.exe db migrate
~~~

~~~powershell
docker compose --profile core config --quiet
docker compose --profile core up -d --build
docker compose --profile core exec api alembic upgrade head
docker compose --profile core ps
~~~

健康检查：

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/health
~~~

返回健康状态后，可打开 `http://127.0.0.1:8000/docs`。

## 4. 先检查权威来源

~~~powershell
.venv\Scripts\datactl.exe source list
.venv\Scripts\datactl.exe source doctor
.venv\Scripts\datactl.exe source doctor --live --source-id cninfo_disclosures
~~~

运行真实小样本演示：

~~~powershell
.venv\Scripts\datactl.exe source demo
~~~

演示结果见 `data/demo/china-mainland-demo-report.json`。完整说明见[权威数据源调试与演示](authoritative_source_demo.md)。

演示只使用国家药监局、国家医保局和巨潮资讯等中国大陆官方来源。药物临床试验平台、CDE、ChiCTR 等受访问保护的来源采用人工导出清单，不绕过校验。

## 5. 导入一份合成新闻

仓库中的新闻示例只用于验证流程：

~~~powershell
docker compose --profile core exec api datactl ingest manifest manifests/examples/news.csv --source-type news
docker compose --profile core logs --tail 100 worker
~~~

查看最近文档：

~~~powershell
docker compose --profile core exec postgres psql -U pharma -d pharma -c "SELECT id,title,current_version_id FROM document ORDER BY created_at DESC LIMIT 10;"
~~~

将查询得到的文档 ID 代入：

~~~powershell
docker compose --profile core exec api datactl pipeline run DOCUMENT_ID
~~~

如果 Worker 已自动完成任务，重复运行会依据幂等键复用结果，不应生成重复事实。

## 6. 查看待复核结果

~~~powershell
docker compose --profile core exec api datactl review list --limit 20
~~~

批准前必须核对原始证据。示例：

~~~powershell
docker compose --profile core exec api datactl review approve assertion ASSERTION_ID --reviewer "测试人员" --rationale "已核对合成新闻原文和证据位置"
~~~

## 7. 启动并验证全部投影

~~~powershell
docker compose --profile full up -d
docker compose --profile full ps
docker compose --profile full exec api datactl projection dispatch --limit 100
~~~

如需单独重建：

~~~powershell
docker compose --profile full exec api datactl projection rebuild neo4j
docker compose --profile full exec api datactl projection rebuild milvus
docker compose --profile full exec api datactl projection rebuild timescale
docker compose --profile full exec api datactl projection rebuild elasticsearch
~~~

## 8. 执行本地质量检查

如果本机已安装 Python 3.12 和 uv：

~~~powershell
uv sync --extra dev
uv run alembic upgrade head
uv run pytest -q
uv run datactl eval all
~~~

无 Python 环境时，至少执行：

~~~powershell
docker compose --profile full config --quiet
docker compose --profile full exec api datactl eval all
~~~

## 9. 停止

~~~powershell
docker compose --profile full down
~~~

这会停止容器但保留数据卷。不要把 `-v` 加到日常停止命令中。

## 下一步

- 导入真实数据前阅读[数据清单编写指南](manifest_guide.md)；
- 执行团队日常任务时使用[数据层操作手册](operations.md)；
- 备份、恢复或处理故障时使用[运维与恢复手册](maintenance_and_recovery.md)。
