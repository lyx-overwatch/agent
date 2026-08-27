import sys
from pathlib import Path

# 支持直接 python app/auth/__init__.py 运行：将 backend/ 加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio

import jwt
import redis.asyncio as redis

from app.core.config import settings

redis_client = redis.from_url(settings.redis_url)

USER_ID = 'b95d69b216c841958eab59efd95bc45b'

async def mock_java_create_token(user_id: str) -> str:
    payload = {"login_user_key": user_id}
    token = jwt.encode(payload, settings.secret_key, algorithm="HS512")
    try:
        await redis_client.set(f'login_tokens:{user_id}', 'active', ex=30*24*3600 )
        return token
    except Exception as e:
        print(f"Error setting token in Redis: {e}") 
        return None   

async def check_is_in_redis(token: str) -> bool:
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS512"])
    user_id = payload.get(settings.login_user_key)
    if not user_id:
        return False
    return await redis_client.exists(f'login_tokens:{user_id}') == 1

def check_is_authenticated(token: str) -> bool:
    return asyncio.run(check_is_in_redis(token))

online_token = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJsb2dpbl91c2VyX2tleSI6ImI5NWQ2OWIyMTZjODQxOTU4ZWFiNTllZmQ5NWJjNDViIiwidGltZXN0YW1wIjoxNzgwNTM4NzQ2OTM2fQ.8QW7EKEgLRe_Qvi3ak2RUgjgUgHfE7DqWIcwBpBADxXYsNgBB1zoFy_OS_V5IsY25AlTX9-n7wSBrCVBYOeBZQ'

if __name__ == "__main__":
    async def init():
        token = await mock_java_create_token(USER_ID)
        if token:
            print(f"Generated token for user_id={USER_ID}: {token}")
    asyncio.run(init())
    # print((check_is_authenticated(online_token)))
