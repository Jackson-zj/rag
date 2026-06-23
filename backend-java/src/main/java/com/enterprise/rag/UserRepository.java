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
        for (int employee = 1; employee <= 5; employee += 1) {
            createSeedUser("u-user" + employee, "user" + employee, "user123", "role-user", passwordEncoder);
        }
        seedEmployeeData();
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
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS attendance_records (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  attendance_date DATE NOT NULL,
                  clock_in TIME,
                  clock_out TIME,
                  status TEXT NOT NULL CHECK (status IN ('NORMAL', 'LATE', 'EARLY_LEAVE', 'ABSENT', 'LEAVE')),
                  work_minutes INT NOT NULL DEFAULT 0 CHECK (work_minutes >= 0),
                  overtime_minutes INT NOT NULL DEFAULT 0 CHECK (overtime_minutes >= 0),
                  remark TEXT NOT NULL DEFAULT '',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  UNIQUE (user_id, attendance_date)
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS employee_work_logs (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  log_date DATE NOT NULL,
                  project_name TEXT NOT NULL,
                  work_summary TEXT NOT NULL,
                  work_hours NUMERIC(4, 1) NOT NULL CHECK (work_hours >= 0 AND work_hours <= 24),
                  completion_status TEXT NOT NULL CHECK (completion_status IN ('COMPLETED', 'IN_PROGRESS', 'BLOCKED')),
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  UNIQUE (user_id, log_date)
                )
                """);
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance_records (user_id, attendance_date DESC)");
        jdbc.execute("CREATE INDEX IF NOT EXISTS idx_work_logs_user_date ON employee_work_logs (user_id, log_date DESC)");
        jdbc.execute("""
                CREATE OR REPLACE VIEW agent_attendance_records AS
                SELECT attendance.id,
                       attendance.user_id,
                       users.username,
                       attendance.attendance_date,
                       attendance.clock_in,
                       attendance.clock_out,
                       attendance.status,
                       attendance.work_minutes,
                       attendance.overtime_minutes,
                       attendance.remark
                FROM attendance_records attendance
                JOIN users ON users.id = attendance.user_id
                """);
        jdbc.execute("""
                CREATE OR REPLACE VIEW agent_employee_work_logs AS
                SELECT logs.id,
                       logs.user_id,
                       users.username,
                       logs.log_date,
                       logs.project_name,
                       logs.work_summary,
                       logs.work_hours,
                       logs.completion_status
                FROM employee_work_logs logs
                JOIN users ON users.id = logs.user_id
                """);
        jdbc.execute("""
                CREATE OR REPLACE VIEW agent_chat_sessions AS
                SELECT sessions.id,
                       sessions.user_id,
                       users.username,
                       sessions.title,
                       sessions.created_at
                FROM chat_sessions sessions
                JOIN users ON users.id = sessions.user_id
                """);
        jdbc.execute("""
                CREATE OR REPLACE VIEW agent_chat_messages AS
                SELECT messages.id,
                       messages.session_id,
                       sessions.user_id,
                       users.username,
                       messages.role,
                       messages.created_at
                FROM chat_messages messages
                JOIN chat_sessions sessions ON sessions.id = messages.session_id
                JOIN users ON users.id = sessions.user_id
                """);
    }

    private String createSeedUser(String id, String username, String password, String roleId, PasswordEncoder encoder) {
        List<String> existingIds = jdbc.query(
                "SELECT id FROM users WHERE id = ? OR username = ? ORDER BY CASE WHEN username = ? THEN 0 ELSE 1 END",
                (rs, rowNum) -> rs.getString("id"),
                id,
                username,
                username
        );
        String actualId = existingIds.stream().findFirst().orElse(null);
        if (actualId == null) {
            jdbc.update("""
                    INSERT INTO users (id, username, password_hash, disabled)
                    VALUES (?, ?, ?, false)
                    """, id, username, encoder.encode(password));
            actualId = id;
        }
        jdbc.update("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?) ON CONFLICT DO NOTHING", actualId, roleId);
        return actualId;
    }

    private void seedEmployeeData() {
        jdbc.update("""
                WITH seed_users AS (
                  SELECT id, username, row_number() OVER (ORDER BY username)::int AS user_no
                  FROM users
                  WHERE username IN ('user1', 'user2', 'user3', 'user4', 'user5')
                ),
                work_days AS (
                  SELECT work_date::date,
                         row_number() OVER (ORDER BY work_date DESC)::int AS day_no
                  FROM (
                    SELECT work_date
                    FROM generate_series(current_date - interval '10 days', current_date, interval '1 day') work_date
                    WHERE extract(isodow FROM work_date) <= 5
                    ORDER BY work_date DESC
                    LIMIT 4
                  ) recent_days
                )
                INSERT INTO attendance_records
                  (id, user_id, attendance_date, clock_in, clock_out, status, work_minutes, overtime_minutes, remark, created_at)
                SELECT 'seed-attendance-' || seed_users.username || '-' || work_days.day_no,
                       seed_users.id,
                       work_days.work_date,
                       CASE WHEN (seed_users.user_no + work_days.day_no) % 5 IN (3, 4) THEN NULL
                            ELSE time '08:30' + (((seed_users.user_no + work_days.day_no) % 4) * interval '10 minutes') END,
                       CASE WHEN (seed_users.user_no + work_days.day_no) % 5 IN (3, 4) THEN NULL
                            ELSE time '17:30' - (((seed_users.user_no + work_days.day_no) % 3) * interval '10 minutes') END,
                       CASE (seed_users.user_no + work_days.day_no) % 5
                         WHEN 0 THEN 'NORMAL'
                         WHEN 1 THEN 'LATE'
                         WHEN 2 THEN 'EARLY_LEAVE'
                         WHEN 3 THEN 'LEAVE'
                         ELSE 'ABSENT'
                       END,
                       CASE (seed_users.user_no + work_days.day_no) % 5
                         WHEN 0 THEN 480 WHEN 1 THEN 450 WHEN 2 THEN 420 ELSE 0
                       END,
                       CASE WHEN (seed_users.user_no * work_days.day_no) % 3 = 0 THEN 60 ELSE 0 END,
                       CASE (seed_users.user_no + work_days.day_no) % 5
                         WHEN 0 THEN '考勤正常'
                         WHEN 1 THEN '早高峰迟到'
                         WHEN 2 THEN '提前离岗'
                         WHEN 3 THEN '已批准请假'
                         ELSE '未打卡'
                       END,
                       work_days.work_date + time '18:00'
                FROM seed_users
                CROSS JOIN work_days
                ON CONFLICT DO NOTHING
                """);
        jdbc.update("""
                WITH seed_users AS (
                  SELECT id, username, row_number() OVER (ORDER BY username)::int AS user_no
                  FROM users
                  WHERE username IN ('user1', 'user2', 'user3', 'user4', 'user5')
                ),
                work_days AS (
                  SELECT work_date::date,
                         row_number() OVER (ORDER BY work_date DESC)::int AS day_no
                  FROM (
                    SELECT work_date
                    FROM generate_series(current_date - interval '10 days', current_date, interval '1 day') work_date
                    WHERE extract(isodow FROM work_date) <= 5
                    ORDER BY work_date DESC
                    LIMIT 4
                  ) recent_days
                )
                INSERT INTO employee_work_logs
                  (id, user_id, log_date, project_name, work_summary, work_hours, completion_status, created_at)
                SELECT 'seed-worklog-' || seed_users.username || '-' || work_days.day_no,
                       seed_users.id,
                       work_days.work_date,
                       CASE (seed_users.user_no + work_days.day_no) % 3
                         WHEN 0 THEN '知识库建设'
                         WHEN 1 THEN '员工服务平台'
                         ELSE '数据质量治理'
                       END,
                       '完成第 ' || work_days.day_no || ' 项计划工作，更新进度并记录后续事项。',
                       (6.5 + ((seed_users.user_no + work_days.day_no) % 4) * 0.5)::numeric(4, 1),
                       CASE (seed_users.user_no + work_days.day_no) % 4
                         WHEN 0 THEN 'IN_PROGRESS'
                         WHEN 1 THEN 'BLOCKED'
                         ELSE 'COMPLETED'
                       END,
                       work_days.work_date + time '18:30'
                FROM seed_users
                CROSS JOIN work_days
                ON CONFLICT DO NOTHING
                """);
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
