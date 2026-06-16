package com.enterprise.rag;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.sql.ResultSet;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class ApiControllerTest {
    private final AuthService auth = mock(AuthService.class);
    private final AuthorizationService authorization = new AuthorizationService();
    private final UserRepository users = mock(UserRepository.class);
    private final KnowledgeBaseRepository knowledgeBases = mock(KnowledgeBaseRepository.class);
    private final DocumentRepository documents = mock(DocumentRepository.class);
    private final ChatRepository chats = mock(ChatRepository.class);
    private final AiClient aiClient = mock(AiClient.class);
    private final RabbitTemplate rabbitTemplate = mock(RabbitTemplate.class);
    private final ApiController controller = new ApiController(
            auth,
            authorization,
            users,
            knowledgeBases,
            documents,
            chats,
            aiClient,
            rabbitTemplate,
            "document.index"
    );

    @Test
    void uploadRejectsNonAdminUsers() {
        when(auth.currentUser("Bearer user")).thenReturn(new CurrentUser(
                "u-user",
                "user",
                false,
                List.of("USER"),
                List.of("kb-hr")
        ));

        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () ->
                controller.upload("Bearer user", new UploadDocumentRequest("kb-hr", "policy.txt", "Policy")));

        assertEquals(403, ex.getStatusCode().value());
        verifyNoInteractions(aiClient);
    }

    @Test
    void uploadSendsEmptyAllowedUserIdsToAiService() {
        when(auth.currentUser("Bearer admin")).thenReturn(new CurrentUser(
                "u-admin",
                "admin",
                false,
                List.of("ADMIN"),
                List.of("kb-hr", "kb-tech")
        ));
        when(knowledgeBases.get("kb-hr")).thenReturn(new KnowledgeBaseView("kb-hr", "HR", "HR docs"));
        DocumentView ready = new DocumentView("doc-1", "kb-hr", "policy.txt", "READY", Instant.now());
        when(aiClient.indexDocument(any())).thenReturn(new AiIndexResponse("doc-1", "READY", 1, false));
        when(documents.get("doc-1")).thenReturn(Optional.of(ready));

        controller.upload("Bearer admin", new UploadDocumentRequest("kb-hr", "policy.txt", "Policy"));

        verify(documents).markIndexed(any(), any(), eq("kb-hr"), eq("policy.txt"), any());
        @SuppressWarnings("unchecked")
        var payload = (Map<String, Object>) mockingDetails(aiClient)
                .getInvocations()
                .stream()
                .filter(invocation -> invocation.getMethod().getName().equals("indexDocument"))
                .findFirst()
                .orElseThrow()
                .getArgument(0);
        assertEquals(List.of(), payload.get("allowed_user_ids"));
    }

    @Test
    void createSessionDefaultsToCurrentUsersKnowledgeBases() {
        CurrentUser user = new CurrentUser(
                "u-user",
                "user",
                false,
                List.of("USER"),
                List.of("kb-hr")
        );
        when(auth.currentUser("Bearer user")).thenReturn(user);
        ChatSessionView session = new ChatSessionView("chat-1", "u-user", "问答", List.of("kb-hr"), Instant.now());
        when(chats.createSession("u-user", "问答", List.of("kb-hr"))).thenReturn(session);

        ChatSessionView created = controller.createSession("Bearer user", new CreateChatSessionRequest("问答", null));

        assertEquals(List.of("kb-hr"), created.knowledgeBaseIds());
        verify(chats).createSession("u-user", "问答", List.of("kb-hr"));
    }

    @Test
    void userCannotReadAnotherUsersSessionMessages() {
        CurrentUser user = new CurrentUser("u-user", "user", false, List.of("USER"), List.of("kb-hr"));
        when(auth.currentUser("Bearer user")).thenReturn(user);
        when(chats.getSession("chat-other")).thenReturn(Optional.of(
                new ChatSessionView("chat-other", "u-other", "别人的会话", List.of("kb-hr"), Instant.now())
        ));

        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () ->
                controller.messages("Bearer user", "chat-other", null));

        assertEquals(403, ex.getStatusCode().value());
    }

    @Test
    void messagesWithoutRoundsReturnsAllSessionMessages() {
        CurrentUser user = new CurrentUser("u-user", "user", false, List.of("USER"), List.of("kb-hr"));
        ChatSessionView session = new ChatSessionView("chat-1", "u-user", "chat", List.of("kb-hr"), Instant.now());
        List<ChatMessageView> messages = List.of(
                new ChatMessageView("msg-1", "chat-1", "user", "Q1", Instant.now()),
                new ChatMessageView("msg-2", "chat-1", "assistant", "A1", Instant.now())
        );
        when(auth.currentUser("Bearer user")).thenReturn(user);
        when(chats.getSession("chat-1")).thenReturn(Optional.of(session));
        when(chats.messages("chat-1")).thenReturn(messages);

        List<ChatMessageView> result = controller.messages("Bearer user", "chat-1", null);

        assertEquals(messages, result);
        verify(chats).messages("chat-1");
        verify(chats, never()).messages(eq("chat-1"), any());
    }

    @Test
    void messagesWithRoundsDelegatesToRoundLimitedRepositoryQuery() {
        CurrentUser user = new CurrentUser("u-user", "user", false, List.of("USER"), List.of("kb-hr"));
        ChatSessionView session = new ChatSessionView("chat-1", "u-user", "chat", List.of("kb-hr"), Instant.now());
        List<ChatMessageView> messages = List.of(
                new ChatMessageView("msg-21", "chat-1", "user", "Q11", Instant.now()),
                new ChatMessageView("msg-22", "chat-1", "assistant", "A11", Instant.now())
        );
        when(auth.currentUser("Bearer user")).thenReturn(user);
        when(chats.getSession("chat-1")).thenReturn(Optional.of(session));
        when(chats.messages("chat-1", 10)).thenReturn(messages);

        List<ChatMessageView> result = controller.messages("Bearer user", "chat-1", 10);

        assertEquals(messages, result);
        verify(chats).messages("chat-1", 10);
        verify(chats, never()).messages("chat-1");
    }

    @Test
    void repositoryLimitsMessagesToLatestRoundsInChronologicalOrder() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ChatRepository repository = new ChatRepository(jdbc);
        List<ChatMessageView> stored = new ArrayList<>();
        Instant base = Instant.parse("2026-01-01T00:00:00Z");
        for (int round = 1; round <= 12; round += 1) {
            stored.add(new ChatMessageView("user-" + round, "chat-1", "user", "Q" + round, base.plusSeconds(round * 2L)));
            stored.add(new ChatMessageView("assistant-" + round, "chat-1", "assistant", "A" + round, base.plusSeconds(round * 2L + 1)));
        }
        stubChatRows(jdbc, stored);

        List<ChatMessageView> result = repository.messages("chat-1", 10);

        assertEquals(20, result.size());
        assertEquals("user-3", result.get(0).id());
        assertEquals("assistant-12", result.get(result.size() - 1).id());
    }

    @Test
    void repositoryReturnsAllMessagesWhenRoundsOmitted() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ChatRepository repository = new ChatRepository(jdbc);
        List<ChatMessageView> stored = List.of(
                new ChatMessageView("user-1", "chat-1", "user", "Q1", Instant.parse("2026-01-01T00:00:00Z")),
                new ChatMessageView("assistant-1", "chat-1", "assistant", "A1", Instant.parse("2026-01-01T00:00:01Z"))
        );
        stubChatRows(jdbc, stored);

        List<ChatMessageView> result = repository.messages("chat-1");

        assertEquals(stored, result);
    }

    @Test
    void nonAdminKnowledgeBaseQueryIncludesFromClause() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        UserRepository userRepository = mock(UserRepository.class);
        KnowledgeBaseRepository repository = new KnowledgeBaseRepository(jdbc, userRepository);
        CurrentUser normalUser = new CurrentUser("u-user", "user", false, List.of("USER"), List.of("kb-hr"));
        ResultSet row = mock(ResultSet.class);
        when(row.getString("id")).thenReturn("kb-hr");
        when(row.getString("name")).thenReturn("HR Policy KB");
        when(row.getString("description")).thenReturn("HR docs");
        when(jdbc.query(any(String.class), any(org.springframework.jdbc.core.RowMapper.class))).thenAnswer(invocation -> {
            String sql = invocation.getArgument(0);
            if (!sql.contains("FROM knowledge_bases")) {
                throw new AssertionError("Missing FROM clause: " + sql);
            }
            @SuppressWarnings("unchecked")
            org.springframework.jdbc.core.RowMapper<KnowledgeBaseView> mapper = invocation.getArgument(1);
            return List.of(mapper.mapRow(row, 0));
        });

        List<KnowledgeBaseView> visible = repository.visibleFor(normalUser);

        assertEquals(1, visible.size());
        assertEquals("kb-hr", visible.get(0).id());
    }

    @SuppressWarnings("unchecked")
    private void stubChatRows(JdbcTemplate jdbc, List<ChatMessageView> stored) {
        when(jdbc.query(any(String.class), any(org.springframework.jdbc.core.RowMapper.class), eq("chat-1"))).thenAnswer(invocation -> {
            org.springframework.jdbc.core.RowMapper<ChatMessageView> mapper = invocation.getArgument(1);
            List<ChatMessageView> mapped = new ArrayList<>();
            for (int index = 0; index < stored.size(); index += 1) {
                ChatMessageView message = stored.get(index);
                ResultSet row = mock(ResultSet.class);
                when(row.getString("id")).thenReturn(message.id());
                when(row.getString("session_id")).thenReturn(message.sessionId());
                when(row.getString("role")).thenReturn(message.role());
                when(row.getString("content")).thenReturn(message.content());
                when(row.getTimestamp("created_at")).thenReturn(java.sql.Timestamp.from(message.createdAt()));
                mapped.add(mapper.mapRow(row, index));
            }
            return mapped;
        });
    }
}
