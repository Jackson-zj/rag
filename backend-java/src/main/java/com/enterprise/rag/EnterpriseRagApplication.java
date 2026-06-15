package com.enterprise.rag;

import org.springframework.amqp.core.Queue;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.OutputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

@SpringBootApplication
public class EnterpriseRagApplication {
    public static void main(String[] args) {
        SpringApplication.run(EnterpriseRagApplication.class, args);
    }

    @Bean
    Queue documentIndexQueue(@Value("${rag.rabbit.document-index-queue}") String queue) {
        return new Queue(queue, true);
    }

    @Bean
    MessageConverter jsonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }
}

record LoginRequest(String username, String password) {}
record LoginResponse(String token, UserView user) {}
record UserView(String id, String username, List<String> roles, List<String> knowledgeBaseIds) {}
record KnowledgeBaseView(String id, String name, String description, List<String> allowedUserIds) {}
record CreateKnowledgeBaseRequest(String name, String description) {}
record UploadDocumentRequest(String knowledgeBaseId, String filename, String content) {}
record DocumentView(String id, String knowledgeBaseId, String filename, String status, Instant createdAt) {}
record CreateChatSessionRequest(String title, List<String> knowledgeBaseIds) {}
record ChatSessionView(String id, String userId, String title, List<String> knowledgeBaseIds, Instant createdAt) {}
record ChatMessageView(String id, String sessionId, String role, String content, Instant createdAt) {}
record ChatRequest(String question) {}
record AgentResponse(String answer, List<Map<String, Object>> citations, List<Map<String, Object>> tool_calls) {}
record AiIndexResponse(String document_id, String status, int chunk_count, boolean duplicate) {}

class DemoStore {
    final Map<String, String> tokens = new ConcurrentHashMap<>();
    final Map<String, UserView> users = new ConcurrentHashMap<>();
    final Map<String, String> passwords = new ConcurrentHashMap<>();
    final Map<String, KnowledgeBaseView> knowledgeBases = new ConcurrentHashMap<>();
    final Map<String, DocumentView> documents = new ConcurrentHashMap<>();
    final Map<String, ChatSessionView> sessions = new ConcurrentHashMap<>();
    final Map<String, List<ChatMessageView>> messages = new ConcurrentHashMap<>();

    DemoStore() {
        users.put("admin", new UserView("u-admin", "admin", List.of("ADMIN"), List.of("kb-hr", "kb-tech")));
        users.put("analyst", new UserView("u-analyst", "analyst", List.of("ANALYST"), List.of("kb-hr")));
        passwords.put("admin", "admin123");
        passwords.put("analyst", "analyst123");
        knowledgeBases.put("kb-hr", new KnowledgeBaseView("kb-hr", "HR Policy KB", "Employee handbook, attendance, reimbursement, and performance policy.", List.of("u-admin", "u-analyst")));
        knowledgeBases.put("kb-tech", new KnowledgeBaseView("kb-tech", "Tech Architecture KB", "Service governance, deployment standards, and incident playbooks.", List.of("u-admin")));
    }

    UserView requireUser(String token) {
        String username = tokens.get(token);
        if (username == null || !users.containsKey(username)) {
            throw new IllegalArgumentException("Invalid token");
        }
        return users.get(username);
    }
}

@RestController
@RequestMapping("/api")
@CrossOrigin
class ApiController {
    private final DemoStore store = new DemoStore();
    private final ObjectMapper objectMapper;
    private final URI aiServiceUri;
    private final RabbitTemplate rabbitTemplate;
    private final String documentQueue;

    ApiController(ObjectMapper objectMapper,
                  RabbitTemplate rabbitTemplate,
                  @Value("${rag.ai-service-url}") String aiServiceUrl,
                  @Value("${rag.rabbit.document-index-queue}") String documentQueue) {
        this.objectMapper = objectMapper;
        this.aiServiceUri = URI.create(aiServiceUrl.endsWith("/") ? aiServiceUrl : aiServiceUrl + "/");
        this.rabbitTemplate = rabbitTemplate;
        this.documentQueue = documentQueue;
    }

    @PostMapping("/auth/login")
    LoginResponse login(@RequestBody LoginRequest request) {
        if (!Objects.equals(store.passwords.get(request.username()), request.password())) {
            throw new IllegalArgumentException("Invalid username or password");
        }
        String token = UUID.randomUUID().toString();
        store.tokens.put(token, request.username());
        return new LoginResponse(token, store.users.get(request.username()));
    }

    @GetMapping("/knowledge-bases")
    List<KnowledgeBaseView> knowledgeBases(@RequestHeader("Authorization") String authorization) {
        UserView user = authenticated(authorization);
        return store.knowledgeBases.values().stream()
                .filter(kb -> user.knowledgeBaseIds().contains(kb.id()))
                .toList();
    }

    @PostMapping("/knowledge-bases")
    KnowledgeBaseView createKnowledgeBase(@RequestHeader("Authorization") String authorization,
                                          @RequestBody CreateKnowledgeBaseRequest request) {
        UserView user = authenticated(authorization);
        String id = "kb-" + UUID.randomUUID();
        KnowledgeBaseView kb = new KnowledgeBaseView(id, request.name(), request.description(), List.of(user.id()));
        store.knowledgeBases.put(id, kb);
        return kb;
    }

    @PostMapping("/documents/upload")
    DocumentView upload(@RequestHeader("Authorization") String authorization, @RequestBody UploadDocumentRequest request) {
        UserView user = authenticated(authorization);
        ensureKbAccess(user, request.knowledgeBaseId());
        String id = "doc-" + UUID.randomUUID();
        DocumentView doc = new DocumentView(id, request.knowledgeBaseId(), request.filename(), "INDEXING", Instant.now());
        store.documents.put(id, doc);
        String contentHash = contentHash(request.content());
        Map<String, Object> payload = Map.of(
                "document_id", id,
                "knowledge_base_id", request.knowledgeBaseId(),
                "filename", request.filename(),
                "content", request.content(),
                "content_hash", contentHash,
                "allowed_user_ids", store.knowledgeBases.get(request.knowledgeBaseId()).allowedUserIds()
        );
        AiIndexResponse indexResponse;
        try {
            indexResponse = indexDocument(payload);
            String indexedDocumentId = indexResponse.document_id();
            DocumentView indexedDoc = store.documents.get(indexedDocumentId);
            if (indexedDoc == null) {
                indexedDoc = new DocumentView(indexedDocumentId, request.knowledgeBaseId(), request.filename(), indexResponse.status(), doc.createdAt());
            } else {
                indexedDoc = new DocumentView(indexedDoc.id(), indexedDoc.knowledgeBaseId(), indexedDoc.filename(), indexResponse.status(), indexedDoc.createdAt());
            }
            store.documents.put(indexedDocumentId, indexedDoc);
            if (!indexedDocumentId.equals(id)) {
                store.documents.remove(id);
            }
        } catch (Exception ex) {
            store.documents.put(id, new DocumentView(id, request.knowledgeBaseId(), request.filename(), "FAILED", doc.createdAt()));
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI indexing failed: " + rootMessage(ex), ex);
        }
        if (!indexResponse.duplicate()) {
            try {
                rabbitTemplate.convertAndSend(documentQueue, payload);
            } catch (Exception ignored) {
                // RabbitMQ is an async acceleration path for the demo; synchronous indexing above is authoritative.
            }
        }
        return store.documents.get(indexResponse.document_id());
    }

    @RabbitListener(queues = "${rag.rabbit.document-index-queue}")
    void handleDocumentIndex(Map<String, Object> payload) {
        indexDocument(payload);
        String documentId = String.valueOf(payload.get("document_id"));
        DocumentView doc = store.documents.get(documentId);
        if (doc != null) {
            store.documents.put(documentId, new DocumentView(doc.id(), doc.knowledgeBaseId(), doc.filename(), "READY", doc.createdAt()));
        }
    }

    @GetMapping("/documents/{id}")
    DocumentView document(@RequestHeader("Authorization") String authorization, @PathVariable("id") String id) {
        UserView user = authenticated(authorization);
        DocumentView doc = Optional.ofNullable(store.documents.get(id)).orElseThrow();
        ensureKbAccess(user, doc.knowledgeBaseId());
        return doc;
    }

    @PostMapping("/chat/sessions")
    ChatSessionView createSession(@RequestHeader("Authorization") String authorization,
                                  @RequestBody CreateChatSessionRequest request) {
        UserView user = authenticated(authorization);
        List<String> requestedKbs = request.knowledgeBaseIds() == null ? List.of() : request.knowledgeBaseIds();
        List<String> visible = requestedKbs.stream()
                .filter(user.knowledgeBaseIds()::contains)
                .toList();
        String id = "chat-" + UUID.randomUUID();
        ChatSessionView session = new ChatSessionView(id, user.id(), request.title(), visible, Instant.now());
        store.sessions.put(id, session);
        store.messages.put(id, new CopyOnWriteArrayList<>());
        return session;
    }

    @GetMapping("/chat/sessions/{id}/messages")
    List<ChatMessageView> messages(@RequestHeader("Authorization") String authorization, @PathVariable("id") String id) {
        UserView user = authenticated(authorization);
        ChatSessionView session = Optional.ofNullable(store.sessions.get(id)).orElseThrow();
        if (!session.userId().equals(user.id())) {
            throw new IllegalArgumentException("Cannot access this chat session");
        }
        return store.messages.getOrDefault(id, List.of());
    }

    @PostMapping(value = "/chat/sessions/{id}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter stream(@RequestHeader("Authorization") String authorization, @PathVariable("id") String id, @RequestBody ChatRequest request) {
        UserView user = authenticated(authorization);
        ChatSessionView session = Optional.ofNullable(store.sessions.get(id)).orElseThrow();
        if (!session.userId().equals(user.id())) {
            throw new IllegalArgumentException("Cannot access this chat session");
        }
        store.messages.get(id).add(new ChatMessageView("msg-" + UUID.randomUUID(), id, "user", request.question(), Instant.now()));
        SseEmitter emitter = new SseEmitter(120_000L);
        new Thread(() -> {
            try {
                Map<String, Object> payload = Map.of(
                        "user_id", user.id(),
                        "session_id", id,
                        "question", request.question(),
                        "knowledge_base_ids", session.knowledgeBaseIds()
                );
                String answer = streamAiChat(payload, emitter);
                store.messages.get(id).add(new ChatMessageView("msg-" + UUID.randomUUID(), id, "assistant", answer, Instant.now()));
                emitter.complete();
            } catch (Exception ex) {
                try {
                    emitter.send(SseEmitter.event().name("error").data("AI chat failed: " + rootMessage(ex)));
                } catch (IOException ignored) {
                }
                emitter.complete();
            }
        }).start();
        return emitter;
    }

    private String streamAiChat(Map<String, Object> payload, SseEmitter emitter) {
        HttpURLConnection connection = null;
        StringBuilder answer = new StringBuilder();
        try {
            byte[] json = objectMapper.writeValueAsBytes(payload);
            connection = (HttpURLConnection) aiServiceUri.resolve("ai/chat/stream").toURL().openConnection();
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setConnectTimeout(5_000);
            connection.setReadTimeout(120_000);
            connection.setRequestProperty("Content-Type", MediaType.APPLICATION_JSON_VALUE + "; charset=UTF-8");
            connection.setRequestProperty("Accept", MediaType.TEXT_EVENT_STREAM_VALUE);
            connection.setFixedLengthStreamingMode(json.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(json);
            }
            int status = connection.getResponseCode();
            if (status >= 400) {
                String body = connection.getErrorStream() == null ? "" : new String(connection.getErrorStream().readAllBytes(), StandardCharsets.UTF_8);
                throw new IllegalStateException("AI service returned " + status + ": " + body);
            }

            try (BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8))) {
                String event = "message";
                List<String> dataLines = new ArrayList<>();
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.isBlank()) {
                        dispatchAiEvent(emitter, answer, event, String.join("\n", dataLines));
                        event = "message";
                        dataLines.clear();
                        continue;
                    }
                    if (line.startsWith("event:")) {
                        event = line.substring("event:".length()).trim();
                    } else if (line.startsWith("data:")) {
                        dataLines.add(line.substring("data:".length()).stripLeading());
                    }
                }
                if (!dataLines.isEmpty()) {
                    dispatchAiEvent(emitter, answer, event, String.join("\n", dataLines));
                }
            }
            return answer.toString();
        } catch (IOException ex) {
            throw new IllegalStateException("Cannot stream AI service: " + ex.getMessage(), ex);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void dispatchAiEvent(SseEmitter emitter, StringBuilder answer, String event, String data) throws IOException {
        if (data == null || data.isEmpty()) {
            return;
        }
        switch (event) {
            case "tool" -> emitter.send(SseEmitter.event().name("tool").data(data));
            case "token" -> {
                answer.append(data);
                emitter.send(SseEmitter.event().name("token").data(data));
            }
            case "error" -> emitter.send(SseEmitter.event().name("error").data(data));
            case "done" -> emitter.send(SseEmitter.event().name("done").data(data));
            default -> emitter.send(SseEmitter.event().name(event).data(data));
        }
    }

    private UserView authenticated(String authorization) {
        String token = authorization == null ? "" : authorization.replace("Bearer ", "");
        return store.requireUser(token);
    }

    private void ensureKbAccess(UserView user, String knowledgeBaseId) {
        if (!user.knowledgeBaseIds().contains(knowledgeBaseId)) {
            throw new IllegalArgumentException("No permission for knowledge base " + knowledgeBaseId);
        }
    }

    private AiIndexResponse indexDocument(Map<String, Object> payload) {
        return postJson("ai/documents/index", payload, AiIndexResponse.class);
    }

    private <T> T postJson(String path, Map<String, Object> payload, Class<T> responseType) {
        HttpURLConnection connection = null;
        try {
            byte[] json = objectMapper.writeValueAsBytes(payload);
            connection = (HttpURLConnection) aiServiceUri.resolve(path).toURL().openConnection();
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setConnectTimeout(5_000);
            connection.setReadTimeout(30_000);
            connection.setRequestProperty("Content-Type", MediaType.APPLICATION_JSON_VALUE + "; charset=UTF-8");
            connection.setRequestProperty("Accept", MediaType.APPLICATION_JSON_VALUE);
            connection.setFixedLengthStreamingMode(json.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(json);
            }
            int status = connection.getResponseCode();
            if (status >= 400) {
                String body = connection.getErrorStream() == null ? "" : new String(connection.getErrorStream().readAllBytes(), StandardCharsets.UTF_8);
                throw new IllegalStateException("AI service returned " + status + ": " + body);
            }
            if (responseType == Void.class) {
                return null;
            }
            String body = new String(connection.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            return objectMapper.readValue(body, responseType);
        } catch (IOException ex) {
            throw new IllegalStateException("Cannot call AI service: " + ex.getMessage(), ex);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
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
