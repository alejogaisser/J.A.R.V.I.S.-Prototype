from config.settings import default_settings_path, get_settings, update_settings


def ensure_config_dir() -> None:
    default_settings_path().parent.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    return default_settings_path().exists()


def save_api_keys(gemini_api_key: str) -> None:
    update_settings({"gemini_api_key": gemini_api_key.strip()})


def load_api_keys() -> dict:
    return get_settings().as_legacy_dict()


def get_gemini_key() -> str | None:
    return get_settings().gemini_api_key or None


def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)
