# 用户自定义 API Key 方案

> 状态：方案设计阶段，待后续评估实施

## 背景

Heyu Agent 的部分技能需要调用外部 API，当前这些 API Key 配置在 `backend/.env` 中作为平台级全局配置：

| 技能 | 需要的 Key |
|---|---|
| image-generation | `GEMINI_API_KEY` |
| video-generation | `GEMINI_API_KEY` |
| ppt-generation | `GEMINI_API_KEY`（间接依赖 image-generation） |
| podcast-generation | `VOLCENGINE_TTS_APPID`、`VOLCENGINE_TTS_ACCESS_TOKEN` |
| github-deep-research | `GITHUB_TOKEN`（可选） |

**问题**：平台提供全局 Key 存在成本不可控、Key 泄露影响面大、无法按用户计费等问题。

**目标**：让每个用户配置自己的 API Key，平台不持有全局 Key，实现用户级隔离。

## 核心挑战

技能脚本（如 `image-generation/scripts/generate.py`）直接通过 `os.getenv("GEMINI_API_KEY")` 读取环境变量，而子进程继承自 FastAPI 主进程。当前架构下 agent 是启动时创建的单例，环境变量在启动时固定，无法按请求动态切换。

## 方案设计

### 整体架构

```
用户配置 Key ──→ 前端设置面板 ──→ PUT /user/api-keys ──→ DB (加密存储)
                                                              │
用户发起对话 ──→ chat_service ──→ 读取用户 Keys ──→ 写入 workspace/.user_env
                                                              │
              Agent 执行 ──→ source .user_env ──→ 技能脚本读取 os.getenv()
```

### 1. 数据库 — 新增 `user_api_keys` 表

```sql
CREATE TABLE user_api_keys (
    id            SERIAL PRIMARY KEY,
    user_id       VARCHAR(100) NOT NULL REFERENCES users(id),
    key_name      VARCHAR(100) NOT NULL,
    encrypted_value TEXT NOT NULL,         -- Fernet 对称加密
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, key_name)
);
```

- **加密方案**：使用 `cryptography.fernet` 模块，密钥从 `SECRET_KEY` 派生
- **API 返回时** value 脱敏：`AIza***abcd` 格式，仅显示首尾各 4 字符
- **SQLModel 定义**位置：`backend/app/models/database.py`

### 2. 后端 API — 新增 `/user/api-keys` 路由

文件：`backend/app/routes/api_keys.py`

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/user/api-keys` | 列出当前用户的 Key（name + 脱敏后的 value 预览 + updated_at） |
| `PUT` | `/user/api-keys/{key_name}` | 设置/更新某个 Key 的值（body: `{"value": "xxx"}`） |
| `DELETE` | `/user/api-keys/{key_name}` | 删除某个 Key |

支持管理的 key_name 白名单：
- `GEMINI_API_KEY`
- `VOLCENGINE_TTS_APPID`
- `VOLCENGINE_TTS_ACCESS_TOKEN`
- `GITHUB_TOKEN`

所有端点需要 `user_id = Depends(get_current_user)` 鉴权，仅操作自己的 Key。

### 3. Agent 执行层 — 注入用户 Key

#### 3.1 chat_service 改动

在 `ChatService.execute_stream()` 和 `execute_sync()` 方法开头，增加 Key 注入步骤：

```python
async def _inject_user_env(self, user_id: str, thread_id: str) -> None:
    """将用户的 API Keys 写入沙箱 workspace 的 .user_env 文件。"""
    keys = await self._api_key_repo.get_by_user(user_id)
    if not keys:
        return

    cfg = get_agent_config()
    workspace = cfg.path_provider.get_workspace_dir(thread_id)
    workspace.mkdir(parents=True, exist_ok=True)
    env_file = workspace / ".user_env"

    lines = [f"{k.key_name}={k.decrypted_value}" for k in keys]
    env_file.write_text("\n".join(lines))
```

#### 3.2 系统提示改动

在 `agent.py` 的系统提示中增加：

```
<User API Keys>
If external API keys are needed, they are available in
/mnt/user-data/workspace/.user_env.
Before running skill scripts that call external APIs,
load them: export $(cat /mnt/user-data/workspace/.user_env | xargs)
```

> 注：系统提示中已有 "Stop on failure: if a tool fails due to missing deps (API keys, env vars, unavailable services), STOP after 2 attempts and tell the user what is missing."，与新增内容配合使用——如果用户没配 Key，Agent 会尝试一次失败后告知用户缺少哪个 Key。

### 4. 前端 — 用户设置面板

在 `debug-agent.html` 侧边栏或主工具栏新增入口：

- **入口按钮**：侧边栏 header 或工具栏中增加「🔑 API Keys」
- **面板内容**：
  - 列出 4 个可选配置的 Key（标注用途）
  - 每项显示：Key 名称 | 当前状态（已配置 ✓ / 未配置 ○） | 输入框 | 保存/清除按钮
  - 已配置的 Key 仅显示脱敏预览值
  - 点击「保存」→ `PUT /user/api-keys/{key_name}`
  - 点击「清除」→ `DELETE /user/api-keys/{key_name}`

### 5. 部署注意事项

- **migration**：需要创建 Alembic 迁移文件添加 `user_api_keys` 表
- **加密密钥**：Fernet key 从 `SECRET_KEY` 的前 32 字节派生，确保不同环境加密不互通
- **向后兼容**：如果用户没有配置自己的 Key 且平台 `.env` 中有全局 Key，行为不变——技能脚本仍能读全局 Key。只有当用户主动配置了自己的 Key 后，才会覆盖全局 Key
- **安全**：API 返回时永远不返回完整 decrypted_value，仅脱敏预览

## 后续工作

- [ ] 评估方案可行性，确认 agent-sdk 版本支持
- [ ] 创建数据库 migration
- [ ] 实现 `UserApiKey` model + CRUD repo
- [ ] 实现 `/user/api-keys` 路由
- [ ] 实现 `chat_service` Key 注入逻辑
- [ ] 实现前端 API Keys 设置面板
- [ ] 测试：多用户 Key 隔离、未配置时的降级行为
