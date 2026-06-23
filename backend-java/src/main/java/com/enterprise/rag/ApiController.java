package com.enterprise.rag;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api")
@CrossOrigin
class ApiController {
    private final AuthService auth;
    private final AuthorizationService authorization;
    private final UserRepository users;
    private final KnowledgeBaseRepository knowledgeBases;
    private final DocumentRepository documents;
    private final ChatRepository chats;
    private final AiClient aiClient;
    private final RabbitTemplate rabbitTemplate;
    private final String documentQueue;

    ApiController(AuthService auth,
                  AuthorizationService authorization,
                  UserRepository users,
                  KnowledgeBaseRepository knowledgeBases,
                  DocumentRepository documents,
                  ChatRepository chats,
                  AiClient aiClient,
                  RabbitTemplate rabbitTemplate,
                  @Value("${rag.rabbit.document-index-queue}") String documentQueue) {
        this.auth = auth;
        this.authorization = authorization;
        this.users = users;
        this.knowledgeBases = knowledgeBases;
        this.documents = documents;
        this.chats = chats;
        this.aiClient = aiClient;
        this.rabbitTemplate = rabbitTemplate;
        this.documentQueue = documentQueue;
    }

    @PostMapping("/auth/register")
    LoginResponse register(@RequestBody RegisterRequest request) {
        return auth.register(request);
    }

    @PostMapping("/auth/login")
    LoginResponse login(@RequestBody LoginRequest request) {
        return auth.login(request);
    }

    @GetMapping("/me")
    UserView me(@RequestHeader("Authorization") String authorizationHeader) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        return new UserView(user.id(), user.username(), user.disabled(), user.roles(), user.knowledgeBaseIds());
    }

    @GetMapping("/admin/users")
    List<UserView> users(@RequestHeader("Authorization") String authorizationHeader) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        return users.listUsers();
    }

    @PutMapping("/admin/users/{id}/roles")
    UserView replaceUserRoles(@RequestHeader("Authorization") String authorizationHeader,
                              @PathVariable("id") String id,
                              @RequestBody AssignUserRolesRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        users.replaceUserRoles(id, request.roleIds());
        return users.userView(id);
    }

    @PutMapping("/admin/users/{id}/disabled")
    UserView setUserDisabled(@RequestHeader("Authorization") String authorizationHeader,
                             @PathVariable("id") String id,
                             @RequestBody SetUserDisabledRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        if (user.id().equals(id)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "不能禁用当前登录管理员");
        }
        users.setDisabled(id, request.disabled());
        return users.userView(id);
    }

    @PutMapping("/admin/users/{id}/password")
    UserView resetPassword(@RequestHeader("Authorization") String authorizationHeader,
                           @PathVariable("id") String id,
                           @RequestBody ResetPasswordRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        auth.resetPassword(id, request.password());
        return users.userView(id);
    }

    @GetMapping("/admin/roles")
    List<RoleView> roles(@RequestHeader("Authorization") String authorizationHeader) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        return users.listRoles();
    }

    @PostMapping("/admin/roles")
    RoleView createRole(@RequestHeader("Authorization") String authorizationHeader,
                        @RequestBody CreateRoleRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        return users.createRole(request.name(), request.description());
    }

    @PutMapping("/admin/roles/{id}/knowledge-bases")
    RoleView replaceRoleKnowledgeBases(@RequestHeader("Authorization") String authorizationHeader,
                                       @PathVariable("id") String id,
                                       @RequestBody AssignRoleKnowledgeBasesRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        users.replaceRoleKnowledgeBases(id, request.knowledgeBaseIds());
        return users.roleView(id);
    }

    @GetMapping("/knowledge-bases")
    List<KnowledgeBaseView> knowledgeBases(@RequestHeader("Authorization") String authorizationHeader) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        return knowledgeBases.visibleFor(user);
    }

    @PostMapping("/knowledge-bases")
    KnowledgeBaseView createKnowledgeBase(@RequestHeader("Authorization") String authorizationHeader,
                                          @RequestBody CreateKnowledgeBaseRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        return knowledgeBases.create(request);
    }

    @PostMapping("/documents/upload")
    DocumentView upload(@RequestHeader("Authorization") String authorizationHeader,
                        @RequestBody UploadDocumentRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        authorization.requireAdmin(user);
        knowledgeBases.get(request.knowledgeBaseId());
        String id = "doc-" + UUID.randomUUID();
        String contentHash = contentHash(request.content());
        Instant createdAt = Instant.now();
        Map<String, Object> payload = Map.of(
                "document_id", id,
                "knowledge_base_id", request.knowledgeBaseId(),
                "filename", request.filename(),
                "content", request.content(),
                "content_hash", contentHash,
                "allowed_user_ids", List.of()
        );
        AiIndexResponse indexResponse;
        try {
            indexResponse = aiClient.indexDocument(payload);
            documents.markIndexed(indexResponse, id, request.knowledgeBaseId(), request.filename(), createdAt);
        } catch (Exception ex) {
            documents.markFailed(id, request.knowledgeBaseId(), request.filename(), contentHash);
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI indexing failed: " + rootMessage(ex), ex);
        }
        if (!indexResponse.duplicate()) {
            try {
                rabbitTemplate.convertAndSend(documentQueue, payload);
            } catch (Exception ignored) {
                // RabbitMQ is optional for the local MVP; synchronous indexing above is authoritative.
            }
        }
        return documents.get(indexResponse.document_id()).orElseThrow();
    }

    @RabbitListener(queues = "${rag.rabbit.document-index-queue}")
    void handleDocumentIndex(Map<String, Object> payload) {
        // Synchronous indexing in upload() is authoritative; RabbitMQ remains a best-effort compatibility path.
        aiClient.indexDocument(payload);
    }

    @GetMapping("/documents/{id}")
    DocumentView document(@RequestHeader("Authorization") String authorizationHeader, @PathVariable("id") String id) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        DocumentView doc = documents.get(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "文档不存在"));
        authorization.requireKnowledgeBaseAccess(user, doc.knowledgeBaseId());
        return doc;
    }

    @PostMapping("/chat/sessions")
    ChatSessionView createSession(@RequestHeader("Authorization") String authorizationHeader,
                                  @RequestBody CreateChatSessionRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        List<String> visible = authorization.allowedKnowledgeBases(user, request.knowledgeBaseIds());
        if (visible.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "当前用户没有可用知识库");
        }
        return chats.createSession(user.id(), request.title(), visible);
    }

    @GetMapping("/chat/sessions")
    List<ChatSessionView> sessions(@RequestHeader("Authorization") String authorizationHeader) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        return chats.listSessions(user.id());
    }

    @PatchMapping("/chat/sessions/{id}")
    ChatSessionView renameSession(@RequestHeader("Authorization") String authorizationHeader,
                                  @PathVariable("id") String id,
                                  @RequestBody UpdateChatSessionRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        ChatSessionView session = requireOwnSession(user, id);
        String title = request.title() == null ? "" : request.title().trim();
        int titleLength = title.codePointCount(0, title.length());
        if (titleLength < 1 || titleLength > 60) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "会话标题长度必须为 1 至 60 个字符");
        }
        return chats.renameSession(session.id(), title);
    }

    @GetMapping("/chat/sessions/{id}/messages")
    List<ChatMessageView> messages(@RequestHeader("Authorization") String authorizationHeader,
                                   @PathVariable("id") String id,
                                   @RequestParam(value = "rounds", required = false) Integer rounds) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        ChatSessionView session = requireOwnSession(user, id);
        return rounds == null ? chats.messages(session.id()) : chats.messages(session.id(), rounds);
    }

    @PostMapping(value = "/chat/sessions/{id}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter stream(@RequestHeader("Authorization") String authorizationHeader,
                      @PathVariable("id") String id,
                      @RequestBody ChatRequest request) {
        CurrentUser user = auth.currentUser(authorizationHeader);
        ChatSessionView session = requireOwnSession(user, id);
        chats.addMessage(id, "user", request.question());
        SseEmitter emitter = new SseEmitter(120_000L);
        new Thread(() -> {
            try {
                Map<String, Object> payload = Map.of(
                        "user_id", user.id(),
                        "session_id", id,
                        "question", request.question(),
                        "knowledge_base_ids", session.knowledgeBaseIds()
                );
                String answer = aiClient.streamChat(payload, emitter);
                chats.addMessage(id, "assistant", answer);
                emitter.complete();
            } catch (Exception ex) {
                try {
                    emitter.send(SseEmitter.event().name("error").data("AI chat failed: " + rootMessage(ex)));
                } catch (Exception ignored) {
                }
                emitter.complete();
            }
        }).start();
        return emitter;
    }

    private ChatSessionView requireOwnSession(CurrentUser user, String id) {
        ChatSessionView session = chats.getSession(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在"));
        if (!session.userId().equals(user.id())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "不能访问其他用户的会话");
        }
        return session;
    }

    private String rootMessage(Exception ex) {
        Throwable cursor = ex;
        while (cursor.getCause() != null) {
            cursor = cursor.getCause();
        }
        return cursor.getMessage() == null ? ex.getClass().getSimpleName() : cursor.getMessage();
    }

    private String contentHash(String content) {
        String normalized = content == null ? "" : content.replace("\r\n", "\n").replace("\r", "\n").strip();
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(normalized.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is not available", ex);
        }
    }
}
