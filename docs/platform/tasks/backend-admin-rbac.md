# 任务：管理员用户角色与权限管理

## 目标

实现管理员管理用户、角色和知识库权限的后端接口，并统一计算用户可访问知识库集合。

## 输入文档

- `docs/platform/proposal.md`
- `docs/platform/high-level-design.md`
- `docs/platform/detailed-design.md`
- `docs/platform/tasks/backend-database-auth.md`

## 预期修改文件

- `backend-java/src/main/java/com/enterprise/rag/ApiController.java`
- `backend-java/src/main/java/com/enterprise/rag/AuthorizationService.java`
- `backend-java/src/main/java/com/enterprise/rag/UserRepository.java`
- `backend-java/src/main/java/com/enterprise/rag/KnowledgeBaseRepository.java`
- `backend-java/src/main/java/com/enterprise/rag/Models.java`
- `backend-java/src/test/java/com/enterprise/rag/ApiControllerTest.java` 或新增测试文件

## 依赖

- 后端数据库基础与认证任务完成。

## 实施步骤

- [ ] 实现 `AuthorizationService`，提供管理员判断、当前用户可访问知识库计算、知识库权限校验。
- [ ] 实现管理员用户列表接口 `GET /api/admin/users`。
- [ ] 实现用户角色替换接口 `PUT /api/admin/users/{id}/roles`。
- [ ] 实现用户禁用/启用接口 `PUT /api/admin/users/{id}/disabled`。
- [ ] 实现用户密码重置接口 `PUT /api/admin/users/{id}/password`。
- [ ] 实现角色列表接口 `GET /api/admin/roles`。
- [ ] 实现角色创建接口 `POST /api/admin/roles`。
- [ ] 实现角色知识库权限替换接口 `PUT /api/admin/roles/{id}/knowledge-bases`。
- [ ] 保护管理员接口，非管理员访问返回 `403 Forbidden`。
- [ ] 添加测试覆盖普通用户访问管理员接口被拒绝、管理员分配角色后权限生效、禁用已有 token 被拒绝。

## 测试与检查

```powershell
cd D:\pythonWorkspace\RAG
$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd test
```

## 完成定义

- [ ] 管理员可以管理用户、角色和角色知识库权限。
- [ ] 普通用户不能访问管理员接口。
- [ ] 用户可访问知识库集合按角色权限并集计算。
- [ ] 禁用用户的已有 token 访问接口被拒绝。
- [ ] 相关测试通过。
