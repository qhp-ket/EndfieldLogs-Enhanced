"""Application settings shared by runtime and presentation adapters."""
from .model import AppConfig
from .codec import (
    default_config_path, default_overlay_entries, default_service_config,
    load_app_config, save_app_config,
)

__all__ = ['AppConfig', 'default_config_path', 'default_overlay_entries',
           'default_service_config', 'load_app_config', 'save_app_config']
