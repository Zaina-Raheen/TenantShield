"""Runtime configuration, read from environment variables (see .env.example)."""
import ipaddress
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_TRUE = {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    """Raised for unsafe or unsupported configuration. Messages never contain secrets."""


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE


def environment() -> str:
    return os.getenv("TENANTSHIELD_ENV", "production")  # safe default: NOT development


def dev_controls_enabled() -> bool:
    """Development-only endpoints (mode toggle, resets). Still restricted to loopback clients."""
    return environment() == "development"


def vulnerable_demo_enabled() -> bool:
    """The intentionally vulnerable path exists ONLY when development AND an explicit opt-in flag are set."""
    return dev_controls_enabled() and _flag("TENANTSHIELD_ENABLE_VULNERABLE_DEMO")


def allow_remote_reads() -> bool:
    """Optional: let non-loopback clients use read-only (GET) endpoints. Never applies to state changes."""
    return _flag("TENANTSHIELD_ALLOW_REMOTE_READS")


def database_url() -> str:
    return os.getenv("TENANTSHIELD_DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'tenantshield.db'}")


def cors_origins() -> list[str]:
    raw = os.getenv("TENANTSHIELD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def allowed_hosts() -> list[str]:
    raw = os.getenv("TENANTSHIELD_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
    return [h.strip() for h in raw.split(",") if h.strip()]


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def validate_target_config() -> None:
    """The engine can only test the bundled demo API, in-process. There is no configurable target URL."""
    if os.getenv("TENANTSHIELD_DEMO_API_BASE_URL"):
        raise ConfigError("TENANTSHIELD_DEMO_API_BASE_URL is no longer supported: the engine only tests the bundled "
                          "demo API in-process. Remove this variable.")
    target = os.getenv("TENANTSHIELD_DEMO_TARGET", "inprocess")
    if target != "inprocess":
        raise ConfigError("Unsupported TENANTSHIELD_DEMO_TARGET; the only permitted value is 'inprocess'.")
