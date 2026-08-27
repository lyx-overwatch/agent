"""Models endpoint — list all configured AI models for the frontend model picker."""

from fastapi import APIRouter

from app.core.config_loader import get_agent_config

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
async def list_models():
    """返回 config.yaml 中所有可用模型的元数据。

    前端可以据此构建模型选择器，根据 ``supports_thinking`` /
    ``supports_vision`` 等字段展示不同的选项和功能开关。
    """
    cfg = get_agent_config()
    return {
        "models": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "model": m.model_settings.get("model", m.name),
                "supports_thinking": m.supports_thinking,
                "thinking_locked": m.thinking_locked,
                "supports_vision": m.supports_vision,
            }
            for m in cfg.model_configs
        ]
    }
