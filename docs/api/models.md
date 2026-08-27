# Models（模型）

> 路由前缀: `/py/api/models`  
> 源码: `backend/app/routes/models.py`

## 接口列表

- [GET /](#get) — 获取可用模型列表

---

## GET /

返回 `config.yaml` 中配置的所有模型的元数据，供前端构建模型选择器。

### Request

```
GET /py/api/models
Authorization: Bearer <token>
```

### Response `200 OK`

```json
{
  "models": [
    {
      "name": "claude-sonnet-4-5",
      "display_name": "Claude Sonnet 4.5",
      "model": "claude-sonnet-4-5-20250901",
      "supports_thinking": true,
      "supports_vision": true
    },
    {
      "name": "deepseek-v3",
      "display_name": "DeepSeek V3",
      "model": "deepseek-chat",
      "supports_thinking": false,
      "supports_vision": false
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 模型逻辑名称（`config.yaml` 中 `models[].name`），用于 `POST /chat/stream` 的 `model_name` 参数 |
| `display_name` | `string` | 前端展示名称 |
| `model` | `string` | 实际调用的模型 ID（API 层面） |
| `supports_thinking` | `boolean` | 是否支持深度思考模式 |
| `supports_vision` | `boolean` | 是否支持视觉/图片理解 |
