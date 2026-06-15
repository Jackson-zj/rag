package com.enterprise.rag;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.mockito.Mockito.mock;

class ApiControllerTest {
    private final ObjectMapper objectMapper = new ObjectMapper();
    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void uploadReturnsExistingDocumentWhenAiReportsDuplicate() throws Exception {
        List<Map<String, Object>> payloads = new ArrayList<>();
        List<String> firstDocumentId = new ArrayList<>();
        ApiController controller = controllerWithAiHandler(exchange -> {
            Map<String, Object> payload = readJson(exchange);
            payloads.add(payload);
            String requestedDocumentId = String.valueOf(payload.get("document_id"));
            boolean duplicate = !firstDocumentId.isEmpty();
            if (!duplicate) {
                firstDocumentId.add(requestedDocumentId);
            }
            writeJson(exchange, Map.of(
                    "document_id", duplicate ? firstDocumentId.get(0) : requestedDocumentId,
                    "status", "READY",
                    "chunk_count", 1,
                    "duplicate", duplicate
            ));
        });

        String auth = bearerToken(controller);
        DocumentView first = controller.upload(auth, new UploadDocumentRequest("kb-hr", "policy.txt", "Line one\r\nLine two"));
        DocumentView duplicate = controller.upload(auth, new UploadDocumentRequest("kb-hr", "policy-copy.txt", "Line one\nLine two"));

        assertEquals(first.id(), duplicate.id());
        assertEquals("READY", duplicate.status());
        assertEquals(2, payloads.size());
        assertEquals(payloads.get(0).get("content_hash"), payloads.get(1).get("content_hash"));
    }

    @Test
    void uploadCreatesSeparateDocumentsForDifferentContentHashes() throws Exception {
        ApiController controller = controllerWithAiHandler(exchange -> {
            Map<String, Object> payload = readJson(exchange);
            String requestedDocumentId = String.valueOf(payload.get("document_id"));
            writeJson(exchange, Map.of(
                    "document_id", requestedDocumentId,
                    "status", "READY",
                    "chunk_count", 1,
                    "duplicate", false
            ));
        });

        String auth = bearerToken(controller);
        DocumentView first = controller.upload(auth, new UploadDocumentRequest("kb-hr", "policy-a.txt", "Policy A"));
        DocumentView second = controller.upload(auth, new UploadDocumentRequest("kb-hr", "policy-b.txt", "Policy B"));

        assertNotEquals(first.id(), second.id());
    }

    private ApiController controllerWithAiHandler(ThrowingHttpHandler handler) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/ai/documents/index", exchange -> {
            try {
                handler.handle(exchange);
            } catch (Exception ex) {
                byte[] body = ex.getMessage().getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(500, body.length);
                exchange.getResponseBody().write(body);
                exchange.close();
            }
        });
        server.start();
        String aiServiceUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        return new ApiController(objectMapper, mock(RabbitTemplate.class), aiServiceUrl, "document.index");
    }

    private String bearerToken(ApiController controller) {
        return "Bearer " + controller.login(new LoginRequest("admin", "admin123")).token();
    }

    private Map<String, Object> readJson(HttpExchange exchange) throws IOException {
        byte[] body = exchange.getRequestBody().readAllBytes();
        return objectMapper.readValue(body, new TypeReference<>() {});
    }

    private void writeJson(HttpExchange exchange, Map<String, Object> payload) throws IOException {
        byte[] body = objectMapper.writeValueAsBytes(payload);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }

    @FunctionalInterface
    interface ThrowingHttpHandler {
        void handle(HttpExchange exchange) throws Exception;
    }
}
