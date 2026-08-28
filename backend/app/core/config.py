from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Heyu Agent"
    debug: bool = False

    # 运行环境: local | test | production
    # local:  文件日志 + 彩色控制台，适合开发调试
    # test:   JSON stdout 日志，适合容器化部署 (Docker Compose / K8s staging)
    # production: JSON stdout 日志，适合生产 K8s
    environment: str = "local"

    # Auth
    secret_key: str
    # Java 端使用 HMAC512 (HS512) 签发 token，Python 端验证时需保持一致
    algorithm: str = "HS512"
    # Java token 中存放用户标识的 claim key，对应 Java Constants.LOGIN_USER_KEY
    login_user_key: str = "login_user_key"
    # 邮箱登录签发的 access token 有效期（分钟），默认 7 天
    access_token_expire_minutes: int = 10080
    # LLM — 支持 Anthropic 直连 或 自定义代理（国内模型）
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    model_id: str = "claude-sonnet-4-5"

    # Database
    database_url: str

    # ── Checkpointer 清理（仅 postgres checkpointer 生效）──────────────
    # keep_latest 语义：删除「ts 超过保留期」的中间快照，但每个 thread 永远保留
    # 最新一条（含完整累积 state），续聊上下文不丢失；仅失去回退到很久之前某个
    # 中间步骤的「时间旅行」能力。详见 app/core/checkpoint_cleanup.py。
    checkpoint_cleanup_enabled: bool = True
    checkpoint_cleanup_ttl_days: int = 30
    checkpoint_cleanup_interval_seconds: int = 3600

    # Skills 目录（相对于运行 uvicorn 的 backend/ 目录）
    skills_dir: Path = Path("../skills")

    # CORS — 允许的来源列表，逗号分隔
    # local: http://localhost:3000,http://localhost:3030,http://localhost,http://127.0.0.1
    # test / production: 留空（前端与 API 同源，无需 CORS）
    cors_origins: str = "http://localhost:3000,http://localhost:3030,http://localhost,http://127.0.0.1"

    model_config = {"env_file": ".env", "extra": "ignore"}

    redis_url: str = "redis://localhost"

    # ── 会话创建限流 ───────────────────────────────────────────────
    # 同一用户创建会话的最小间隔（秒）。前端已有发送锁，这里作为服务端兜底，
    # 防止前端异常 / 连点 / 代理重试在短时间内批量创建重复会话。
    # 设为 0 或负数表示关闭限流。
    conversation_create_min_interval_seconds: int = 3
    # 限流后端：memory（进程内，单实例 / 本地开发，零依赖）| redis（多副本共享窗口）。
    # 单实例部署 memory 足够；多副本负载均衡时需用 redis，否则各进程窗口不共享。
    rate_limit_backend: str = "memory"

    # ── File storage (OBS / MinIO / local) ──────────────────────────
    # "local" → files on local disk (zero-config development)
    # "s3"    → S3-compatible object storage (Huawei Cloud OBS, MinIO, AWS S3)
    storage_backend: str = "s3"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "skillhub-files"
    s3_region: str = ""
    s3_addressing_style: str = "virtual"  # "virtual" for OBS, "path" for MinIO
    # 反向代理前缀：下载 URL 用它替换 OBS 直连地址（如 https://agc-study.oa.cmbchina.biz/obs）。
    # 空字符串表示直接用 OBS 预签名地址（开发/MinIO 场景）。
    s3_proxy_url: str = ""
    download_url_expires: int = 3600


settings = Settings()
