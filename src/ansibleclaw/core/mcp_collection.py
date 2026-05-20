"""Ansible collection generator from MCP tool definitions.

Uses ``ansible-creator`` to scaffold a standards-compliant collection,
then replaces the sample files with generated MCP module wrappers.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from ansibleclaw.core.mcp_schema import McpSchemaError, mcp_tool_to_metadata


def _get_template_env():
    """Create a Jinja2 environment pointed at the templates directory."""
    from jinja2 import Environment, FileSystemLoader

    from ansibleclaw.config import TEMPLATE_DIR

    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _find_ansible_creator() -> str:
    """Locate the ansible-creator binary."""
    env_bin = Path(sys.executable).parent / "ansible-creator"
    if env_bin.exists():
        return str(env_bin)
    found = shutil.which("ansible-creator")
    if found:
        return found
    raise McpSchemaError(
        "ansible-creator not found. Install it: pip install ansible-creator"
    )


def write_mcp_collection(
    output_dir: Path,
    namespace: str,
    name: str,
    version: str,
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate a full Ansible collection from MCP tool definitions.

    1. Scaffolds with ansible-creator for standards-compliant structure
    2. Removes sample files
    3. Writes generated MCP modules and action plugin
    4. Patches galaxy.yml and runtime.yml

    Returns the list of module metadata dicts that were generated.
    """
    env = _get_template_env()

    modules: list[dict[str, Any]] = []
    for tool in tools:
        metadata = mcp_tool_to_metadata(tool, namespace, name)
        modules.append(metadata)

    _scaffold_collection(output_dir, namespace, name)
    _remove_sample_files(output_dir)
    _patch_galaxy_yml(output_dir, namespace, name, version)
    _patch_runtime_yml(output_dir, namespace, name, modules)
    _write_readme(env, output_dir, namespace, name, modules)
    _write_action_plugin(env, output_dir)
    _write_modules(env, output_dir, modules)

    return modules


def _scaffold_collection(output_dir: Path, namespace: str, name: str) -> None:
    """Run ansible-creator to scaffold the collection structure."""
    creator = _find_ansible_creator()
    collection_fqcn = f"{namespace}.{name}"

    parent_dir = output_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    cmd = [creator, "init", "collection", collection_fqcn, str(output_dir)]

    if output_dir.exists():
        cmd.append("--overwrite")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise McpSchemaError(
            "ansible-creator not found. Install it: pip install ansible-creator"
        )
    except subprocess.TimeoutExpired:
        raise McpSchemaError("ansible-creator timed out.")

    if result.returncode != 0:
        raise McpSchemaError(
            f"ansible-creator failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )


def _remove_sample_files(output_dir: Path) -> None:
    """Remove ansible-creator sample/example files."""
    sample_files = [
        "plugins/modules/sample_module.py",
        "plugins/modules/sample_action.py",
        "plugins/action/sample_action.py",
        "plugins/filter/sample_filter.py",
        "plugins/lookup/sample_lookup.py",
        "plugins/test/sample_test.py",
    ]
    for rel_path in sample_files:
        path = output_dir / rel_path
        if path.exists():
            path.unlink()

    sample_dirs = [
        "roles/run",
        "extensions/eda",
        "tests/integration/targets/hello_world",
        "extensions/molecule/integration_hello_world",
    ]
    for rel_path in sample_dirs:
        path = output_dir / rel_path
        if path.exists():
            shutil.rmtree(path)


def _patch_galaxy_yml(
    output_dir: Path, namespace: str, name: str, version: str,
) -> None:
    """Update galaxy.yml with MCP-specific metadata."""
    galaxy_path = output_dir / "galaxy.yml"
    data = yaml.safe_load(galaxy_path.read_text())

    data["namespace"] = namespace
    data["name"] = name
    data["version"] = version
    data["description"] = (
        "Ansible collection generated from MCP server tools. "
        "Provides typed module wrappers with argument validation "
        "that delegate to ansible.mcp.run_tool at runtime."
    )
    data["tags"] = ["mcp", "tools", "ai"]
    data["dependencies"] = {"ansible.mcp": "*"}

    galaxy_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _patch_runtime_yml(
    output_dir: Path, namespace: str, name: str,
    modules: list[dict[str, Any]],
) -> None:
    """Update runtime.yml with action plugin routing for all modules."""
    runtime_path = output_dir / "meta" / "runtime.yml"
    data = yaml.safe_load(runtime_path.read_text()) or {}

    proxy_fqcn = f"{namespace}.{name}._mcp_proxy"
    routing = {}
    for m in modules:
        routing[m["module_name"]] = {"redirect": proxy_fqcn}

    data["plugin_routing"] = {"action": routing}

    runtime_path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False)
    )


def _write_readme(
    env, output_dir: Path, namespace: str, name: str,
    modules: list[dict[str, Any]],
) -> None:
    template = env.get_template("mcp_readme.md.j2")
    content = template.render(
        namespace=namespace,
        collection_name=name,
        modules=modules,
    )
    (output_dir / "README.md").write_text(content)


def _write_action_plugin(env, output_dir: Path) -> None:
    template = env.get_template("mcp_action_plugin.py.j2")
    content = template.render()
    action_dir = output_dir / "plugins" / "action"
    action_dir.mkdir(parents=True, exist_ok=True)
    (action_dir / "_mcp_proxy.py").write_text(content)


def _write_modules(
    env, output_dir: Path, modules: list[dict[str, Any]],
) -> None:
    template = env.get_template("mcp_module.py.j2")
    modules_dir = output_dir / "plugins" / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    for metadata in modules:
        content = template.render(**metadata)
        module_file = modules_dir / f"{metadata['module_name']}.py"
        module_file.write_text(content)
