# 任务：文档更新与整体验证

## 目标

更新项目说明文档，执行后端、AI 服务和前端验证，并记录最终风险。

## 输入文档

- `docs/proposal.md`
- `docs/high-level-design.md`
- `docs/detailed-design.md`
- `docs/tasks/*.md`

## 预期修改文件

- `docs/API.md`
- `docs/ARCHITECTURE.md`
- `README.md` 或 `AGENTS.md`，仅在需要同步运行方式时修改
- `docs/tasks/progress.md`

## 依赖

- 所有实现任务完成。

## 实施步骤

- [ ] 更新 `docs/API.md`，补充注册、当前用户、管理员用户/角色接口和聊天会话列表接口。
- [ ] 更新 `docs/ARCHITECTURE.md`，说明 PostgreSQL 持久化、RBAC 和 AI 权限契约。
- [ ] 检查 README 是否需要更新 demo 账号、运行配置或持久化说明。
- [ ] 执行 Java 后端测试。
- [ ] 执行 AI 服务测试。
- [ ] 执行前端构建。
- [ ] 视条件执行本地服务烟测：管理员登录上传、普通用户聊天、权限移除后不可见。
- [ ] 检查 `git diff`，确认无无关改动、无密钥、无生成物误提交。
- [ ] 更新 `docs/tasks/progress.md` 最终状态。

## 测试与检查

```powershell
cd D:\pythonWorkspace\RAG
$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd test
```

```powershell
cd D:\pythonWorkspace\RAG\ai-service
conda activate rag-ai
python -m unittest discover -s tests
```

```powershell
cd D:\pythonWorkspace\RAG\frontend
npm run build
```

## 完成定义

- [ ] API 和架构文档已更新。
- [ ] Java 测试通过或失败原因已记录。
- [ ] AI 服务测试通过或失败原因已记录。
- [ ] 前端构建通过或失败原因已记录。
- [ ] 最终 diff 已检查。
- [ ] `progress.md` 已更新。
