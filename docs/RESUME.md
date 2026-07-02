# Resume Description

企业级智能知识库平台（React + Spring Boot + FastAPI + LangGraph-style Agent + pgvector）

- 设计并实现企业 RAG 知识库平台，支持文档解析、切分、向量化、权限过滤检索、用户级聊天历史恢复、流式问答和 Agent Tool Calling。
- 后端采用 Spring Boot 承载认证、RBAC、知识库、文档元数据和会话管理，AI 服务采用 FastAPI 解耦模型调用和检索链路。
- 使用 PostgreSQL + pgvector 作为向量检索基础设施，Redis 作为会话/热点缓存预留，RabbitMQ 处理文档异步索引任务。
- 设计统一能力注册中心，将 RAG、受控 Text2SQL 与 Java 微服务封装为标准只读能力；模型通过两阶段规划自主选择和组合工具，服务端负责参数校验、权限注入、执行预算和失败重规划。
- 通过 OpenAI-compatible 接口统一适配 Qwen、DeepSeek、OpenAI，并预留模型切换和降级策略。
- 使用 Docker Compose 集成前后端、PostgreSQL、Redis、RabbitMQ、Prometheus、Grafana，具备完整本地演示和企业架构讲解能力。
