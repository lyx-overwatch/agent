-- ============================================================================
-- 设置技能审核管理员（手动执行，一次性运维操作）
-- ============================================================================
-- 原理：审核权限由 users.role 字段控制，逻辑在
--   backend/app/services/skill_service.py::_require_admin()
--   → 只有 users.role = 'admin' 的用户才能调用 GET /skills/pending 与 POST /skills/{name}/review
-- 字段由迁移 311e49d8b58b 新增：VARCHAR(20) NOT NULL DEFAULT 'user'，运维手动置 'admin'。
--
-- 重要：users.id 是 Java 端 JWT 的 login_user_key（主系统 userId），不是 username。
-- 目标用户需已登录过一次（首次鉴权会自动注册到 users 表）才能被置位。

-- 1) 先查目标用户，确认行存在、当前 role（把结果里的 id 复制到第 2 步）
SELECT id, username, role, is_active, created_at
FROM users
ORDER BY created_at;

-- 2) 设为管理员（把 <user_id> 替换为上一步查到的 id）
UPDATE users
SET role = 'admin'
WHERE id = '<user_id>';

-- 3) 校验
SELECT id, username, role FROM users WHERE role = 'admin';

-- 撤销管理员（可选，把 <user_id> 替换为目标 id）
-- UPDATE users SET role = 'user' WHERE id = '<user_id>';
