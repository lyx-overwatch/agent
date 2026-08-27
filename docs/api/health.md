# Health（健康检查）

> 路由前缀: 无（根路径）  
> 源码: `backend/app/main.py`

## 接口列表

- [GET /health](#get-health) — 健康检查

---

## GET /health

返回服务运行状态。**无需认证**。

### Request

```
GET /health
```

### Response `200 OK`

```json
{
  "status": "ok"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `string` | `"ok"` 表示服务正常运行 |
