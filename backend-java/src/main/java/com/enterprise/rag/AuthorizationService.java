package com.enterprise.rag;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

@Service
class AuthorizationService {
    void requireAdmin(CurrentUser user) {
        if (!user.isAdmin()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "需要管理员权限");
        }
    }

    void requireKnowledgeBaseAccess(CurrentUser user, String knowledgeBaseId) {
        if (user.isAdmin()) {
            return;
        }
        if (!user.knowledgeBaseIds().contains(knowledgeBaseId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "无权访问知识库 " + knowledgeBaseId);
        }
    }

    List<String> allowedKnowledgeBases(CurrentUser user, List<String> requested) {
        if (requested == null || requested.isEmpty()) {
            return user.knowledgeBaseIds();
        }
        List<String> filtered = requested.stream()
                .filter(user.knowledgeBaseIds()::contains)
                .toList();
        if (filtered.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "没有可用于本次会话的知识库权限");
        }
        return filtered;
    }
}
