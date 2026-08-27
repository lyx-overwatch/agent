# Auth（认证）

> 路由前缀: `/py/api/auth`  
> 源码: `backend/app/routes/auth.py`

## 接口列表

- [POST /verify](#post-verify) — 校验 Token 并自动注册用户

---

## POST /verify

校验 JWT Token（HS512）并自动注册用户。前端在调用任何业务接口之前必须先调此接口。

### Request

```
POST /py/api/auth/verify
Authorization: Bearer <java-issued-jwt>
```

### Response `200 OK`

```json
{
  "user_id": "user123",
  "is_new_user": false,
  "role": "user"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | `string` | 用户标识（对应 JWT 中 `login_user_key` claim） |
| `is_new_user` | `boolean` | 是否本次新注册（首次调用时为 `true`） |
| `role` | `string` | 用户角色：`user` / `admin`（管理员由运维手动置位，前端据此显示审核入口） |

### 认证流程

1. 从 `Authorization: Bearer <token>` 提取 JWT
2. 使用 HS512 算法 + `SECRET_KEY` 解码，提取 `login_user_key` claim
3. 校验 Redis 中是否存在 `login_tokens:{user_id}` key（登录态）
4. 在本地 `users` 表中执行 get-or-create 操作
5. 返回 `user_id`、`is_new_user` 和 `role` 标志

### 错误响应

| 状态码 | 说明 |
|--------|------|
| 401 | Token 无效、格式错误，或 Redis 登录态缺失 |
