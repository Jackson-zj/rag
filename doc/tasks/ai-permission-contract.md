# 任务：AI 服务权限契约适配

## 目标

确认并测试 AI 服务以 `knowledge_base_ids` 作为检索主权限边界，`allowed_user_ids` 仅保留兼容行为。

## 输入文档

- `doc/proposal.md`
- `doc/high-level-design.md`
- `doc/detailed-design.md`
- `doc/tasks/backend-doc-chat-persistence.md`

## 预期修改文件

- `ai-service/app/main.py`
- `ai-service/tests/test_api.py`
- `ai-service/tests/test_rag.py`

## 依赖

- 后端文档上传契约明确为发送 `allowed_user_ids: []`。

## 实施步骤

- [ ] 检查 `search_chunks_in_memory`，确保先按 `knowledge_base_ids` 过滤。
- [ ] 检查 `search_chunks_in_postgres`，确保 SQL 先按 `knowledge_base_id = ANY(...)` 过滤。
- [ ] 保留 `allowed_user_ids` 兼容逻辑：为空表示不额外限制用户。
- [ ] 增加测试：`allowed_user_ids = []` 时，请求包含知识库 ID 可以检索。
- [ ] 增加测试：请求不包含知识库 ID 时，即使 chunk 存在也不能返回。
- [ ] 如果代码已满足要求，仅补测试和少量注释，不做无关重构。

## 测试与检查

```powershell
cd D:\pythonWorkspace\RAG\ai-service
conda activate rag-ai
python -m unittest discover -s tests
```

## 完成定义

- [ ] AI 服务查询权限以 `knowledge_base_ids` 为主。
- [ ] `allowed_user_ids` 为空不会阻止合法知识库检索。
- [ ] 未授权知识库不会被检索返回。
- [ ] AI 服务测试通过。
