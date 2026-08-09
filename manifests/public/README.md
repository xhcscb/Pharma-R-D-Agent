# 公开数据清单

本目录只存放允许公开提交的来源元数据、官方 URL 和团队原创字段，不存放原始全文。

- 不得提交受版权保护的券商研报 PDF；
- 不得提交私人或未授权的电话会议录音；
- 必须明确填写 `license_status` 和 `access_class`；
- `public_access` 只表示公众可访问，不等于全文可以公开再分发；
- 可进入公开数据集快照的正文必须同时满足 `license_status=public` 和 `access_class=public`；
- 字段格式参考 `manifests/examples`；
- 公开数据集快照会拒绝任何非公开文档版本；
- 清单不得包含密码、Cookie、Token 或个人敏感信息。

提交前运行 `python scripts/validate_docs.py`，并按[数据清单编写指南](../../docs/data_layer/manifest_guide.md)核对字段。
