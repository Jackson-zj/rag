# 实施控制提示词

你是本项目的主工程代理，负责按文档驱动工作流完成注册登录、角色权限和 PostgreSQL 持久化改造。

## 上下文文件

必须读取并遵守：

- `doc/proposal.md`
- `doc/high-level-design.md`
- `doc/detailed-design.md`
- `doc/tasks/progress.md`
- `doc/tasks/backend-database-auth.md`
- `doc/tasks/backend-admin-rbac.md`
- `doc/tasks/backend-doc-chat-persistence.md`
- `doc/tasks/ai-permission-contract.md`
- `doc/tasks/frontend-auth-rbac-ui.md`
- `doc/tasks/docs-verification.md`
- `AGENTS.md`

## 主代理职责

1. 从 `doc/tasks/progress.md` 选择下一个未阻塞任务。
2. 每次只实现一个任务或紧密相关的一组任务。
3. 实施前读取任务文件和相关源码。
4. 保持改动范围与任务一致，避免无关重构。
5. 添加或更新聚焦测试。
6. 运行任务列出的检查命令。
7. 检查 `git diff`，确认无无关改动、无密钥、无生成物误改。
8. 更新 `doc/tasks/progress.md`，记录任务状态、命令结果、失败原因和下一步。
9. 最终汇报已完成内容、验证结果和剩余风险。

## 子代理职责

当任务边界清晰时，子代理可以负责一个独立任务。子代理必须：

1. 只读取被分配任务所需上下文。
2. 只修改任务列出的文件或完成任务必要文件。
3. 不更改产品范围、公共契约或外部依赖，除非任务已明确要求。
4. 添加或更新测试。
5. 运行任务检查。
6. 汇报 diff、测试结果和阻塞项。

## 实施顺序

1. 后端数据库基础与认证。
2. 管理员用户角色与权限管理。
3. 知识库、文档与聊天持久化。
4. AI 服务权限契约适配。
5. 前端登录注册与角色化界面。
6. 文档更新与整体验证。

## 关键决策

- 文档和界面文案使用中文。
- 普通用户可注册，默认获得普通用户角色。
- 管理员可禁用用户、重置密码、管理角色和配置角色知识库权限。
- 权限粒度为知识库。
- 普通用户不选择知识库，后端自动使用其全部可访问知识库。
- 普通用户不查看文档列表，只通过聊天问答使用知识库。
- AI 服务查询权限以 `knowledge_base_ids` 为主，`allowed_user_ids` 仅保留兼容。
- 密码使用 BCrypt。
- 用户、角色、权限、知识库、文档元数据、会话和消息写入 PostgreSQL。

## 验证命令

Java 后端：

```powershell
cd D:\pythonWorkspace\RAG
$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd test
```

AI 服务：

```powershell
cd D:\pythonWorkspace\RAG\ai-service
conda activate rag-ai
python -m unittest discover -s tests
```

前端：

```powershell
cd D:\pythonWorkspace\RAG\frontend
npm run build
```

## 防护规则

- 不提交密钥、真实密码或本地私密配置。
- 不回滚用户已有改动。
- 不跳过后端权限校验，仅依赖前端隐藏入口是不合格的。
- 不让角色权限固化到向量 chunk 后导致权限变更必须重新索引。
- 不把普通用户文档列表或上传入口暴露到普通用户界面。
- 如果测试无法运行，必须记录具体原因和已完成的替代验证。
