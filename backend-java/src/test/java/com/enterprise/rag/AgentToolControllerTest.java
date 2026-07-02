package com.enterprise.rag;

import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AgentToolControllerTest {
    private final UserRepository users = mock(UserRepository.class);
    private final DocumentRepository documents = mock(DocumentRepository.class);
    private final AuthorizationService authorization = new AuthorizationService();

    @Test
    void rejectsMissingConfigurationAndBadToken() {
        AgentToolController unconfigured = new AgentToolController(users, documents, authorization, "");
        ResponseStatusException unavailable = assertThrows(ResponseStatusException.class, () ->
                unconfigured.documentStatus("anything", "u-user", "doc-1"));
        assertEquals(503, unavailable.getStatusCode().value());

        AgentToolController configured = new AgentToolController(users, documents, authorization, "secret");
        ResponseStatusException unauthorized = assertThrows(ResponseStatusException.class, () ->
                configured.documentStatus("wrong", "u-user", "doc-1"));
        assertEquals(401, unauthorized.getStatusCode().value());
        verifyNoInteractions(documents);
    }

    @Test
    void rejectsDisabledAndUnauthorizedUsers() {
        AgentToolController controller = new AgentToolController(users, documents, authorization, "secret");
        UserRepository.UserAccount account = new UserRepository.UserAccount("u-user", "user", "hash", false);
        when(users.findAccountById("u-user")).thenReturn(Optional.of(account));
        when(users.userView("u-user")).thenReturn(new UserView("u-user", "user", true, List.of("USER"), List.of("kb-hr")));

        ResponseStatusException disabled = assertThrows(ResponseStatusException.class, () ->
                controller.documentStatus("secret", "u-user", "doc-1"));
        assertEquals(403, disabled.getStatusCode().value());

        when(users.userView("u-user")).thenReturn(new UserView("u-user", "user", false, List.of("USER"), List.of("kb-hr")));
        when(documents.getAgentStatus("doc-tech")).thenReturn(Optional.of(
                new AgentDocumentStatus("doc-tech", "kb-tech", "architecture.pdf", "READY", 4, Instant.now())));
        ResponseStatusException forbidden = assertThrows(ResponseStatusException.class, () ->
                controller.documentStatus("secret", "u-user", "doc-tech"));
        assertEquals(403, forbidden.getStatusCode().value());
    }

    @Test
    void returnsAuthorizedDocumentStatus() {
        AgentToolController controller = new AgentToolController(users, documents, authorization, "secret");
        UserRepository.UserAccount account = new UserRepository.UserAccount("u-user", "user", "hash", false);
        AgentDocumentStatus expected = new AgentDocumentStatus(
                "doc-1", "kb-hr", "policy.pdf", "READY", 12, Instant.parse("2026-06-24T00:00:00Z"));
        when(users.findAccountById("u-user")).thenReturn(Optional.of(account));
        when(users.userView("u-user")).thenReturn(new UserView("u-user", "user", false, List.of("USER"), List.of("kb-hr")));
        when(documents.getAgentStatus("doc-1")).thenReturn(Optional.of(expected));

        AgentDocumentStatus actual = controller.documentStatus("secret", "u-user", "doc-1");
        assertEquals(expected, actual);
    }
}
