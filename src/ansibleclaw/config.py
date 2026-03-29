"""Central configuration for AnsibleClaw."""

import os
from pathlib import Path

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

# AAP Controller settings (read from environment, used by web UI and builtins;
# generated skills read these at runtime independently).
AAP_CONTROLLER_URL: str = os.environ.get("AAP_CONTROLLER_URL", "")
AAP_CONTROLLER_TOKEN: str = os.environ.get("AAP_CONTROLLER_TOKEN", "")
AAP_VERIFY_SSL: bool = os.environ.get("AAP_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
AAP_DEFAULT_INVENTORY: str = os.environ.get("AAP_DEFAULT_INVENTORY", "")
AAP_DEFAULT_CREDENTIAL: str = os.environ.get("AAP_DEFAULT_CREDENTIAL", "")
AAP_DEFAULT_ORGANIZATION: str = os.environ.get("AAP_DEFAULT_ORGANIZATION", "Default")
