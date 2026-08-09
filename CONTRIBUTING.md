# 团队协作规范

本规范同时适用于数据层工程、说明文档和论文调研。提交前先确认改动属于哪个模块，不在同一提交中混入无关修改。

## 1. 分支与提交

远程仓库长期保留三条分支：

| 分支 | 用途 | 合并规则 |
|---|---|---|
| `main` | 稳定、可复现的项目基线 | 只接受通过检查的 Pull Request；禁止强制推送 |
| `develop` | 数据层和 Agent 功能集成 | `feat/*`、`fix/*`、`docs/*` 先合入此分支；阶段稳定后再合入 `main` |
| `research/phase1-literature` | 第一阶段检索、筛选、深读和研究设计冻结 | 研究产物在本分支协作，达到阶段质量门后合入 `main` |

短期分支命名：

- 功能：`feat/<简短主题>`；
- 修复：`fix/<简短主题>`；
- 文档：`docs/<简短主题>`；
- 自动化协作：`agent/<简短主题>`。

短期分支通过 Pull Request 合并后删除，不在远程长期保留。不得改写已共享分支的提交历史；不得向 `main`、`develop` 或 `research/phase1-literature` 强制推送。

推荐流程：

1. 工程任务从 `develop` 创建短期分支，完成后 Pull Request 回 `develop`；
2. 论文调研直接从 `research/phase1-literature` 创建短期分支，复核后合回研究分支；
3. 阶段验收通过后，由负责人发起 `develop → main` 或 `research/phase1-literature → main` 的 Pull Request；
4. `main` 上只保留已复核提交，不直接进行日常开发。

提交信息使用 Conventional Commits：

~~~text
docs(research): clarify screening workflow
research(search): record pilot query results
research(evidence): add verified paper card
feat(data): add mainland source adapter
fix(parser): preserve table footnote evidence
test(data): cover conflict grouping
~~~

阶段标签只能在对应验收门全部通过后创建：

- 论文调研：`research-phase1-v1.0`；
- 数据层：`data-layer-v1.0.0`。

## 2. 论文调研提交

每篇论文只允许一个 `literature_id`。正式会议或期刊版本优先于预印本；不同主题用英文分号 `;` 分隔。

固定复核链为：`成员1 → 成员2 → 成员3 → 成员4 → 成员5 → 成员1`。

- 标题/摘要筛选：至少 25% 随机双人复核；
- 全文纳入/排除：100% 双人独立判断；
- 15 篇锚点：100% 双人深读复核；
- 分歧：由第三名成员裁决并记录原因；
- `quality_score` 只能在全文评价后填写；
- 实验数字必须记录页码、表格、图或章节；
- LLM 可起草，但未核验内容不得标记为 `full_text_verified`。

操作顺序、状态和表格字段见[论文调研模块说明](research/README.md)。

## 3. 数据层提交

- 解析、抽取和清洗结果必须保留来源、版本和证据位置；
- 新 Connector 必须声明 `license_status`、`access_class`、域名白名单和失败策略；
- 解析器和抽取器不得直接写 Neo4j、Milvus、TimescaleDB 或 Elasticsearch；
- 模型输出只能进入 Candidate 或 Silver；Gold 必须由人工确认；
- Schema 变化必须附带 Alembic 迁移、契约测试和文档更新；
- 新接口、CLI 命令或环境变量必须同步修改相应说明文档。

## 4. 文档规范

- 说明文档使用简体中文；代码名、标准名和字段名可保留英文；
- 命令必须从仓库根目录可执行，并说明是在本机还是容器中运行；
- 本机地址使用 `localhost` 或 SQLite；Compose 服务名只用于容器内部；
- 计划、模板、演示结果和已验收结论必须明确区分；
- 新增或移动 Markdown 文件后运行 `python scripts/validate_docs.py`。

## 5. 提交前检查

~~~powershell
python scripts/validate_docs.py
./scripts/validate_phase1.ps1
uv run pytest -q
uv run ruff check .
uv run mypy PATH_TO_CHANGED_MODULES
~~~

若只修改文档，至少运行前两项；若修改代码，运行全部相关测试。全量严格类型检查的现有问题见[数据层已知限制](docs/data_layer/known_limitations.md)，不得因已有债务跳过对改动模块的定向检查。

## 6. 版权与安全

- 禁止提交付费或未授权 PDF、来源不明录音和数据库导出全文；
- 禁止绕过登录、付费墙、验证码、脚本校验或访问频率限制；
- 若论文全文不可访问，记录为 `metadata_only`，不得推测正文；
- 清单不得包含密码、Cookie、Token、身份证明或个人敏感信息；
- 公开快照只能包含明确允许公开再分发的内容。
