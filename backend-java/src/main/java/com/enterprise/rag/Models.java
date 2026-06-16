package com.enterprise.rag;

import java.time.Instant;
import java.util.List;
import java.util.Map;

record RegisterRequest(String username, String password) {}
record LoginRequest(String username, String password) {}
record LoginResponse(String token, UserView user) {}
record UserView(String id, String username, boolean disabled, List<String> roles, List<String> knowledgeBaseIds) {}
record RoleView(String id, String name, String description, boolean systemRole, List<String> knowledgeBaseIds) {}
record CreateRoleRequest(String name, String description) {}
record KnowledgeBaseView(String id, String name, String description) {}
record CreateKnowledgeBaseRequest(String name, String description) {}
record UploadDocumentRequest(String knowledgeBaseId, String filename, String content) {}
record DocumentView(String id, String knowledgeBaseId, String filename, String status, Instant createdAt) {}
record CreateChatSessionRequest(String title, List<String> knowledgeBaseIds) {}
record ChatSessionView(String id, String userId, String title, List<String> knowledgeBaseIds, Instant createdAt) {}
record ChatMessageView(String id, String sessionId, String role, String content, Instant createdAt) {}
record ChatRequest(String question) {}
record AssignUserRolesRequest(List<String> roleIds) {}
record AssignRoleKnowledgeBasesRequest(List<String> knowledgeBaseIds) {}
record ResetPasswordRequest(String password) {}
record SetUserDisabledRequest(boolean disabled) {}
record AgentResponse(String answer, List<Map<String, Object>> citations, List<Map<String, Object>> tool_calls) {}
record AiIndexResponse(String document_id, String status, int chunk_count, boolean duplicate) {}
record CurrentUser(String id, String username, boolean disabled, List<String> roles, List<String> knowledgeBaseIds) {
    boolean isAdmin() {
        return roles.contains("ADMIN");
    }
}
