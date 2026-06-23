# Task: 历史会话后端 API

## Objective

增加安全的本人会话重命名能力。

## Expected Files

- `backend-java/src/main/java/com/enterprise/rag/Models.java`
- `backend-java/src/main/java/com/enterprise/rag/ChatRepository.java`
- `backend-java/src/main/java/com/enterprise/rag/ApiController.java`
- `backend-java/src/test/java/com/enterprise/rag/ApiControllerTest.java`

## Implementation Steps

- [x] 增加标题更新请求模型与 PATCH 接口。
- [x] 增加所有权和标题校验。
- [x] 增加 Repository 更新方法。
- [x] 补充控制器测试。

## Definition Of Done

- [x] 所有者可重命名，越权和非法标题被拒绝。
- [x] Java 测试通过。
