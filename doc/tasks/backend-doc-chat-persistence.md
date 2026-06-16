# 任务：知识库、文档与聊天持久化

## 目标

将知识库、文档元数据、聊天会话和消息从内存存储迁移到 PostgreSQL，并在上传和问答流程中接入新的权限模型。

## 输入文档

- `doc/proposal.md`
- `doc/high-level-design.md`
- `doc/detailed-design.md`
- `doc/tasks/backend-database-auth.md`
- `doc/tasks/backend-admin-rbac.md`

## 预期修改文件

- `backend-java/src/main/java/com/enterprise/rag/ApiController.java`
- `backend-java/src/main/java/com/enterprise/rag/KnowledgeBaseRepository.java`
- `backend-java/src/main/java/com/enterprise/rag/DocumentRepository.java`
- `backend-java/src/main/java/com/enterprise/rag/ChatRepository.java`
- `backend-java/src/main/java/com/enterprise/rag/AiClient.java`
- `backend-java/src/main/java/com/enterprise/rag/Models.java`
- `deploy/docker-compose.yml`
- `backend-java/src/test/java/com/enterprise/rag/ApiControllerTest.java` 或新增测试文件

## 依赖

- 后端数据库基础与认证任务完成。
- 管理员用户角色与权限管理任务完成。

## 实施步骤

- [ ] 实现 `KnowledgeBaseRepository`，支持知识库查询和创建。
- [ ] 实现 `DocumentRepository`，支持文档创建、状态更新、去重结果同步和按 ID 查询。
- [ ] 实现 `ChatRepository`，支持会话创建、会话知识库范围、会话列表和消息读写。
- [ ] 将 `POST /api/knowledge-bases` 改为管理员接口，新知识库默认授权给 `ADMIN` 角色。
- [ ] 将 `POST /api/documents/upload` 改为管理员专属接口。
- [ ] 上传文档时向 AI 服务传 `allowed_user_ids: []`。
- [ ] 创建聊天会话时，如果请求未传知识库 ID，则使用当前用户全部可访问知识库。
- [ ] 聊天 SSE 流保存用户消息和助手消息。
- [ ] Docker Compose 为 Java 后端补充数据库连接环境变量。
- [ ] 添加测试覆盖普通用户上传被拒绝、聊天会话范围自动计算、用户不能访问他人会话。

## 测试与检查

```powershell
cd D:\pythonWorkspace\RAG
$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd test
```

## 完成定义

- [ ] 知识库、文档元数据、会话和消息写入 PostgreSQL。
- [ ] 普通用户不能上传文档。
- [ ] 普通用户创建会话默认使用其全部可访问知识库。
- [ ] 用户不能读取或使用他人的会话。
- [ ] 上传时 AI 权限主边界不再固化为用户列表。
- [ ] 相关测试通过。
