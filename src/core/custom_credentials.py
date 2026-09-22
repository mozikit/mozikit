"""Custom credential operations used by both frontends."""
from .credential_store import store_credential, delete_credential


def set_custom_credential(manager, key: str, value: str):
    if not key.strip() or key in {"ai_api_key", "github_token"}:
        raise ValueError("凭据名称为空或与内置凭据冲突")
    if not isinstance(value, str) or not value:
        raise ValueError("凭据值必须是非空字符串")
    encrypted = store_credential(key, value)
    if not encrypted:
        raise ValueError("凭据存储失败")
    manager.config.setdefault("custom_credentials", {})[key] = encrypted
    manager.save_config_sync()


def remove_custom_credential(manager, key: str):
    if key in {"ai_api_key", "github_token"}:
        raise ValueError("不能通过自定义凭据操作删除内置凭据")
    custom = manager.config.get("custom_credentials", {})
    if key not in custom:
        raise ValueError(f"凭据不存在: {key}")
    delete_credential(key)
    del custom[key]
    manager.save_config_sync()
