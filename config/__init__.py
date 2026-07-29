# config/__init__.py
from .settings import get_settings

def get_config() -> dict:
    """Compatibility view for callers not yet migrated to AppSettings."""
    return get_settings().as_legacy_dict()

def get_os() -> str:
    """Returns: 'windows' | 'mac' | 'linux'"""
    return get_settings().os_system

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"
