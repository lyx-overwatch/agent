# SkillHub 认证方案总结

> Python 不维护用户体系，直接复用 Java JWT + 共享 Redis 确认登录态。

---

## 一、核心决策

| 决策项 | 结论 |
|--------|------|
| Python 是否有自己的 token | **否**，直接使用 Java JWT |
| Python 是否存用户密码 | **否**，不维护用户表，只读 Redis |
| 前端存几个 token | **1 个**（Java JWT） |
| 认证方式 | 每个请求：验 JWT 签名 + 查 Redis 确认登录态 |
| 登出同步 | Java 登出删 Redis key → Python 侧自动感知 |

---

## 二、整体架构

```
                             ┌──────────────────┐
                             │     Redis        │
                             │  (共享缓存)       │
          ┌──────────────────┤ user:session:zhs │◄──────────────────┐
          │ 写 session        │                  │      读 session    │
          │                  └──────────────────┘                   │
    ┌─────┴──────────┐                                   ┌──────────┴──────┐
    │  Java 后端      │                                   │  Python SkillHub│
    │  登录 → 写 Redis│                                   │  验 JWT 签名    │
    │  登出 → 删 Redis│                                   │  查 Redis 状态  │
    │  颁发 JWT      │                                   │  放行/拒绝      │
    └────────────────┘                                   └────────────────┘
           ▲                                                    ▲
           │        同一个 Java JWT                              │
           └────────────────────────────────────────────────────┘
                               │
                         ┌─────┴─────┐
                         │   前端     │
                         │  1 个 token│
                         └───────────┘
```

---

## 三、找 Java 确认

| # | 需要什么 | 用途 |
|---|---------|------|
| 1 | **JWT 密钥**（HS256 对称密钥 或 RS256 公钥） | Python 验证 JWT 签名 |
| 2 | **JWT payload 结构**（`sub` 是 user_id？还有哪些字段？） | Python 提取用户标识 |
| 3 | **Redis 连接信息**（地址、密码、端口） | Python 连 Redis |
| 4 | **Redis key 命名格式**（如 `user:session:{user_id}`） | Python 查登录态 |
| 5 | **Redis key 生命周期**（登录写、登出删、TTL） | Python 理解过期机制 |

**Java 不需要新开发任何接口。** Python 只读已有 Redis 数据。

---

## 四、认证流程

### 4.1 登录（Java 负责，Python 不参与）

```
前端 → Java /api/auth/login → Java 验密 → 写 Redis → 返回 JWT
```

### 4.2 每次 API 请求（Python 中间件）

```
前端 → Python /api/skillhub/*（带 Java JWT）
    │
    ▼
JavaJWTAuthMiddleware:
    1. 提取 Authorization: Bearer {JWT}
    2. 验 JWT 签名（JWT_SHARED_SECRET）
    3. 提取 user_id = payload["sub"]
    4. 查 Redis: EXISTS user:session:{user_id}
    5. 存在 → 放行，注入用户到 ContextVar
    6. 不存在 → 401
```

### 4.3 登出（Java 负责，Python 自动感知）

```
前端 → Java /api/auth/logout → Java 删 Redis key → 前端丢弃 JWT
Python 侧下次请求 → Redis key 不存在 → 401（实时生效）
```

---

## 五、Python 侧实现

### 5.1 文件结构

```
skillhub-python/
├── app.py
├── auth/
│   └── java_jwt_middleware.py     # 唯一的认证文件
```

### 5.2 端点

| 端点 | 功能 |
|------|------|
| `GET /api/skillhub/auth/me` | 返回当前用户信息（可选，供前端确认登录态） |

没有 `/login`、`/register`、`/logout`、`/refresh`、`/exchange`。

### 5.3 中间件代码

```python
# auth/java_jwt_middleware.py

import jwt
import redis.asyncio as aioredis
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from types import SimpleNamespace
from deerflow.runtime.user_context import set_current_user, reset_current_user

# --- 配置 ---
redis_client = aioredis.from_url(
    os.environ["REDIS_URL"],
    decode_responses=True,
)
JWT_SECRET = os.environ["JWT_SHARED_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
SESSION_KEY_PREFIX = os.environ.get("REDIS_SESSION_KEY_PREFIX", "user:session:")

EXCLUDED_PATHS = {"/health", "/api/skillhub/health"}


class JavaJWTAuthMiddleware(BaseHTTPMiddleware):
    """认证中间件：验 Java JWT + 查 Redis 确认登录态。

    每个请求三步：
      1. 验 JWT 签名
      2. 查 Redis 确认登录态有效
      3. 注入用户到 ContextVar
    """

    async def dispatch(self, request, call_next):
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        # 第一步：提取 + 验签 Java JWT
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing token"})

        token = auth_header.removeprefix("Bearer ")

        try:
            payload = jwt.decode(
                token,
                key=JWT_SECRET,
                algorithms=[JWT_ALGORITHM],
                options={"require": ["sub", "exp"]},
            )
        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"detail": "Token expired"})
        except jwt.InvalidTokenError as e:
            return JSONResponse(status_code=401, content={"detail": f"Invalid token: {e}"})

        user_id = str(payload["sub"])

        # 第二步：查 Redis 确认登录态
        session_key = f"{SESSION_KEY_PREFIX}{user_id}"
        if not await redis_client.exists(session_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Session expired, please login again"},
            )

        # 第三步：注入用户
        user = SimpleNamespace(
            id=user_id,
            name=payload.get("name", user_id),
            role=payload.get("role", "user"),
        )
        request.state.user = user

        ctx_token = set_current_user(user)
        try:
            return await call_next(request)
        finally:
            reset_current_user(ctx_token)
```

### 5.4 注册中间件

```python
# app.py
from fastapi import FastAPI
from auth.java_jwt_middleware import JavaJWTAuthMiddleware

app = FastAPI(title="SkillHub API")
app.add_middleware(JavaJWTAuthMiddleware)
```

---

## 六、本地调试方案（不依赖线上环境）

### 6.1 整体思路

```
┌─────────────────────────────────────────────────────┐
│                    本地开发机器                       │
│                                                     │
│  Docker Redis (localhost:6379)                      │
│      ▲                                              │
│      │                                              │
│  ┌───┴──────────────┐    ┌──────────────────────┐   │
│  │ simulate_java.py │    │  pytest 测试套件       │   │
│  │                  │    │                      │   │
│  │ 签发 JWT         │    │ 1. 有效 token → 200  │   │
│  │ 写 Redis session │    │ 2. 过期 token → 401  │   │
│  │ 删 Redis session │    │ 3. 登出(删key)→ 401 │   │
│  └──────────────────┘    │ 4. 错误签名 → 401   │   │
│                          │ 5. 缺少 token → 401 │   │
│                          └──────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**不需要 Java 后端，不需要线上 Redis，一套脚本 + Docker 搞定。**

### 6.2 第一步：启动本地 Redis

```bash
docker run -d --name skillhub-redis -p 6379:6379 redis:7-alpine
```

验证：

```bash
docker exec -it skillhub-redis redis-cli PING
# → PONG
```

### 6.3 第二步：Java 模拟脚本

`tests/simulate_java.py` — 模拟 Java 侧的三个动作：签发 JWT、写 session、删 session。

```python
"""simulate_java.py — 模拟 Java 后端行为，供本地调试使用。

用法：
    # 1. 模拟登录（签发 JWT + 写 Redis）
    python tests/simulate_java.py login --user-id zhs --user-name 张三

    # 2. 模拟登出（删 Redis session key）
    python tests/simulate_java.py logout --user-id zhs

    # 3. 只生成 JWT（不写 Redis）
    python tests/simulate_java.py token --user-id zhs

    # 4. 生成过期 JWT（测试过期场景）
    python tests/simulate_java.py token --user-id zhs --expired
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import jwt
import redis


# —— 和 Java 约定好的配置（本地调试用，不写入版本控制）——
JWT_SECRET = os.environ.get("JWT_SHARED_SECRET", "local-dev-shared-secret")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SESSION_KEY_PREFIX = os.environ.get("REDIS_SESSION_KEY_PREFIX", "user:session:")
SESSION_TTL = 7200  # 2 小时，和 Java 保持一致


def create_jwt(user_id: str, user_name: str = "", expired: bool = False) -> str:
    """签发 JWT，payload 结构对齐 Java。"""
    now = datetime.now(timezone.utc)
    if expired:
        exp = now - timedelta(hours=1)  # 1 小时前过期
    else:
        exp = now + timedelta(hours=2)

    payload = {
        "sub": user_id,           # 用户唯一标识
        "name": user_name or user_id,
        "role": "user",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def write_session(user_id: str) -> None:
    """模拟 Java 登录：写 Redis session key。"""
    r = redis.from_url(REDIS_URL, decode_responses=True)
    key = f"{SESSION_KEY_PREFIX}{user_id}"
    r.setex(key, SESSION_TTL, "1")
    ttl = r.ttl(key)
    print(f"[Redis] SET {key} (TTL={ttl}s)")


def delete_session(user_id: str) -> None:
    """模拟 Java 登出：删 Redis session key。"""
    r = redis.from_url(REDIS_URL, decode_responses=True)
    key = f"{SESSION_KEY_PREFIX}{user_id}"
    r.delete(key)
    print(f"[Redis] DEL {key}")


def main():
    parser = argparse.ArgumentParser(description="模拟 Java 后端行为")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="模拟登录：签发 JWT + 写 Redis")
    p_login.add_argument("--user-id", required=True)
    p_login.add_argument("--user-name", default="")

    p_logout = sub.add_parser("logout", help="模拟登出：删 Redis session")
    p_logout.add_argument("--user-id", required=True)

    p_token = sub.add_parser("token", help="只生成 JWT（不写 Redis）")
    p_token.add_argument("--user-id", required=True)
    p_token.add_argument("--user-name", default="")
    p_token.add_argument("--expired", action="store_true")

    args = parser.parse_args()

    if args.command == "login":
        token = create_jwt(args.user_id, args.user_name)
        write_session(args.user_id)
        print(f"[JWT] {token}")

    elif args.command == "logout":
        delete_session(args.user_id)

    elif args.command == "token":
        token = create_jwt(args.user_id, args.user_name, expired=args.expired)
        print(token)


if __name__ == "__main__":
    main()
```

### 6.4 第三步：完整测试文件

`tests/test_java_jwt_middleware.py` — 覆盖所有场景，一键验证。

```python
"""test_java_jwt_middleware.py — JavaJWTAuthMiddleware 完整测试套件。

运行方式：
    # 先启动 Redis
    docker run -d --name skillhub-redis -p 6379:6379 redis:7-alpine

    # 运行测试
    REDIS_URL=redis://localhost:6379/0 pytest tests/test_java_jwt_middleware.py -v

    # 测试完清理
    docker rm -f skillhub-redis
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import redis
from fastapi import FastAPI
from starlette.testclient import TestClient

# —— 测试用常量 ——
TEST_SECRET = "test-shared-secret-for-pytest"
TEST_USER_ID = "test-user-001"
TEST_USER_NAME = "测试用户"
SESSION_KEY = f"user:session:{TEST_USER_ID}"

# 确保 auth 模块可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# —— Fixtures ——

@pytest.fixture
def redis_client():
    """连接测试 Redis（db=1，不影响开发数据）。"""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/1")
    r = redis.from_url(redis_url, decode_responses=True)
    # 清空测试 db
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def app():
    """创建带中间件的测试 FastAPI app。"""
    # 在导入中间件之前注入环境变量
    os.environ["JWT_SHARED_SECRET"] = TEST_SECRET
    os.environ["JWT_ALGORITHM"] = "HS256"

    from auth.java_jwt_middleware import JavaJWTAuthMiddleware

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/skillhub/me")
    async def me(request):
        user = request.state.user
        return {"id": user.id, "name": user.name}

    app.add_middleware(JavaJWTAuthMiddleware)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# —— 辅助函数 ——

def make_token(
    user_id: str = TEST_USER_ID,
    user_name: str = TEST_USER_NAME,
    secret: str = TEST_SECRET,
    expired: bool = False,
    wrong_secret: bool = False,
) -> str:
    """生成测试用 JWT。"""
    key = "wrong-secret" if wrong_secret else secret
    now = datetime.now(timezone.utc)
    if expired:
        exp = now - timedelta(hours=1)
    else:
        exp = now + timedelta(hours=2)

    return jwt.encode(
        {"sub": user_id, "name": user_name, "role": "user", "exp": int(exp.timestamp())},
        key,
        algorithm="HS256",
    )


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# —— 测试用例 ——

class TestHealthEndpoint:
    """健康检查端点不需要认证。"""

    def test_health_no_token(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestMissingToken:
    """没有 token 时返回 401。"""

    def test_no_auth_header(self, client):
        resp = client.get("/api/skillhub/me")
        assert resp.status_code == 401
        assert "Missing token" in resp.json()["detail"]

    def test_empty_auth_header(self, client):
        resp = client.get("/api/skillhub/me", headers={"Authorization": ""})
        assert resp.status_code == 401


class TestValidToken:
    """有效 token + Redis session 存在 → 200。"""

    def test_valid_token_with_session(self, client, redis_client):
        # 模拟 Java 登录：写 Redis session
        redis_client.setex(SESSION_KEY, 7200, "1")

        token = make_token()
        resp = client.get("/api/skillhub/me", headers=auth_header(token))

        assert resp.status_code == 200
        assert resp.json()["id"] == TEST_USER_ID
        assert resp.json()["name"] == TEST_USER_NAME


class TestExpiredToken:
    """过期的 JWT → 401。"""

    def test_expired_token(self, client, redis_client):
        redis_client.setex(SESSION_KEY, 7200, "1")
        token = make_token(expired=True)

        resp = client.get("/api/skillhub/me", headers=auth_header(token))

        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()


class TestWrongSignature:
    """签名错误的 JWT → 401。"""

    def test_wrong_signature(self, client, redis_client):
        redis_client.setex(SESSION_KEY, 7200, "1")
        token = make_token(wrong_secret=True)

        resp = client.get("/api/skillhub/me", headers=auth_header(token))

        assert resp.status_code == 401


class TestLogout:
    """模拟登出：Redis key 被删除 → 401（即使 JWT 未过期）。"""

    def test_logout_rejected(self, client, redis_client):
        token = make_token()

        # 场景：用户登录过（Redis 有 key），然后登出（Java 删了 key）
        # 不做 redis_client.setex —— 模拟登出后的状态

        resp = client.get("/api/skillhub/me", headers=auth_header(token))

        assert resp.status_code == 401
        assert "login again" in resp.json()["detail"].lower()


class TestLoginThenLogout:
    """登录 → 正常访问 → 登出 → 被拒绝，完整流程。"""

    def test_full_lifecycle(self, client, redis_client):
        token = make_token()

        # 1. 登录：写 Redis
        redis_client.setex(SESSION_KEY, 7200, "1")

        # 2. 正常访问
        resp = client.get("/api/skillhub/me", headers=auth_header(token))
        assert resp.status_code == 200

        # 3. 登出：删 Redis（模拟 Java logout）
        redis_client.delete(SESSION_KEY)

        # 4. 再次访问 → 被拒绝
        resp = client.get("/api/skillhub/me", headers=auth_header(token))
        assert resp.status_code == 401
```

### 6.5 手动 curl 验证

```bash
# 终端 1：启动 Redis
docker run -d --name skillhub-redis -p 6379:6379 redis:7-alpine

# 终端 2：模拟登录，获取 token
export JWT=$(python tests/simulate_java.py login --user-id zhs --user-name 张三 | grep '\[JWT\]' | cut -d' ' -f2)

# 正常访问 → 200
curl -H "Authorization: Bearer $JWT" http://localhost:8001/api/skillhub/me

# 模拟登出
python tests/simulate_java.py logout --user-id zhs

# 再次访问 → 401 "Session expired, please login again"
curl -H "Authorization: Bearer $JWT" http://localhost:8001/api/skillhub/me

# 测试过期 token
export EXPIRED_JWT=$(python tests/simulate_java.py token --user-id zhs --expired)
curl -H "Authorization: Bearer $EXPIRED_JWT" http://localhost:8001/api/skillhub/me
# → 401 "Token expired"
```

### 6.6 验证清单

跟 Java 对接前，确保以下全部通过：

| # | 场景 | 预期 | 对应测试 |
|---|------|------|---------|
| 1 | 无 token | 401 `Missing token` | `TestMissingToken` |
| 2 | 有效 token + Redis session 存在 | 200，返回用户信息 | `TestValidToken` |
| 3 | JWT 已过期 | 401 `Token expired` | `TestExpiredToken` |
| 4 | JWT 签名错误 | 401 `Invalid token` | `TestWrongSignature` |
| 5 | JWT 有效但 Redis key 不存在（已登出） | 401 `login again` | `TestLogout` |
| 6 | 登录→访问→登出→拒绝 | 完整生命周期 | `TestLoginThenLogout` |
| 7 | `/health` 端点 | 200（不鉴权） | `TestHealthEndpoint` |

**拿到 Java 的真实密钥和 Redis 地址后，只需替换 3 个环境变量，再跑一遍全部通过，就可以上线。**

---

## 七、安全要点

| 防护 | 措施 |
|------|------|
| JWT 伪造 | 密码学签名验证，密钥仅 Java/Python 持有 |
| 过期 JWT | `jwt.decode()` 自动校验 `exp` |
| 已登出用户 | Redis key 被 Java 删除 → Python 实时拒绝 |
| 登出安全窗口 | **0**（删 Redis key 即时生效） |
| 数据隔离 | user_id 注入 ContextVar，持久化层自动按用户隔离 |

---

## 八、环境变量

| 变量 | 用途 |
|------|------|
| `JWT_SHARED_SECRET` | 验证 Java JWT 签名 |
| `JWT_ALGORITHM` | HS256 / RS256（默认 HS256） |
| `REDIS_URL` | Redis 连接地址 |
| `REDIS_SESSION_KEY_PREFIX` | Session key 前缀（默认 `user:session:`） |

---

## 九、执行计划

| 阶段 | 内容 |
|------|------|
| **第一步** | 找 Java 确认：JWT 密钥/算法、payload 字段、Redis 地址、session key 命名 |
| **第二步** | Python 认证中间件开发（一个文件 ~80 行）+ 单元测试 |
| **第三步** | 抽离 DeerFlow 核心（agent + sandbox + runtime），带认证跑通端到端 |
| **第四步** | SkillHub 前端 MVP（市场、执行、工作台 3 个页面） |
| **第五步** | Docker Compose 本地联调 → 部署验证 → 完整链路测试 |
