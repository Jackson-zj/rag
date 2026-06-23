package com.enterprise.rag;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Component
class AiClient {
    private final ObjectMapper objectMapper;
    private final URI aiServiceUri;

    AiClient(ObjectMapper objectMapper, @Value("${rag.ai-service-url}") String aiServiceUrl) {
        this.objectMapper = objectMapper;
        this.aiServiceUri = URI.create(aiServiceUrl.endsWith("/") ? aiServiceUrl : aiServiceUrl + "/");
    }

    AiIndexResponse indexDocument(Map<String, Object> payload) {
        return postJson("ai/documents/index", payload, AiIndexResponse.class);
    }

    String streamChat(Map<String, Object> payload, SseEmitter emitter) {
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
            case "tool_result" -> emitter.send(SseEmitter.event().name("tool_result").data(data));
            case "citation" -> emitter.send(SseEmitter.event().name("citation").data(data));
            case "token" -> {
                answer.append(data);
                emitter.send(SseEmitter.event().name("token").data(data));
            }
            case "error" -> emitter.send(SseEmitter.event().name("error").data(data));
            case "done" -> emitter.send(SseEmitter.event().name("done").data(data));
            default -> emitter.send(SseEmitter.event().name(event).data(data));
        }
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
}
