# 注册登录与角色权限持久化详细设计

## 设计范围

本设计把已确认的需求和高层设计拆成可实现的模块、数据结构、接口契约和测试计划。实现目标是让当前本地 MVP 在 PostgreSQL 上持久化用户、角色、权限、知识库、文档元数据、会话和消息，并让管理员与普通用户获得不同的界面与能力。

## 文件结构

当前 Java 后端集中在 `EnterpriseRagApplication.java`。本次改造建议拆分为同包下多个文件，降低单文件复杂度：

```text
backend-java/src/main/java/com/enterprise/rag/
  EnterpriseRagApplication.java
  ApiController.java
  AuthService.java
  AuthorizationService.java
  UserRepository.java
  KnowledgeBaseRepository.java
  DocumentRepository.java
  ChatRepository.java
  AiClient.java
  Models.java
```

说明：

- `EnterpriseRagApplication.java` 保留 Spring Boot 启动类、RabbitMQ queue 和 JSON converter bean。
- `Models.java` 放置请求和响应 record，避免跨文件重复声明。
- `ApiController.java` 只做 HTTP 入参、调用服务和返回响应。
- `AuthService.java` 处理注册、登录、token、当前用户解析、BCrypt。
- `AuthorizationService.java` 处理管理员判断、知识库权限计算、接口权限校验。
- `UserRepository.java` 处理用户、角色、用户角色、角色知识库权限。
- `KnowledgeBaseRepository.java` 处理知识库查询和创建。
- `DocumentRepository.java` 处理文档元数据写入和查询。
- `ChatRepository.java` 处理会话、会话知识库范围和消息持久化。
- `AiClient.java` 封装当前控制器中的 AI HTTP 调用和 SSE 转发逻辑。

前端暂不强制拆分目录，但建议在 `frontend/src/main.tsx` 内先用函数组件分区实现，避免引入路由库扩大改动面。若组件复杂度过高，再在实现任务中拆分为：

```text
frontend/src/
  main.tsx
  styles.css
```

数据库初始化改动集中在：

```text
deploy/postgres/init.sql
```

文档更新集中在：

```text
docs/API.md
docs/ARCHITECTURE.md
```

## 数据库设计

### `users`

现有表需要增补状态和时间字段：

```sql
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  disabled BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `roles`

现有表需要增补描述和系统角色标记：

```sql
CREATE TABLE IF NOT EXISTS roles (
  id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  system_role BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `user_roles`

```sql
CREATE TABLE IF NOT EXISTS user_roles (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);
```

### `role_knowledge_bases`

```sql
CREATE TABLE IF NOT EXISTS role_knowledge_bases (
  role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, knowledge_base_id)
);
```

### `knowledge_bases`

沿用现有表，保留创建时间：

```sql
CREATE TABLE IF NOT EXISTS knowledge_bases (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `documents`

沿用现有表，补充兼容字段即可：

```sql
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
  filename TEXT NOT NULL,
  status TEXT NOT NULL,
  content_hash TEXT,
  chunk_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `document_chunks`

权限主边界改为查询时的 `knowledge_base_ids`，`allowed_user_ids` 保留兼容：

```sql
CREATE TABLE IF NOT EXISTS document_chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
  filename TEXT NOT NULL DEFAULT '',
  position INT NOT NULL,
  content TEXT NOT NULL,
  embedding vector(64),
  allowed_user_ids TEXT[] NOT NULL DEFAULT '{}'
);
```

### `chat_sessions`

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `chat_session_knowledge_bases`

```sql
CREATE TABLE IF NOT EXISTS chat_session_knowledge_bases (
  session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  PRIMARY KEY (session_id, knowledge_base_id)
);
```

### `chat_messages`

```sql
CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 种子数据

`init.sql` 写入以下初始数据：

- 角色：
  - `role-admin` / `ADMIN` / 系统管理员 / `system_role = true`
  - `role-user` / `USER` / 普通用户 / `system_role = true`
  - `role-analyst` / `ANALYST` / 分析用户 / `system_role = true`
- 用户：
  - `u-admin` / `admin` / BCrypt 后的 `admin123`
  - `u-analyst` / `analyst` / BCrypt 后的 `analyst123`
- 知识库：
  - `kb-hr`
  - `kb-tech`
- 用户角色：
  - `admin` -> `ADMIN`
  - `analyst` -> `ANALYST`
- 角色知识库权限：
  - `ADMIN` 可访问全部知识库。
  - `ANALYST` 可访问 `kb-hr`。
  - `USER` 默认不配置知识库权限，管理员后续分配。

BCrypt 哈希可以在实现阶段由 Java 启动种子逻辑生成，避免在 SQL 中维护固定哈希。若选择纯 SQL 种子，则使用预生成 BCrypt 字符串，并在文档中标注仅用于本地 demo。

## 后端模型

### 请求模型

```java
record RegisterRequest(String username, String password) {}
record LoginRequest(String username, String password) {}
record CreateRoleRequest(String name, String description) {}
record AssignUserRolesRequest(List<String> roleIds) {}
record AssignRoleKnowledgeBasesRequest(List<String> knowledgeBaseIds) {}
record ResetPasswordRequest(String password) {}
record SetUserDisabledRequest(boolean disabled) {}
record CreateKnowledgeBaseRequest(String name, String description) {}
record UploadDocumentRequest(String knowledgeBaseId, String filename, String content) {}
record CreateChatSessionRequest(String title, List<String> knowledgeBaseIds) {}
record ChatRequest(String question) {}
```

### 响应模型

```java
record LoginResponse(String token, UserView user) {}
record UserView(String id, String username, boolean disabled, List<String> roles, List<String> knowledgeBaseIds) {}
record RoleView(String id, String name, String description, boolean systemRole, List<String> knowledgeBaseIds) {}
record KnowledgeBaseView(String id, String name, String description) {}
record DocumentView(String id, String knowledgeBaseId, String filename, String status, Instant createdAt) {}
record ChatSessionView(String id, String userId, String title, List<String> knowledgeBaseIds, Instant createdAt) {}
record ChatMessageView(String id, String sessionId, String role, String content, Instant createdAt) {}
record AiIndexResponse(String document_id, String status, int chunk_count, boolean duplicate) {}
```

## API 设计

### 认证

- `POST /api/auth/register`
  - 公开接口。
  - 创建普通用户，默认分配 `USER` 角色。
  - 用户名重复返回 `409 Conflict`。

- `POST /api/auth/login`
  - 公开接口。
  - 用户不存在、密码错误或用户被禁用返回 `401 Unauthorized`。
  - 成功返回 token 和用户视图。

### 当前用户

- `GET /api/me`
  - 登录后可访问。
  - 返回当前用户、角色和可访问知识库。

### 用户管理

以下接口均要求管理员：

- `GET /api/admin/users`
  - 返回用户列表。

- `PUT /api/admin/users/{id}/roles`
  - 替换用户角色列表。
  - 不允许移除最后一个管理员角色导致系统没有管理员。实现阶段可先保护 `u-admin`。

- `PUT /api/admin/users/{id}/disabled`
  - 设置用户禁用状态。
  - 不允许禁用当前登录管理员自己。

- `PUT /api/admin/users/{id}/password`
  - 重置用户密码。
  - 密码使用 BCrypt 写入。

### 角色管理

以下接口均要求管理员：

- `GET /api/admin/roles`
  - 返回角色列表及各角色可访问知识库 ID。

- `POST /api/admin/roles`
  - 创建角色。
  - 角色名唯一。

- `PUT /api/admin/roles/{id}/knowledge-bases`
  - 替换角色可访问知识库列表。

### 知识库

- `GET /api/knowledge-bases`
  - 登录后可访问。
  - 管理员返回全部知识库。
  - 普通用户返回其角色授权的知识库；普通用户前端不显示列表，但聊天创建会使用这些权限。

- `POST /api/knowledge-bases`
  - 要求管理员。
  - 创建知识库。
  - 新知识库默认授权给 `ADMIN` 角色。

### 文档

- `POST /api/documents/upload`
  - 要求管理员。
  - 校验知识库存在。
  - 写入文档元数据并调用 AI 索引。

- `GET /api/documents/{id}`
  - 登录后可访问。
  - 管理员可访问全部。
  - 普通用户按知识库权限校验，但前端不提供文档列表入口。

### 聊天

- `POST /api/chat/sessions`
  - 登录后可访问。
  - 如果请求未传知识库 ID，使用当前用户可访问的全部知识库。
  - 如果请求传入知识库 ID，只保留当前用户有权限访问的知识库；如果过滤后为空则返回 `403 Forbidden` 或 `400 Bad Request`。
  - 普通用户前端不传知识库 ID。

- `GET /api/chat/sessions`
  - 登录后可访问。
  - 返回当前用户自己的会话列表。

- `GET /api/chat/sessions/{id}/messages`
  - 只能访问自己的会话。
  - 可选查询参数 `rounds`，例如 `rounds=10`。
  - 传入 `rounds` 时返回该会话最新 N 轮用户问题及其后续助手消息，并按时间正序返回。

- `POST /api/chat/sessions/{id}/stream`
  - 只能访问自己的会话。
  - 后端保存用户消息，转发 AI SSE，完成后保存助手消息。

## 后端控制流

### 当前用户解析

所有受保护接口调用：

```text
Authorization header -> token -> username/user_id -> 数据库读取用户 -> 检查 disabled -> 构造 CurrentUser
```

`CurrentUser` 包含：

- 用户 ID
- 用户名
- 角色名集合
- 是否管理员
- 可访问知识库 ID 集合

即使 token 存在于内存中，也必须每次从数据库读取用户状态，满足“禁用后已有 token 也被拒绝”。

### 权限计算

```text
如果用户拥有 ADMIN 角色：
  返回全部知识库 ID
否则：
  查询 user_roles -> role_knowledge_bases，取并集
```

### 上传索引

上传时发送给 AI 服务：

```json
{
  "document_id": "doc-...",
  "knowledge_base_id": "kb-...",
  "filename": "policy.txt",
  "content": "...",
  "content_hash": "...",
  "allowed_user_ids": []
}
```

`allowed_user_ids` 传空数组，表示 AI 端不再用固化用户列表作为主权限。检索权限由后端传入的 `knowledge_base_ids` 控制。

### 聊天流

发送给 AI 服务：

```json
{
  "user_id": "u-...",
  "session_id": "chat-...",
  "question": "...",
  "knowledge_base_ids": ["kb-hr", "kb-tech"]
}
```

AI 服务只按 `knowledge_base_ids` 检索。`allowed_user_ids` 兼容逻辑不能因为为空而拒绝结果。

## AI 服务适配

### 搜索过滤

`search_chunks_in_memory` 当前逻辑已经在 `allowed_user_ids` 为空时允许访问：

```python
if chunk["allowed_user_ids"] and request.user_id not in chunk["allowed_user_ids"]:
    continue
```

PostgreSQL 查询当前包含：

```sql
AND (cardinality(allowed_user_ids) = 0 OR %s = ANY(allowed_user_ids))
```

该逻辑可以保留。关键是 Java 后端上传时传空数组，并在聊天时传准确的 `knowledge_base_ids`。

### 测试补充

AI 服务增加或更新测试，验证：

- `allowed_user_ids = []` 时，用户只要在请求的 `knowledge_base_ids` 中即可检索。
- 请求中不包含某知识库 ID 时，即使 chunk 存在也不能返回。

## 前端设计

### 状态模型

前端新增状态：

```ts
type Role = { id: string; name: string; description: string; systemRole: boolean; knowledgeBaseIds: string[] };
type User = { id: string; username: string; disabled: boolean; roles: string[]; knowledgeBaseIds: string[] };
type KnowledgeBase = { id: string; name: string; description: string };
type AuthContext = { token: string; user: User };
```

### 未登录视图

- 登录表单：用户名、密码。
- 注册表单：用户名、密码、确认密码。
- 注册成功后提示用户登录，或自动登录。建议先自动登录，减少流程阻力。

### 管理员视图

保留当前管理台结构并新增管理区域：

- 侧边栏：上传文件、上传文本、新建会话、刷新用户/角色。
- 知识库区域：展示全部知识库。
- 文档上传区域：管理员可见。
- 用户管理区域：
  - 用户列表。
  - 禁用/启用按钮。
  - 重置密码输入。
  - 用户角色分配。
- 角色管理区域：
  - 创建角色。
  - 角色描述。
  - 配置角色可访问知识库。
- 聊天区域：管理员也可以问答。

### 普通用户视图

- 页面主体只保留聊天。
- 不显示上传入口、文档文本框、文档列表、知识库列表、用户管理、角色管理。
- 创建会话和提问时不传知识库 ID，由后端默认处理。

## 错误处理

后端统一使用明确 HTTP 状态：

- `400 Bad Request`：请求字段缺失、密码为空、无可用知识库创建会话。
- `401 Unauthorized`：未登录、token 无效、密码错误、用户被禁用。
- `403 Forbidden`：已登录但无管理员权限或无知识库权限。
- `404 Not Found`：用户、角色、知识库、文档或会话不存在。
- `409 Conflict`：用户名或角色名重复。
- `502 Bad Gateway`：AI 服务索引或问答失败。

前端通过现有 `readableError` 展示后端错误消息。

## 配置

### Java 后端

`application.yml` 新增：

```yaml
spring:
  datasource:
    url: ${DATABASE_URL:jdbc:postgresql://localhost:5433/rag_db}
    username: ${DATABASE_USER:postgres}
    password: ${DATABASE_PASSWORD:123456}
```

Docker Compose 的 `backend-java` 新增环境变量：

```yaml
DATABASE_URL: jdbc:postgresql://pgvector:5432/rag_db
DATABASE_USER: postgres
DATABASE_PASSWORD: 123456
```

### AI 服务

保持：

```yaml
VECTOR_DATABASE_URL: postgresql://postgres:123456@pgvector:5432/rag_db
```

## 测试计划

### Java 后端测试

建议使用 H2 兼容性不佳，因为 SQL 使用 PostgreSQL 数组、pgvector 和 `TIMESTAMPTZ`。本阶段可优先把 repository 方法设计为 `JdbcTemplate`，并在控制器测试中通过 mock repository/service 覆盖业务逻辑。若需要数据库集成测试，后续再引入 Testcontainers。

需要覆盖：

- 注册成功并分配默认 `USER` 角色。
- 重复用户名注册返回冲突。
- 登录成功返回 token 和用户视图。
- 禁用用户不能登录。
- 禁用用户已有 token 调用接口被拒绝。
- 普通用户上传文档返回禁止。
- 管理员上传文档成功调用 AI 索引。
- 管理员创建角色并分配知识库。
- 管理员给用户分配角色后，用户可访问知识库更新。
- 创建聊天会话未传知识库时，自动使用当前用户全部可访问知识库。
- 用户不能访问他人的聊天会话。
- 重置密码后旧密码失败、新密码成功。

### AI 服务测试

需要覆盖：

- PostgreSQL 未启用时，内存检索以 `knowledge_base_ids` 为主。
- `allowed_user_ids` 为空时不会阻止有知识库权限的用户检索。
- 不在请求 `knowledge_base_ids` 中的 chunk 不会返回。

### 前端验证

- `npm run build` 通过。
- 管理员登录后显示管理工作台和上传入口。
- 普通用户登录后只显示聊天界面。
- 注册后可以登录。
- API 错误能显示在页面通知区域。

## 实施风险

- Java 后端从内存迁移到数据库会影响多数接口，需要分任务逐步替换，避免一次性大改难以验证。
- 如果保留内存 token，服务重启后用户需要重新登录；这不影响用户、角色和聊天数据持久化，但需要在最终说明中明确。
- 初始化 BCrypt 种子数据需要谨慎，避免把明文密码写入除文档说明外的运行路径。
- 前端当前存在中文乱码文本，改造界面时应统一替换为正常中文，避免继续传播旧乱码。
- RabbitMQ 当前只是异步加速路径，索引权威结果仍来自同步 AI 调用；后续任务不要把成功状态完全依赖 RabbitMQ。

## 分阶段实现建议

1. 数据库和后端依赖：补表、数据源、BCrypt、repository 基础。
2. 认证与用户角色：注册、登录、当前用户、管理员用户和角色接口。
3. 知识库、文档和聊天持久化：替换 DemoStore，接入权限计算。
4. AI 权限契约适配：上传传空 `allowed_user_ids`，补测试。
5. 前端登录注册与角色化界面：管理员工作台、普通用户聊天界面。
6. 文档和验证：更新 API/架构说明，跑测试和构建。
