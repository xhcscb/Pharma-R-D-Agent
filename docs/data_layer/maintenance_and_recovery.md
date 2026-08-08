# 数据层运维与恢复手册

本文用于日常监控、备份、故障处置和恢复。覆盖恢复、删除数据卷和生产迁移属于高风险操作，执行前必须确认目标环境、备份可用性和负责人批准。

## 1. 日常健康检查

~~~powershell
docker compose --profile full ps
Invoke-RestMethod http://127.0.0.1:8000/health
docker compose --profile core logs --tail 100 api
docker compose --profile core logs --tail 100 worker
~~~

每天至少检查：

- API 和 Worker 是否运行；
- PostgreSQL 是否健康；
- `FAILED_RETRYABLE`、`FAILED_FINAL`、`QUARANTINED` 数量；
- Outbox 未发布数量和最后错误；
- 对象存储、数据库卷和磁盘剩余空间；
- 最近一次备份时间和校验结果。

## 2. PostgreSQL 备份

先创建仓库外或已忽略的备份目录。不要把包含受限内容的备份提交 Git。

~~~powershell
New-Item -ItemType Directory -Force backups
docker compose --profile core exec postgres pg_dump -U pharma -d pharma -Fc -f /tmp/pharma.dump
docker compose --profile core cp postgres:/tmp/pharma.dump ./backups/pharma.dump
Get-FileHash ./backups/pharma.dump -Algorithm SHA256
~~~

记录备份时间、提交号、Schema 版本、文件哈希和执行人。重要批次导入前后各备份一次。

## 3. PostgreSQL 恢复

恢复会覆盖现有事实数据，必须先停 Worker，确认数据库名称并再次备份当前状态：

~~~powershell
docker compose --profile core stop worker
docker compose --profile core cp ./backups/pharma.dump postgres:/tmp/pharma.dump
docker compose --profile core exec postgres pg_restore -U pharma -d pharma --clean --if-exists /tmp/pharma.dump
docker compose --profile core start worker
~~~

恢复后执行：

~~~powershell
docker compose --profile core exec api alembic upgrade head
docker compose --profile core exec api datactl eval all
~~~

再检查文档、主张、复核和 Outbox 数量。未经验证的备份不能作为唯一恢复点。

## 4. 原始对象存储

`data/objects` 保存内容寻址的原始文件。备份时必须：

- 保留目录结构和文件名；
- 保存总体文件数、总大小和抽样哈希；
- 使用与事实库同一批次的时间点；
- 对受限材料使用加密存储和访问控制；
- 定期执行恢复演练。

只恢复 PostgreSQL 而缺少对应对象文件，会导致证据链不完整。

## 5. 任务失败恢复

查询失败任务：

~~~powershell
docker compose --profile core exec postgres psql -U pharma -d pharma -c "SELECT id,status,attempts,last_error FROM processing_job WHERE status IN ('FAILED_RETRYABLE','FAILED_FINAL') ORDER BY updated_at DESC;"
~~~

处置顺序：

1. 检查许可和来源是否有效；
2. 检查原始文件是否存在且哈希一致；
3. 检查解析依赖、模型和配置；
4. 修复根因；
5. 对 `FAILED_RETRYABLE` 执行一次受控重试；
6. 抽查输出和证据；
7. 记录故障原因与处理人。

~~~powershell
docker compose --profile core exec api datactl pipeline retry JOB_ID
~~~

达到上限的 `FAILED_FINAL` 不应通过循环重试掩盖问题。

## 6. Outbox 与投影恢复

投影不可替代统一事实库。Neo4j、Milvus、TimescaleDB 或 Elasticsearch 损坏时：

1. 停止对应投影写入；
2. 验证 PostgreSQL 和对象存储完整；
3. 恢复目标服务；
4. 重放未发布 Outbox；
5. 必要时从主库完整重建；
6. 检查投影检查点和 ID 一致性。

~~~powershell
docker compose --profile full exec api datactl projection dispatch --limit 1000
docker compose --profile full exec api datactl projection rebuild neo4j
docker compose --profile full exec api datactl projection rebuild milvus
docker compose --profile full exec api datactl projection rebuild timescale
docker compose --profile full exec api datactl projection rebuild elasticsearch
~~~

重建后运行 `datactl eval all`，并使用 Gold 数据验证投影 ID 一致率为 100%。

## 7. 数据库迁移

迁移前：

- 备份 PostgreSQL；
- 保存当前 Git 提交和 Alembic 版本；
- 在测试环境运行迁移和回归测试；
- 暂停 Worker；
- 预留回滚窗口。

执行：

~~~powershell
docker compose --profile core stop worker
docker compose --profile core exec api alembic upgrade head
docker compose --profile core start worker
~~~

不要在生产环境直接执行未经测试的降级迁移。需要回滚时依据具体 Alembic 修订和备份制定恢复步骤。

## 8. 容量与性能

- 原始 PDF、音视频和 OCR 中间结果增长最快，应单独监控；
- Elasticsearch 和 Milvus 的索引可重建，但重建耗时和资源占用较高；
- 完整 Profile 建议至少 16 GB 内存；
- 笔记本可分别启动 `graph`、`vector`、`timeseries` 和 `search`；
- 批量导入使用可审计的小批次，避免一次导入无法人工复核的大量数据；
- 不通过删除原始证据换取空间。

## 9. 安全事件

出现以下情况时立即暂停导入和公开导出：

- 受限内容出现在公开查询或快照；
- 许可状态不明的数据被下载；
- 内部密钥或数据库密码泄露；
- 文档哈希异常或来源文件被替换；
- Gold 主张缺少证据；
- 审计日志出现未授权操作。

保留日志和证据，轮换密钥，确定影响范围，修复后执行公开快照泄漏审计。

## 10. 停机与升级

正常停机：

~~~powershell
docker compose --profile full down
~~~

升级流程：

1. 备份主库与对象存储；
2. 记录当前镜像和提交；
3. 在测试环境验证 Compose、迁移和回归测试；
4. 停 Worker；
5. 更新服务并迁移；
6. 启动 Worker；
7. 执行健康检查、质量检查和抽样查询。

`docker compose down -v` 会删除数据库卷。除非明确重建测试环境、已核对目录且备份可恢复，否则不得执行。
