"""Central configuration for AnsibleClaw."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_PKG_DIR = Path(__file__).resolve().parent

TEMPLATE_DIR = _PKG_DIR / "templates"
TEMPLATE_PATH = TEMPLATE_DIR / "skill_template.md"

BUILTINS_DIR = _PKG_DIR / "builtins"

SKILLS_DIR = Path(os.environ.get(
    "ANSIBLECLAW_SKILLS_DIR",
    Path.cwd() / "skills",
))

INSTALL_PATHS: dict[str, Path] = {
    "cursor": Path.home() / ".cursor" / "skills",
    "claude": Path.home() / ".claude" / "skills",
}

# Collection resolution settings
COLLECTIONS_PATH: str = os.environ.get("ANSIBLECLAW_COLLECTIONS_PATH", "")
GALAXY_URL: str = os.environ.get(
    "ANSIBLECLAW_GALAXY_URL", "https://galaxy.ansible.com"
)

# ---------------------------------------------------------------------------
# AAP Controller settings
#
# Resolution order: environment variable > .ansibleclaw.yml > default.
# The web UI writes .ansibleclaw.yml; env vars always win for CI/CD.
# Generated skills read env vars at their own runtime independently.
# ---------------------------------------------------------------------------

SETTINGS_FILE = ".ansibleclaw.yml"

_AAP_KEYS: dict[str, tuple[str, str]] = {
    # key -> (env var name, default value)
    "url":                 ("AAP_CONTROLLER_URL", ""),
    "token":               ("AAP_CONTROLLER_TOKEN", ""),
    "verify_ssl":          ("AAP_VERIFY_SSL", "true"),
    "default_inventory":   ("AAP_DEFAULT_INVENTORY", ""),
    "default_credential":  ("AAP_DEFAULT_CREDENTIAL", ""),
    "default_organization":("AAP_DEFAULT_ORGANIZATION", "Default"),
    "default_project":     ("AAP_DEFAULT_PROJECT", ""),
    "default_ee":          ("AAP_DEFAULT_EE", ""),
    "default_scm_url":    ("AAP_DEFAULT_SCM_URL", ""),
    # Prepended to Job Template names created by Deploy to AAP (empty = no prefix).
    "job_template_prefix": ("ANSIBLECLAW_JOB_TEMPLATE_PREFIX", "AnsibleClaw: "),
}


class AAPSettings:
    """Mutable AAP configuration with env > file > default resolution."""

    _file_cache: dict[str, str] | None = None

    @classmethod
    def _settings_path(cls) -> Path:
        return Path.cwd() / SETTINGS_FILE

    @classmethod
    def _load_file(cls) -> dict[str, str]:
        if cls._file_cache is not None:
            return cls._file_cache
        path = cls._settings_path()
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text()) or {}
                cls._file_cache = {
                    k: str(v) for k, v in data.get("aap", {}).items()
                } if isinstance(data.get("aap"), dict) else {}
            except Exception:
                cls._file_cache = {}
        else:
            cls._file_cache = {}
        return cls._file_cache

    @classmethod
    def get(cls, key: str) -> str:
        """Resolve a single AAP setting: env var > file > default."""
        env_name, default = _AAP_KEYS[key]
        if key == "job_template_prefix" and env_name in os.environ:
            return os.environ[env_name]
        env_val = os.environ.get(env_name)
        if env_val is not None and env_val != "":
            return env_val
        file_val = cls._load_file().get(key)
        if key == "job_template_prefix" and file_val is not None:
            return str(file_val)
        if file_val is not None and str(file_val) != "":
            return str(file_val)
        return default

    @classmethod
    def get_bool(cls, key: str) -> bool:
        return cls.get(key).lower() in ("true", "1", "yes")

    @classmethod
    def get_all(cls) -> dict[str, str]:
        """Return all AAP settings with resolved values."""
        return {k: cls.get(k) for k in _AAP_KEYS}

    @classmethod
    def source_of(cls, key: str) -> str:
        """Return where the active value comes from: 'env', 'file', or 'default'."""
        env_name, _ = _AAP_KEYS[key]
        if key == "job_template_prefix" and env_name in os.environ:
            return "env"
        env_val = os.environ.get(env_name)
        if env_val is not None and env_val != "":
            return "env"
        file_val = cls._load_file().get(key)
        if key == "job_template_prefix" and file_val is not None:
            return "file"
        if file_val is not None and str(file_val) != "":
            return "file"
        return "default"

    @classmethod
    def save(cls, settings: dict[str, str]) -> None:
        """Write AAP settings to .ansibleclaw.yml and update the cache."""
        path = cls._settings_path()
        existing: dict = {}
        if path.exists():
            try:
                existing = yaml.safe_load(path.read_text()) or {}
            except Exception:
                pass

        clean: dict[str, str] = {}
        for k, v in settings.items():
            if k not in _AAP_KEYS:
                continue
            if isinstance(v, str):
                v = v.strip()
            if k == "job_template_prefix":
                clean[k] = v
                continue
            if v:
                clean[k] = v
        existing["aap"] = clean
        path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))
        cls._file_cache = clean
        _ensure_gitignore()

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._file_cache = None


def local_inventory_path() -> Path:
    """Path to the on-disk inventory file for local / CLI workflows.

    Set ``ANSIBLECLAW_INVENTORY_FILE`` to override. Otherwise uses
    ``inventory/hosts.yml`` under the current working directory (AnsibleClaw
    project convention).
    """
    raw = os.environ.get("ANSIBLECLAW_INVENTORY_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / "inventory" / "hosts.yml"


def _ensure_gitignore() -> None:
    """Append .ansibleclaw.yml to .gitignore if not already present."""
    gi = Path.cwd() / ".gitignore"
    entry = SETTINGS_FILE
    if gi.exists():
        content = gi.read_text()
        if entry in content.splitlines():
            return
        if not content.endswith("\n"):
            content += "\n"
        gi.write_text(content + f"{entry}\n")
    else:
        gi.write_text(f"{entry}\n")


# Backward-compatible module-level accessors used by the rest of the codebase.
# These are now thin wrappers around AAPSettings so values update at runtime.

def _get(key: str) -> str:
    return AAPSettings.get(key)

def _get_bool(key: str) -> bool:
    return AAPSettings.get_bool(key)


class _AAPProxy:
    """Lazy descriptor so ``from config import AAP_CONTROLLER_URL`` still works
    but always returns the current resolved value."""

    def __init__(self, key: str, is_bool: bool = False):
        self._key = key
        self._is_bool = is_bool

    def __get__(self, obj: object, objtype: type | None = None) -> str | bool:
        return _get_bool(self._key) if self._is_bool else _get(self._key)


class _ConfigModule:
    """Provides attribute access that delegates AAP_* lookups to AAPSettings."""

    AAP_CONTROLLER_URL = _AAPProxy("url")
    AAP_CONTROLLER_TOKEN = _AAPProxy("token")
    AAP_VERIFY_SSL = _AAPProxy("verify_ssl", is_bool=True)
    AAP_DEFAULT_INVENTORY = _AAPProxy("default_inventory")
    AAP_DEFAULT_CREDENTIAL = _AAPProxy("default_credential")
    AAP_DEFAULT_ORGANIZATION = _AAPProxy("default_organization")
    AAP_DEFAULT_PROJECT = _AAPProxy("default_project")
    AAP_DEFAULT_EE = _AAPProxy("default_ee")
    AAP_DEFAULT_SCM_URL = _AAPProxy("default_scm_url")
    ANSIBLECLAW_JOB_TEMPLATE_PREFIX = _AAPProxy("job_template_prefix")


_cfg = _ConfigModule()

# Re-export so ``from ansibleclaw.config import AAP_CONTROLLER_URL`` keeps
# working.  At import time these resolve to the current value; at attribute
# access time on `_cfg` they are always live.  The web app should prefer
# ``AAPSettings.get()`` or ``_cfg.AAP_*`` for guaranteed freshness.
AAP_CONTROLLER_URL: str = os.environ.get("AAP_CONTROLLER_URL", "")
AAP_CONTROLLER_TOKEN: str = os.environ.get("AAP_CONTROLLER_TOKEN", "")
AAP_VERIFY_SSL: bool = os.environ.get("AAP_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
AAP_DEFAULT_INVENTORY: str = os.environ.get("AAP_DEFAULT_INVENTORY", "")
AAP_DEFAULT_CREDENTIAL: str = os.environ.get("AAP_DEFAULT_CREDENTIAL", "")
AAP_DEFAULT_ORGANIZATION: str = os.environ.get("AAP_DEFAULT_ORGANIZATION", "Default")
AAP_DEFAULT_PROJECT: str = os.environ.get("AAP_DEFAULT_PROJECT", "")
AAP_DEFAULT_EE: str = os.environ.get("AAP_DEFAULT_EE", "")
AAP_DEFAULT_SCM_URL: str = os.environ.get("AAP_DEFAULT_SCM_URL", "")
ANSIBLECLAW_JOB_TEMPLATE_PREFIX: str = os.environ.get(
    "ANSIBLECLAW_JOB_TEMPLATE_PREFIX", "AnsibleClaw: "
)
