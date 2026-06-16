# 任务：后端数据库基础与认证

## 目标

为 Java 后端接入 PostgreSQL、BCrypt 和持久化用户认证能力，替换当前 `DemoStore` 中的内存登录用户。

## 输入文档

- `doc/proposal.md`
- `doc/high-level-design.md`
- `doc/detailed-design.md`

## 预期修改文件

- `backend-java/pom.xml`
- `backend-java/src/main/resources/application.yml`
- `backend-java/src/main/java/com/enterprise/rag/EnterpriseRagApplication.java`
- `backend-java/src/main/java/com/enterprise/rag/Models.java`
- `backend-java/src/main/java/com/enterprise/rag/AuthService.java`
- `backend-java/src/main/java/com/enterprise/rag/UserRepository.java`
- `deploy/postgres/init.sql`
- `backend-java/src/test/java/com/enterprise/rag/ApiControllerTest.java` 或新增测试文件

## 依赖

无。该任务是后续后端任务的基础。

## 实施步骤

- [ ] 在 Maven 中新增 PostgreSQL JDBC、Spring JDBC 和 Spring Security Crypto 依赖。
- [ ] 在 `application.yml` 中新增 `spring.datasource` 配置，支持环境变量覆盖。
- [ ] 扩展 `deploy/postgres/init.sql`，加入用户状态、角色描述、用户角色表、角色知识库权限表和种子数据。
- [ ] 新建或整理 `Models.java`，放置注册、登录、用户视图、角色视图等 record。
- [ ] 实现 `UserRepository`，支持用户查询、创建、角色查询和默认角色分配。
- [ ] 实现 `AuthService`，支持注册、登录、BCrypt 校验、token 生成、当前用户解析和禁用状态校验。
- [ ] 保留 `admin / admin123` 与 `analyst / analyst123` 的本地 demo 初始化能力。
- [ ] 更新或新增测试覆盖注册、登录、重复用户名、禁用用户登录失败。

## 测试与检查

```powershell
cd D:\pythonWorkspace\RAG
$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd test
```

## 完成定义

- [ ] Java 后端可以连接 PostgreSQL 配置。
- [ ] 注册用户写入 PostgreSQL。
- [ ] 登录使用 BCrypt 校验。
- [ ] 被禁用用户不能登录。
- [ ] demo 账号仍可用于本地验证。
- [ ] 相关测试通过。
