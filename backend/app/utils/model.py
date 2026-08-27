"""Model display name helper."""

from app.core.config import settings
from app.core.config_loader import get_agent_config


def get_model_display_name(model_name: str | None = None) -> str:
    """Read model display_name from config.yaml, fallback to .env MODEL_ID.

    Args:
        model_name: Optional model name to look up.  When provided, returns
            that model's display name.  When ``None``, returns the first
            configured model's display name.
    """
    cfg = get_agent_config()
    if model_name:
        match = next((m for m in cfg.model_configs if m.name == model_name), None)
        if match and match.display_name:
            return match.display_name
    if cfg.model_configs:
        return cfg.model_configs[0].display_name
    return settings.model_id
