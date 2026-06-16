package com.enterprise.rag;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
class KnowledgeBaseRepository {
    private final JdbcTemplate jdbc;
    private final UserRepository users;

    KnowledgeBaseRepository(JdbcTemplate jdbc, UserRepository users) {
        this.jdbc = jdbc;
        this.users = users;
    }

    List<KnowledgeBaseView> visibleFor(CurrentUser user) {
        if (user.isAdmin()) {
            return jdbc.query("""
                    SELECT id, name, description
                    FROM knowledge_bases
                    ORDER BY name
                    """, this::mapKnowledgeBase);
        }
        if (user.knowledgeBaseIds().isEmpty()) {
            return List.of();
        }
        return jdbc.query("""
                SELECT id, name, description
                FROM knowledge_bases
                ORDER BY name
                """, this::mapKnowledgeBase)
                .stream()
                .filter(kb -> user.knowledgeBaseIds().contains(kb.id()))
                .toList();
    }

    KnowledgeBaseView create(CreateKnowledgeBaseRequest request) {
        String id = "kb-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO knowledge_bases (id, name, description)
                VALUES (?, ?, ?)
                """, id, request.name(), request.description() == null ? "" : request.description());
        jdbc.update("""
                INSERT INTO role_knowledge_bases (role_id, knowledge_base_id)
                VALUES (?, ?)
                ON CONFLICT DO NOTHING
                """, users.requiredRoleIdByName("ADMIN"), id);
        return get(id);
    }

    KnowledgeBaseView get(String id) {
        return jdbc.query("""
                SELECT id, name, description
                FROM knowledge_bases
                WHERE id = ?
                """, this::mapKnowledgeBase, id).stream().findFirst().orElseThrow();
    }

    private KnowledgeBaseView mapKnowledgeBase(java.sql.ResultSet rs, int rowNum) throws java.sql.SQLException {
        return new KnowledgeBaseView(rs.getString("id"), rs.getString("name"), rs.getString("description"));
    }
}
