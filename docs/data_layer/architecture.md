# 数据层架构

PostgreSQL 统一事实库是唯一数据真相来源。原始文件按内容寻址并保持不可变；解析、实体抽取、关系抽取、清洗、复核和投影均为可追踪、可重放的受控步骤。

## 处理流程

1. 数据源适配器发现记录，只抓取公开或已获授权的内容。
2. 对象存储按 SHA-256 路径保存不可变原始字节。
3. DocParser 生成带版本的文档元素或带时间戳的语音片段。
4. EntityExtract 生成实体提及，并链接到规范实体。
5. RelationExtract 生成有证据支持的结构化主张。
6. DataClean 规范化字段、去重主张并记录冲突。
7. 人工复核批准、拒绝或退回主张。
8. Outbox 只将已批准事实投影到 Neo4j、Milvus、TimescaleDB 和 Elasticsearch。

解析器和抽取器不得直接写入任何投影数据库。

## 流水线状态

正常路径：

`DISCOVERED → FETCHED → PARSED → ENTITY_EXTRACTED → RELATION_EXTRACTED → CLEANED → NEEDS_REVIEW → APPROVED → PROJECTED`

异常状态：

- `QUARANTINED`：许可、来源或文件异常，停止后续处理；
- `FAILED_RETRYABLE`：可在修复后重试；
- `FAILED_FINAL`：达到重试上限，需要人工处置。

Worker 使用 PostgreSQL 的 `FOR UPDATE SKIP LOCKED` 领取任务。幂等键由文档版本哈希、步骤、Schema 版本、组件版本和配置哈希共同生成。同一输入和配置重复运行时不会重复造数。

## 文档解析

路由器支持 PDF、HTML、JSON、CSV、XLSX、XBRL/XML、图片、纯文本和音视频。授权行情的 JSON/CSV/XLSX 由专用解析器规范为逐证券、逐交易日证据元素。PDF 质量模式以 MinerU 为主解析器，保存内容列表、中间 JSON、模型输出以及表格/图表/图片裁剪；PyMuPDF 只用于页数、尺寸、原生字符、数字 token 和坐标核验，PP-StructureV3 仅补救失败页。

视觉内容单独经过“资产归档 → 类型识别 → 专用几何分析 → 语义观察 → 实体/关系”链路。临床管线矩阵会把有色条终点映射到阶段列，并把颜色、地区、条形框、阶段列框和推导方法写入证据。没有专用验证器或无法通过几何一致性检查的图表/图片进入硬复核队列，不会因为 OCR 成功而被标记为已理解。

每个文档元素都保存解析器与版本、置信度、页码、坐标、阅读顺序、内容哈希和结构化载荷。不可靠的图表数值必须保留为 `null`，不能猜测补齐。

音视频先由 FFmpeg 标准化为单声道 16 kHz PCM，再由 faster-whisper 完成 VAD、转写和词级时间对齐，并可选执行说话人分离。说话人身份不能只根据声纹聚类确定，必须有官方名单、主持人介绍或人工确认。

## 四类投影

- Neo4j：已批准实体、关系、证据追溯边和临床监管时间属性；
- Milvus：`document_chunks`、`entity_descriptions`、`assertion_evidence`；
- TimescaleDB：市场、财务、临床、监管、新闻和主张版本事件；
- Elasticsearch：文档、文档元素、新闻和电话会议发言全文。

已批准事实只能通过 Outbox 离开 PostgreSQL。所有可检索记录都必须带访问权限字段。

## 延伸阅读

- [统一数据模型](data_model.md)
- [数据治理](governance.md)
- [数据层操作手册](operations.md)
