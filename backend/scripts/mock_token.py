#!/usr/bin/env python3
"""生成本地开发的 mock 登录 token,用于绕过 Java 主系统的鉴权。

Java 主系统正常会签发 JWT(HS512),本脚本伪造一个等价的 token,方便本地
开发/联调时无需 Java token 即可登录。它做两件事:

  1. 用与后端相同的 SECRET_KEY / 算法(HS512)签发 JWT,claim 结构与 Java 一致:
       {"login_user_key": "<userId>", "timestamp": <epochMillis>}
  2. 在 Redis 写入登录态 key ``login_tokens:<userId>``
     (app/core/auth.py 的 check_is_authenticated 会校验其存在性)

首次使用该 token 调 ``POST /py/api/auth/verify`` 时,后端会自动在 users 表
注册该用户(role 默认 "user";如需管理员,注册后手动 UPDATE users SET role='admin')。

用法:
  cd backend
  uv run scripts/mock_token.py              # 默认 user_id=mock-user
  uv run scripts/mock_token.py user123      # 自定义 user_id
"""

import argparse
import sys
import time
import warnings
from pathlib import Path

import jwt
import redis

# 让脚本在任意 cwd 下都能 import 到 backend/ 的 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings

# SECRET_KEY 为 32 bytes,HS512 建议 64 bytes,与后端一致地抑制该告警
warnings.filterwarnings("ignore", category=jwt.InsecureKeyLengthWarning)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("user_id", nargs="?", default="mock-user", help="用户标识(即 JWT 的 login_user_key)")
    parser.add_argument("--no-redis", action="store_true", help="跳过写入 Redis(仅打印 token)")
    args = parser.parse_args()

    user_id = args.user_id

    # 1. 签发 JWT —— 与 Java 端格式一致
    payload = {
        settings.login_user_key: user_id,
        "timestamp": int(time.time() * 1000),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    # 2. 写 Redis 登录态(后端 check_is_authenticated 会校验 login_tokens:<user_id>)
    if not args.no_redis:
        try:
            r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            r.set(f"login_tokens:{user_id}", token)
            r.close()
        except Exception as exc:  # noqa: BLE001
            print(f"✗ 写 Redis 失败: {exc}", file=sys.stderr)
            print("  后端会因「Redis 无登录态」拒绝该 token,请先确认 Redis 已启动。", file=sys.stderr)
            return 1

    print()
    print("=" * 64)
    print("mock token 已生成")
    print(f"  user_id : {user_id}")
    print(f"  算法    : {settings.algorithm}")
    print(f"  claim   : {settings.login_user_key}={user_id}")
    print()
    print("  请求 Header:")
    print(f"    Authorization: Bearer {token}")
    print("=" * 64)
    print()
    print("提示: 前端首次调用 POST /py/api/auth/verify 会自动注册该用户。")
    print("如需管理员权限,注册后执行: UPDATE users SET role='admin' WHERE id='" + user_id + "';")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
