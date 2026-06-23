# 历史会话功能详细设计

## Backend Contract

- 新增 `PATCH /api/chat/sessions/{id}`，请求体为 `{"title":"..."}`，响应为更新后的 `ChatSessionView`。
- 标题 trim 后必须为 1 至 60 个字符；非法返回 400。
- 复用 `requireOwnSession`：不存在返回 404，非所有者返回 403。
- Repository 仅更新标题并重新读取会话，不修改 `created_at`。

## Frontend State And Flow

- `ChatSession` 增加 `userId` 和 `createdAt`；新增 `sessions`、会话栏展开状态和重命名状态。
- 本地键格式为 `rag.activeSession.<userId>`。
- 登录恢复：匹配本地 Session ID，失败则选择列表首项；读取最近 10 轮后再展示。
- 新对话：清空当前会话、消息、输入和临时事件；首次发送时创建会话，标题为压缩空白后的首问前 32 字符。
- 切换：清空输入，加载历史，保存 Session ID；请求失败保持原会话。
- 重命名：原地输入，Enter/确认保存，Escape 取消；客户端和服务端均校验 1 至 60 字符。
- 会话操作在 `busy` 非空时禁用。

## UI

- 聊天页使用双列 `session-history + chat`，会话项展示标题和本地化创建时间。
- 当前项使用边框和背景区分；编辑操作使用 Lucide 图标与 tooltip。
- 小屏幕默认收起历史栏，由聊天标题栏的历史图标打开；选择会话后自动收起。

## Verification

- Java 控制器测试覆盖成功、空标题、超长标题和越权。
- 运行 Java 测试和前端构建。
- 浏览器验证 admin 与普通用户的列表隔离、切换、新建、恢复、重命名及移动端布局。

