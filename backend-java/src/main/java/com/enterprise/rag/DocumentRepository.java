package com.enterprise.rag;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

@Repository
class DocumentRepository {
    private final JdbcTemplate jdbc;

    DocumentRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    void markIndexed(AiIndexResponse response, String fallbackDocumentId, String knowledgeBaseId, String filename, Instant createdAt) {
        String documentId = response.document_id();
        Optional<DocumentView> existing = get(documentId);
        if (existing.isPresent()) {
            jdbc.update("""
                    UPDATE documents
                    SET status = ?, chunk_count = ?
                    WHERE id = ?
                    """, response.status(), response.chunk_count(), documentId);
        } else {
            jdbc.update("""
                    INSERT INTO documents (id, knowledge_base_id, filename, status, chunk_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, documentId, knowledgeBaseId, filename, response.status(), response.chunk_count(), Timestamp.from(createdAt));
        }
        if (!documentId.equals(fallbackDocumentId) && get(fallbackDocumentId).isPresent()) {
            jdbc.update("DELETE FROM documents WHERE id = ?", fallbackDocumentId);
        }
    }

    void markFailed(String id, String knowledgeBaseId, String filename, String contentHash) {
        jdbc.update("""
                INSERT INTO documents (id, knowledge_base_id, filename, status, content_hash, chunk_count)
                VALUES (?, ?, ?, 'FAILED', ?, 0)
                ON CONFLICT (id) DO UPDATE SET status = 'FAILED'
                """, id, knowledgeBaseId, filename, contentHash);
    }

    Optional<DocumentView> get(String id) {
        return jdbc.query("""
                SELECT id, knowledge_base_id, filename, status, created_at
                FROM documents
                WHERE id = ?
                """, (rs, rowNum) -> new DocumentView(
                        rs.getString("id"),
                        rs.getString("knowledge_base_id"),
                        rs.getString("filename"),
                        rs.getString("status"),
                        rs.getTimestamp("created_at").toInstant()
                ), id).stream().findFirst();
    }
}
