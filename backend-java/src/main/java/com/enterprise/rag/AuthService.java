package com.enterprise.rag;

import jakarta.annotation.PostConstruct;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
class AuthService {
    private final UserRepository users;
    private final PasswordEncoder passwordEncoder;
    private final Map<String, String> tokens = new ConcurrentHashMap<>();

    AuthService(UserRepository users, PasswordEncoder passwordEncoder) {
        this.users = users;
        this.passwordEncoder = passwordEncoder;
    }

    @PostConstruct
    void seedDefaults() {
        users.seedDefaults(passwordEncoder);
    }

    LoginResponse register(RegisterRequest request) {
        String username = normalizeUsername(request.username());
        String password = requirePassword(request.password());
        try {
            UserView user = users.createUser(username, passwordEncoder.encode(password), users.requiredRoleIdByName("USER"));
            String token = UUID.randomUUID().toString();
            tokens.put(token, user.id());
            return new LoginResponse(token, user);
        } catch (DataIntegrityViolationException ex) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "用户名已存在", ex);
        }
    }

    LoginResponse login(LoginRequest request) {
        String username = normalizeUsername(request.username());
        String password = requirePassword(request.password());
        UserRepository.UserAccount account = users.findAccountByUsername(username)
                .orElseThrow(() -> unauthorized("用户名或密码错误"));
        if (account.disabled()) {
            throw unauthorized("用户已被禁用");
        }
        if (!passwordEncoder.matches(password, account.passwordHash())) {
            throw unauthorized("用户名或密码错误");
        }
        String token = UUID.randomUUID().toString();
        tokens.put(token, account.id());
        return new LoginResponse(token, users.userView(account.id()));
    }

    CurrentUser currentUser(String authorization) {
        String token = authorization == null ? "" : authorization.replace("Bearer ", "").trim();
        String userId = tokens.get(token);
        if (userId == null) {
            throw unauthorized("无效或过期的登录凭证");
        }
        UserView user = users.userView(userId);
        if (user.disabled()) {
            tokens.remove(token);
            throw unauthorized("用户已被禁用");
        }
        return new CurrentUser(user.id(), user.username(), user.disabled(), user.roles(), user.knowledgeBaseIds());
    }

    void resetPassword(String userId, String password) {
        users.resetPassword(userId, passwordEncoder.encode(requirePassword(password)));
    }

    private String normalizeUsername(String username) {
        String value = username == null ? "" : username.trim();
        if (value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "用户名不能为空");
        }
        return value;
    }

    private String requirePassword(String password) {
        String value = password == null ? "" : password;
        if (value.length() < 6) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "密码至少需要 6 位");
        }
        return value;
    }

    private ResponseStatusException unauthorized(String message) {
        return new ResponseStatusException(HttpStatus.UNAUTHORIZED, message);
    }
}
