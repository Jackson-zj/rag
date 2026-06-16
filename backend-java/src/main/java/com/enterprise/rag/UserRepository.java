package com.enterprise.rag;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

@Repository
class UserRepository {
    private final JdbcTemplate jdbc;

    UserRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    void seedDefaults(PasswordEncoder passwordEncoder) {
        ensureSchema();
        jdbc.update("""
                INSERT INTO roles (id, name, description, system_role)
                VALUES
                  ('role-admin', 'ADMIN', '系统管理员', true),
                  ('role-user', 'USER', '普通用户', true),
                  ('role-analyst', 'ANALYST', '分析用户', true)
                ON CONFLICT (id) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    system_role = EXCLUDED.system_role,
                    updated_at = now()
                """);
        jdbc.update("""
                INSERT INTO knowledge_bases (id, name, description)
                VALUES
                  ('kb-hr', 'HR Policy KB', 'Employee handbook, attendance, reimbursement, and performance policy.'),
                  ('kb-tech', 'Tech Architecture KB', 'Service governance, deployment standards, and incident playbooks.')
                ON CONFLICT (id) DO NOTHING
                """);
        createSeedUser("u-admin", "admin", "admin123", "role-admin", passwordEncoder);
        createSeedUser("u-analyst", "analyst", "analyst123", "role-analyst", passwordEncoder);
        jdbc.update("""
                INSERT INTO role_knowledge_bases (role_id, knowledge_base_id)
                SELECT 'role-admin', id FROM knowledge_bases
                ON CONFLICT DO NOTHING
                """);
        jdbc.update("""
                INSERT INTO role_knowledge_bases (role_id, knowledge_base_id)
                VALUES ('role-analyst', 'kb-hr')
                ON CONFLICT DO NOTHING
                """);
    }

    private void ensureSchema() {
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  disabled BOOLEAN NOT NULL DEFAULT false,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS roles (
                  id TEXT PRIMARY KEY,
                  name TEXT UNIQUE NOT NULL,
                  description TEXT NOT NULL DEFAULT '',
                  system_role BOOLEAN NOT NULL DEFAULT false,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  description TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """);
        jdbc.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT false");
        jdbc.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()");
        jdbc.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()");
        jdbc.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''");
        jdbc.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS system_role BOOLEAN NOT NULL DEFAULT false");
        jdbc.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()");
        jdbc.execute("ALTER TABLE roles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()");
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS user_roles (
                  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                  PRIMARY KEY (user_id, role_id)
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS role_knowledge_bases (
                  role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                  PRIMARY KEY (role_id, knowledge_base_id)
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                  id TEXT PRIMARY KEY,
                  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                  filename TEXT NOT NULL,
                  status TEXT NOT NULL,
                  content_hash TEXT,
                  chunk_count INT NOT NULL DEFAULT 0,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """);
        jdbc.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT");
        jdbc.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INT NOT NULL DEFAULT 0");
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  title TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS chat_session_knowledge_bases (
                  session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                  PRIMARY KEY (session_id, knowledge_base_id)
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                  content TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """);
    }

    private void createSeedUser(String id, String username, String password, String roleId, PasswordEncoder encoder) {
        Integer count = jdbc.queryForObject("SELECT count(*) FROM users WHERE id = ? OR username = ?", Integer.class, id, username);
        if (count != null && count == 0) {
            jdbc.update("""
                    INSERT INTO users (id, username, password_hash, disabled)
                    VALUES (?, ?, ?, false)
                    """, id, username, encoder.encode(password));
        }
        jdbc.update("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?) ON CONFLICT DO NOTHING", id, roleId);
    }

    Optional<UserAccount> findAccountByUsername(String username) {
        List<UserAccount> users = jdbc.query("""
                SELECT id, username, password_hash, disabled
                FROM users
                WHERE username = ?
                """, this::mapAccount, username);
        return users.stream().findFirst();
    }

    Optional<UserAccount> findAccountById(String id) {
        List<UserAccount> users = jdbc.query("""
                SELECT id, username, password_hash, disabled
                FROM users
                WHERE id = ?
                """, this::mapAccount, id);
        return users.stream().findFirst();
    }

    UserView createUser(String username, String passwordHash, String defaultRoleId) {
        String id = "u-" + java.util.UUID.randomUUID();
        try {
            jdbc.update("""
                    INSERT INTO users (id, username, password_hash, disabled)
                    VALUES (?, ?, ?, false)
                    """, id, username, passwordHash);
            jdbc.update("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", id, defaultRoleId);
            return userView(id);
        } catch (DataIntegrityViolationException ex) {
            throw ex;
        }
    }

    String requiredRoleIdByName(String name) {
        return jdbc.query("""
                SELECT id FROM roles WHERE name = ?
                """, (rs, rowNum) -> rs.getString("id"), name)
                .stream()
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("Missing role " + name));
    }

    UserView userView(String userId) {
        UserAccount account = findAccountById(userId).orElseThrow();
        List<String> roles = roleNamesForUser(userId);
        return new UserView(account.id(), account.username(), account.disabled(), roles, knowledgeBaseIdsForUser(userId, roles));
    }

    List<UserView> listUsers() {
        return jdbc.query("SELECT id FROM users ORDER BY username", (rs, rowNum) -> rs.getString("id"))
                .stream()
                .map(this::userView)
                .toList();
    }

    List<RoleView> listRoles() {
        return jdbc.query("""
                SELECT id, name, description, system_role
                FROM roles
                ORDER BY system_role DESC, name
                """, (rs, rowNum) -> new RoleView(
                        rs.getString("id"),
                        rs.getString("name"),
                        rs.getString("description"),
                        rs.getBoolean("system_role"),
                        knowledgeBaseIdsForRole(rs.getString("id"))
                ));
    }

    RoleView createRole(String name, String description) {
        String id = "role-" + java.util.UUID.randomUUID();
        jdbc.update("""
                INSERT INTO roles (id, name, description, system_role)
                VALUES (?, ?, ?, false)
                """, id, name, description == null ? "" : description);
        return roleView(id);
    }

    RoleView roleView(String roleId) {
        return jdbc.query("""
                SELECT id, name, description, system_role
                FROM roles
                WHERE id = ?
                """, (rs, rowNum) -> new RoleView(
                        rs.getString("id"),
                        rs.getString("name"),
                        rs.getString("description"),
                        rs.getBoolean("system_role"),
                        knowledgeBaseIdsForRole(rs.getString("id"))
                ), roleId).stream().findFirst().orElseThrow();
    }

    void replaceUserRoles(String userId, List<String> roleIds) {
        jdbc.update("DELETE FROM user_roles WHERE user_id = ?", userId);
        for (String roleId : safeList(roleIds)) {
            jdbc.update("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?) ON CONFLICT DO NOTHING", userId, roleId);
        }
    }

    void replaceRoleKnowledgeBases(String roleId, List<String> knowledgeBaseIds) {
        jdbc.update("DELETE FROM role_knowledge_bases WHERE role_id = ?", roleId);
        for (String kbId : safeList(knowledgeBaseIds)) {
            jdbc.update("""
                    INSERT INTO role_knowledge_bases (role_id, knowledge_base_id)
                    VALUES (?, ?)
                    ON CONFLICT DO NOTHING
                    """, roleId, kbId);
        }
    }

    void setDisabled(String userId, boolean disabled) {
        jdbc.update("UPDATE users SET disabled = ?, updated_at = now() WHERE id = ?", disabled, userId);
    }

    void resetPassword(String userId, String passwordHash) {
        jdbc.update("UPDATE users SET password_hash = ?, updated_at = now() WHERE id = ?", passwordHash, userId);
    }

    boolean hasRole(String userId, String roleName) {
        Integer count = jdbc.queryForObject("""
                SELECT count(*)
                FROM user_roles ur
                JOIN roles r ON r.id = ur.role_id
                WHERE ur.user_id = ? AND r.name = ?
                """, Integer.class, userId, roleName);
        return count != null && count > 0;
    }

    List<String> roleNamesForUser(String userId) {
        return jdbc.query("""
                SELECT r.name
                FROM user_roles ur
                JOIN roles r ON r.id = ur.role_id
                WHERE ur.user_id = ?
                ORDER BY r.name
                """, (rs, rowNum) -> rs.getString("name"), userId);
    }

    List<String> knowledgeBaseIdsForUser(String userId, List<String> roleNames) {
        if (roleNames.contains("ADMIN")) {
            return allKnowledgeBaseIds();
        }
        return jdbc.query("""
                SELECT DISTINCT rkb.knowledge_base_id
                FROM user_roles ur
                JOIN role_knowledge_bases rkb ON rkb.role_id = ur.role_id
                WHERE ur.user_id = ?
                ORDER BY rkb.knowledge_base_id
                """, (rs, rowNum) -> rs.getString("knowledge_base_id"), userId);
    }

    List<String> allKnowledgeBaseIds() {
        return jdbc.query("SELECT id FROM knowledge_bases ORDER BY id", (rs, rowNum) -> rs.getString("id"));
    }

    List<String> knowledgeBaseIdsForRole(String roleId) {
        return jdbc.query("""
                SELECT knowledge_base_id
                FROM role_knowledge_bases
                WHERE role_id = ?
                ORDER BY knowledge_base_id
                """, (rs, rowNum) -> rs.getString("knowledge_base_id"), roleId);
    }

    private UserAccount mapAccount(ResultSet rs, int rowNum) throws SQLException {
        return new UserAccount(
                rs.getString("id"),
                rs.getString("username"),
                rs.getString("password_hash"),
                rs.getBoolean("disabled")
        );
    }

    private List<String> safeList(List<String> values) {
        return values == null ? List.of() : new ArrayList<>(values);
    }

    record UserAccount(String id, String username, String passwordHash, boolean disabled) {}
}
