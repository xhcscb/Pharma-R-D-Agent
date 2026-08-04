# 第一阶段协作规范

## 分支与提交

- 稳定分支：`main`
- 第一阶段分支：`research/phase1-literature`
- 一次提交只处理一种研究产物，使用 Conventional Commits 风格。
- 阶段验收后合并到 `main` 并创建 `research-phase1-v1.0` 标签。

建议提交前缀：

```text
docs(protocol): ...
research(search): ...
research(screen): ...
research(evidence): ...
docs(cards): ...
docs(synthesis): ...
docs(decisions): ...
```

## 双人复核

交叉复核采用：`成员1 → 成员2 → 成员3 → 成员4 → 成员5 → 成员1`。

- 标题/摘要筛选：至少 25% 随机双人复核；
- 全文纳入/排除：100% 双人复核；
- 15 篇锚点论文：100% 双人深读复核；
- 分歧：第三名成员裁决，并在筛选表中记录理由。

## 文献数据约定

- 每篇论文只允许一个 `literature_id`；
- 正式会议/期刊版本优先于预印本；
- 论文可以属于多个主题簇，使用分号分隔；
- `quality_score` 只能在全文核验后填写；
- 任何结果数字必须在卡片中记录页码、表格或章节位置；
- LLM 只能生成工作草稿，不能把未核验内容标记为 `verified`。

## 版权与安全

- 禁止提交付费或未授权 PDF；
- 禁止绕过登录、付费墙、验证码或访问频率限制；
- 引用保留 DOI、ACL Anthology、PubMed、arXiv 或官方页面链接；
- 若全文不可访问，设置 `access_status=metadata_only`，不得猜测正文内容。
