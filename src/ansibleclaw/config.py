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
AAP_DEFAULT_PROJECT: str = os.environ.get("AAP_DEFAULT_PROJECT", "")
AAP_DEFAULT_EE: str = os.environ.get("AAP_DEFAULT_EE", "")

# Collection resolution settings
COLLECTIONS_PATH: str = os.environ.get("ANSIBLECLAW_COLLECTIONS_PATH", "")
GALAXY_URL: str = os.environ.get(
    "ANSIBLECLAW_GALAXY_URL", "https://galaxy.ansible.com"
)
