# Redis 速通教程（Python 版）

> 目的：能看懂认证中间件里 Redis 那几行代码在干什么，能在本地自己调试。

---

## 一、先跑起来

确保 Redis 开着（之前的 `redis-server.exe` 窗口别关），装 Python 客户端：

```bash
pip install redis
```

然后在 Python 里试：

```python
import redis

# 连接本机 Redis（默认 6379 端口，不需要密码）
r = redis.from_url("redis://localhost")

# 验证连通
print(r.ping())  # → True
```

**Redis 本质上就是一个存在内存里的字典。** 你用过的 Python dict 是：

```python
d = {}
d["name"] = "张三"
print(d["name"])  # 张三
del d["name"]
```

Redis 做的事一模一样，只是这个 "dict" 是独立进程，所有程序都能连，而且数据在程序重启后还在。

---

## 二、五种基础操作（对照 Python dict）

你只需要掌握这 5 个操作，就能看懂中间件代码：

| 操作 | Python dict | Redis | 说明 |
|------|------------|-------|------|
| 写入 | `d["k"] = "v"` | `r.set("k", "v")` | 存一个 key-value |
| 读取 | `d["k"]` → `"v"` | `r.get("k")` → `b"v"` | 取 key 对应的值（返回 bytes） |
| 查询是否存在 | `"k" in d` | `r.exists("k")` → 1/0 | 1 表示存在，0 表示不存在 |
| 删除 | `del d["k"]` | `r.delete("k")` | 删掉 key |
| 带过期时间的写入 | ❌ 做不到 | `r.setex("k", 时间秒, "v")` | 到期自动删除，**Redis 独有** |

### 直接跑一遍

```python
import redis

r = redis.from_url("redis://localhost", decode_responses=True)
# decode_responses=True 让返回值是 str 而不是 b"xxx"

# ── 1. 写入 ──
r.set("name", "张三")
print(r.get("name"))            # 张三

# ── 2. 判断是否存在 ──
print(r.exists("name"))         # 1（存在）
print(r.exists("不存在的key"))   # 0（不存在）

# ── 3. 删除 ──
r.delete("name")
print(r.exists("name"))         # 0（删完了）

# ── 4. 带过期时间（Redis 最核心的功能） ──
r.setex("验证码", 10, "123456")   # 10 秒后自动删除
print(r.get("验证码"))            # 123456
print(r.ttl("验证码"))            # 还剩几秒（比如 8）
# 等 10 秒...
import time
time.sleep(10)
print(r.get("验证码"))            # None（自动没了！）
```

`setex` 是中间件最核心的操作——Java 用它实现"登录态 2 小时自动过期"，Python 只需要确认 key 还在不在。

---

## 三、对照认证中间件理解

现在回来看中间件的 Redis 部分，只有 2 行代码：

```python
# 连接 Redis（全局单例，启动时创建一次）
redis_client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
```

```python
# 每个请求执行：查 key 在不在（就这一行！）
session_key = f"user:session:{user_id}"
if not await redis_client.exists(session_key):
    return JSONResponse(status_code=401, content={"detail": "请重新登录"})
```

对照翻译：

```python
# Redis 里存的 key 长这样：
#   user:session:zhs     → "1"
#   user:session:ls      → "1"

session_key = f"user:session:{user_id}"   # 拼接出 key 名

# 等价于 Python dict 的：
# if "user:session:zhs" not in d:
#     return 401

if not await redis_client.exists(session_key):
    return 401  # key 不存在 → 这个用户没登录（或已登出）
```

**你只需要知道 `exists` 这一个操作，就能理解整个认证流程。** Redis 对 Python 中间件来说，就是一个全局的、跨语言的 `set`——只问"这个 key 在不在"，不关心 value 是什么。

---

## 四、自己动手调试

打开 Redis Insight（或再开一个 `redis-cli` 窗口），边写 Python 边观察：

```python
import redis
r = redis.from_url("redis://localhost", decode_responses=True)

# 模拟 Java 登录
r.setex("user:session:zhs", 7200, "1")
# 切换到 Redis Insight → 刷新 → 看到 user:session:zhs，TTL 7200 秒

# 模拟 Python 中间件检查（就是你写的那 3 行）
key = "user:session:zhs"
print(r.exists(key))   # 1 → 放行

# 模拟 Java 登出
r.delete("user:session:zhs")
# 切换到 Redis Insight → 刷新 → key 消失了

# Python 中间件再检查
print(r.exists(key))   # 0 → 401
```

**你写的中间件逻辑就是这样**，只不过用 `async` 版本（`aioredis`）适配 FastAPI 的异步架构，操作完全一样。

---

## 五、常见疑问

**Q: key 名叫 `user:session:zhs`，冒号是什么意思？**
A: 只是命名约定，方便 Redis Insight 里按层级展示，没有特殊含义。写成 `user_session_zhs` 也一样能用。

**Q: value 都是 `"1"`，有意义吗？**
A: 没意义，就是个标记位。你只关心 key 在不在，value 是什么不重要。

**Q: 为什么用 `aioredis` 而不是普通的 `redis`？**
A: FastAPI 是异步框架（`async/await`），如果在异步代码里用同步 Redis 客户端，会阻塞整个事件循环导致所有请求卡住。`aioredis` 是异步版本，并发性能更好。

**Q: Redis 数据会丢吗？**
A: 默认每隔一段时间存盘（RDB 快照），重启一般不会丢。就算丢了，用户只是需要重新登录，不会丢业务数据。
