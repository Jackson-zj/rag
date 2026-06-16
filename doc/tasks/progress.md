# 进度

## 当前状态

注册登录、角色权限、PostgreSQL 持久化、AI 权限契约、前端角色化界面、API/架构文档更新均已完成。已执行 Java 后端测试、AI 服务测试和前端构建。

## 任务

- [x] 后端数据库基础与认证 - 已完成，文件：`doc/tasks/backend-database-auth.md`
- [x] 管理员用户角色与权限管理 - 已完成，文件：`doc/tasks/backend-admin-rbac.md`
- [x] 知识库、文档与聊天持久化 - 已完成，文件：`doc/tasks/backend-doc-chat-persistence.md`
- [x] AI 服务权限契约适配 - 已完成，文件：`doc/tasks/ai-permission-contract.md`
- [x] 前端登录注册与角色化界面 - 已完成，文件：`doc/tasks/frontend-auth-rbac-ui.md`
- [x] 文档更新与整体验证 - 已完成，文件：`doc/tasks/docs-verification.md`

## 已确认决策

- 文档使用中文。
- 普通用户可以注册，默认获得普通用户角色。
- 管理员可以禁用用户和重置用户密码。
- 角色包含描述字段。
- 权限粒度按知识库控制。
- 普通用户不选择知识库，后端自动使用其全部可访问知识库。
- 普通用户不查看文档列表，只使用聊天问答。
- AI 服务查询权限以 `knowledge_base_ids` 为主，`allowed_user_ids` 仅保留兼容。

## 命令记录

- `.\mvnw.cmd test`：通过，`ApiControllerTest` 4 个测试通过。
- `D:\anaconda3\envs\rag-ai\python.exe -m unittest discover -s tests`：通过，20 个测试通过。
- `npm run build`：通过，TypeScript 和 Vite 构建成功。

## 阻塞项

- 无。

## 后续风险

- Java 后端当前使用内存 bearer token，重启后需要重新登录；用户、角色、权限、文档元数据、会话和消息已持久化到 PostgreSQL。
- 当前测试以控制器/服务逻辑和 AI 单元测试为主，尚未引入真实 PostgreSQL 的 Testcontainers 集成测试。
- 若本机已有旧 PostgreSQL volume，Java 启动时会自动补业务表和列；pgvector 扩展与 `document_chunks` 向量表仍依赖 `deploy/postgres/init.sql` 或现有部署初始化。
