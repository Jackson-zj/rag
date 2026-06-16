# 任务：前端登录注册与角色化界面

## 目标

将前端从自动登录 demo 管理台改造为登录/注册入口、管理员工作台和普通用户聊天界面。

## 输入文档

- `doc/proposal.md`
- `doc/high-level-design.md`
- `doc/detailed-design.md`
- `doc/tasks/backend-database-auth.md`
- `doc/tasks/backend-admin-rbac.md`
- `doc/tasks/backend-doc-chat-persistence.md`

## 预期修改文件

- `frontend/src/main.tsx`
- `frontend/src/styles.css`
- 视实现复杂度可新增前端组件文件，但优先控制改动范围。

## 依赖

- 后端注册、登录、当前用户、管理员用户角色接口可用。
- 后端聊天接口支持普通用户不传知识库 ID。

## 实施步骤

- [ ] 移除自动 admin 登录行为。
- [ ] 新增登录和注册表单。
- [ ] 登录成功后保存 token 和用户信息。
- [ ] 根据 `ADMIN` 角色显示管理员工作台。
- [ ] 管理员工作台保留上传文档、知识库、问答和事件时间线。
- [ ] 管理员工作台新增用户管理、禁用/启用、重置密码、角色分配。
- [ ] 管理员工作台新增角色创建、角色描述和角色知识库权限配置。
- [ ] 普通用户界面只显示聊天框、回答区域和必要状态提示。
- [ ] 普通用户创建会话和提问时不传知识库 ID。
- [ ] 替换当前乱码中文文案，统一为正常中文。

## 测试与检查

```powershell
cd D:\pythonWorkspace\RAG\frontend
npm run build
```

## 完成定义

- [ ] 未登录用户看到登录/注册界面。
- [ ] 管理员登录后看到管理工作台和上传入口。
- [ ] 普通用户登录后只看到聊天界面。
- [ ] 用户管理和角色管理界面可以调用后端接口。
- [ ] 前端构建通过。
