package com.enterprise.rag;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
class ChatRepository {
    private final JdbcTemplate jdbc;

    ChatRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    ChatSessionView createSession(String userId, String title, List<String> knowledgeBaseIds) {
        String id = "chat-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO chat_sessions (id, user_id, title)
                VALUES (?, ?, ?)
                """, id, userId, title == null || title.isBlank() ? "企业知识库问答" : title);
        for (String kbId : knowledgeBaseIds) {
            jdbc.update("""
                    INSERT INTO chat_session_knowledge_bases (session_id, knowledge_base_id)
                    VALUES (?, ?)
                    ON CONFLICT DO NOTHING
                    """, id, kbId);
        }
        return getSession(id).orElseThrow();
    }

    List<ChatSessionView> listSessions(String userId) {
        return jdbc.query("""
                SELECT id
                FROM chat_sessions
                WHERE user_id = ?
                ORDER BY created_at DESC
                """, (rs, rowNum) -> rs.getString("id"), userId).stream().map(id -> getSession(id).orElseThrow()).toList();
    }

    ChatSessionView renameSession(String id, String title) {
        jdbc.update("UPDATE chat_sessions SET title = ? WHERE id = ?", title, id);
        return getSession(id).orElseThrow();
    }

    java.util.Optional<ChatSessionView> getSession(String id) {
        return jdbc.query("""
                SELECT id, user_id, title, created_at
                FROM chat_sessions
                WHERE id = ?
                """, (rs, rowNum) -> new ChatSessionView(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getString("title"),
                        knowledgeBaseIdsForSession(rs.getString("id")),
                        rs.getTimestamp("created_at").toInstant()
                ), id).stream().findFirst();
    }

    List<ChatMessageView> messages(String sessionId) {
        return allMessages(sessionId);
    }

    List<ChatMessageView> messages(String sessionId, Integer rounds) {
        List<ChatMessageView> all = allMessages(sessionId);
        if (rounds == null || rounds <= 0) {
            return all;
        }
        int userTurnsSeen = 0;
        int start = 0;
        for (int i = all.size() - 1; i >= 0; i -= 1) {
            if ("user".equals(all.get(i).role())) {
                userTurnsSeen += 1;
                if (userTurnsSeen == rounds) {
                    start = i;
                    break;
                }
            }
        }
        if (userTurnsSeen < rounds) {
            return all;
        }
        return all.subList(start, all.size());
    }

    private List<ChatMessageView> allMessages(String sessionId) {
        return jdbc.query("""
                SELECT id, session_id, role, content, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at
                """, (rs, rowNum) -> new ChatMessageView(
                        rs.getString("id"),
                        rs.getString("session_id"),
                        rs.getString("role"),
                        rs.getString("content"),
                        rs.getTimestamp("created_at").toInstant()
                ), sessionId);
    }

    void addMessage(String sessionId, String role, String content) {
        jdbc.update("""
                INSERT INTO chat_messages (id, session_id, role, content)
                VALUES (?, ?, ?, ?)
                """, "msg-" + UUID.randomUUID(), sessionId, role, content);
    }

    private List<String> knowledgeBaseIdsForSession(String sessionId) {
        return jdbc.query("""
                SELECT knowledge_base_id
                FROM chat_session_knowledge_bases
                WHERE session_id = ?
                ORDER BY knowledge_base_id
                """, (rs, rowNum) -> rs.getString("knowledge_base_id"), sessionId);
    }
}
