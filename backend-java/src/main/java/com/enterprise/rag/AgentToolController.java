package com.enterprise.rag;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@RestController
class AgentToolController {
    private final UserRepository users;
    private final DocumentRepository documents;
    private final AuthorizationService authorization;
    private final String internalToken;

    AgentToolController(UserRepository users,
                        DocumentRepository documents,
                        AuthorizationService authorization,
                        @Value("${rag.agent-internal-token:}") String internalToken) {
        this.users = users;
        this.documents = documents;
        this.authorization = authorization;
        this.internalToken = internalToken == null ? "" : internalToken;
    }

    @GetMapping("/internal/agent/documents/{documentId}")
    AgentDocumentStatus documentStatus(
            @RequestHeader(value = "X-Agent-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-Acting-User-Id", required = false) String userId,
            @PathVariable String documentId) {
        requireTrustedAgent(serviceToken);
        if (userId == null || userId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少 acting user ID");
        }
        UserView user = users.findAccountById(userId)
                .map(account -> users.userView(account.id()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户不存在"));
        if (user.disabled()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "用户已被禁用");
        }
        AgentDocumentStatus document = documents.getAgentStatus(documentId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "文档不存在"));
        CurrentUser currentUser = new CurrentUser(
                user.id(), user.username(), user.disabled(), user.roles(), user.knowledgeBaseIds());
        authorization.requireKnowledgeBaseAccess(currentUser, document.knowledgeBaseId());
        return document;
    }

    private void requireTrustedAgent(String suppliedToken) {
        if (internalToken.isBlank()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Agent internal token is not configured");
        }
        byte[] expected = internalToken.getBytes(StandardCharsets.UTF_8);
        byte[] supplied = (suppliedToken == null ? "" : suppliedToken).getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expected, supplied)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid agent service token");
        }
    }
}
