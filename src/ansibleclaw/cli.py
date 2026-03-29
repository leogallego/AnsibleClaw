"""AnsibleClaw CLI entrypoint.

Subcommands:
    generate  -- Generate a skill package for an Ansible module
    search    -- Search available Ansible modules by keyword
    ui        -- Launch the web management dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from ansibleclaw import __version__
from ansibleclaw.config import INSTALL_PATHS, SKILLS_DIR, TEMPLATE_DIR, TEMPLATE_PATH
from ansibleclaw.core.parser import (
    AnsibleDocError,
    extract_module_metadata,
    get_module_doc,
    search_modules,
)


def _module_to_skill_name(module_name: str) -> str:
    """Convert a module FQCN to a skill directory name.

    e.g. 'ansible.builtin.package' -> 'ansible_package'
          'community.general.redis' -> 'ansible_redis'
    """
    short = module_name.rsplit(".", 1)[-1]
    return f"ansible_{short}"


def _get_template_env():
    """Create a Jinja2 environment pointed at the templates directory."""
    from jinja2 import Environment, FileSystemLoader

    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _template_context(metadata: dict) -> dict:
    """Build the shared template context from module metadata."""
    params = metadata["params"]
    example_args = _build_example_args(params, metadata.get("examples", ""))
    return {
        "module_name": metadata["module_name"],
        "skill_name": _module_to_skill_name(metadata["module_name"]).replace("ansible_", ""),
        "short_description": metadata["short_description"],
        "params": params,
        "examples": metadata["examples"].strip() if metadata["examples"] else "",
        "example_args": example_args,
    }


def _render_skill(metadata: dict) -> str:
    """Render the skill template with the given module metadata."""
    env = _get_template_env()
    template = env.get_template(TEMPLATE_PATH.name)
    return template.render(**_template_context(metadata))


def _write_skill_package(output_dir: Path, metadata: dict) -> None:
    """Write the full skill package: SKILL.md + scripts + assets."""
    env = _get_template_env()
    ctx = _template_context(metadata)

    output_dir.mkdir(parents=True, exist_ok=True)

    skill_template = env.get_template(TEMPLATE_PATH.name)
    (output_dir / "SKILL.md").write_text(skill_template.render(**ctx))

    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    for script_name in ("run.sh", "check.sh"):
        template = env.get_template(f"{script_name}.j2")
        script_path = scripts_dir / script_name
        script_path.write_text(template.render(**ctx))
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    aap_template = env.get_template("aap_run.py.j2")
    aap_path = scripts_dir / "aap_run.py"
    aap_path.write_text(aap_template.render(**ctx))
    aap_path.chmod(aap_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    playbook_template = env.get_template("playbook.yml.j2")
    (assets_dir / "playbook.yml").write_text(playbook_template.render(**ctx))


def _build_example_args(params: list[dict], examples_yaml: str = "") -> str:
    """Build a representative example args string from parameters.

    Tries to extract concrete values from ansible-doc examples first,
    then falls back to parameter metadata.
    """
    concrete = _extract_example_values(examples_yaml)

    parts = []
    for p in params:
        if p["required"]:
            name = p["name"]
            if name in concrete:
                parts.append(f"{name}={concrete[name]}")
            elif p["choices"]:
                parts.append(f"{name}={p['choices'][0]}")
            elif p["type"] == "bool":
                parts.append(f"{name}=true")
            else:
                parts.append(f"{name}=<{name}>")
    if not parts:
        for p in params[:2]:
            name = p["name"]
            if name in concrete:
                parts.append(f"{name}={concrete[name]}")
            elif p["default"] is not None:
                parts.append(f"{name}={p['default']}")
            elif p["choices"]:
                parts.append(f"{name}={p['choices'][0]}")
            else:
                parts.append(f"{name}=<{name}>")
    return " ".join(parts) if parts else "name=<value>"


def _extract_example_values(examples_yaml: str) -> dict[str, str]:
    """Pull concrete parameter values from the first YAML example block."""
    values: dict[str, str] = {}
    if not examples_yaml:
        return values
    for line in examples_yaml.splitlines():
        line = line.strip()
        if line.startswith("- name:") or line.startswith("#") or not line:
            continue
        if ":" in line and not line.endswith(":"):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and not val.startswith("{") and not val.startswith("["):
                values.setdefault(key, val)
    return values


def _resolve_output_dir(args: argparse.Namespace, skill_name: str) -> Path:
    """Determine the output directory based on CLI flags."""
    if args.install:
        platform = args.install.lower()
        if platform not in INSTALL_PATHS:
            supported = ", ".join(INSTALL_PATHS.keys())
            print(f"Error: Unknown platform '{platform}'. Supported: {supported}", file=sys.stderr)
            sys.exit(1)
        return INSTALL_PATHS[platform] / skill_name
    elif args.output:
        return Path(args.output) / skill_name
    else:
        return SKILLS_DIR / skill_name


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a full skill package for the specified Ansible module."""
    module_name = args.module

    print(f"Fetching documentation for {module_name}...")
    try:
        doc = get_module_doc(module_name)
    except AnsibleDocError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    metadata = extract_module_metadata(doc)
    skill_name = _module_to_skill_name(metadata["module_name"])
    output_dir = _resolve_output_dir(args, skill_name)

    _write_skill_package(output_dir, metadata)
    print(f"Skill generated: {output_dir}/")
    print(f"  SKILL.md, scripts/run.sh, scripts/check.sh, scripts/aap_run.py, assets/playbook.yml")

    if getattr(args, "zip", False):
        from ansibleclaw.core.packager import package_skill_zip
        zip_path = package_skill_zip(output_dir)
        print(f"  Packaged: {zip_path}")


def cmd_search(args: argparse.Namespace) -> None:
    """Search for Ansible modules by keyword."""
    keyword = args.keyword
    namespace = args.namespace

    if args.detail:
        try:
            doc = get_module_doc(args.detail)
        except AnsibleDocError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(doc, indent=2))
        return

    print(f"Searching for '{keyword}'", end="")
    if namespace:
        print(f" in {namespace}...", end="")
    print()

    try:
        results = search_modules(keyword, namespace)
    except AnsibleDocError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No modules found.")
        return

    max_name_len = max(len(name) for name in results)
    for name, desc in sorted(results.items()):
        print(f"  {name:<{max_name_len}}  {desc or ''}")
    print(f"\n{len(results)} module(s) found.")


def cmd_ui(args: argparse.Namespace) -> None:
    """Launch the web management dashboard."""
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: Web UI dependencies not installed.\n"
            "Install them with: pip install ansibleclaw[ui]",
            file=sys.stderr,
        )
        sys.exit(1)

    from ansibleclaw.web.app import app

    port = args.port
    print(f"Starting AnsibleClaw UI at http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ansibleclaw",
        description="AnsibleClaw -- Ansible skill generation framework for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- generate ---
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate a SKILL.md for an Ansible module.",
    )
    gen_parser.add_argument("module", help="Fully-qualified module name (e.g., ansible.builtin.package)")
    gen_parser.add_argument("--install", metavar="PLATFORM", help="Install to agent platform (cursor, claude)")
    gen_parser.add_argument("--output", metavar="DIR", help="Custom output directory")
    gen_parser.add_argument("--zip", action="store_true", help="Also create a .zip archive for distribution")
    gen_parser.set_defaults(func=cmd_generate)

    # --- search ---
    search_parser = subparsers.add_parser(
        "search",
        help="Search available Ansible modules by keyword.",
    )
    search_parser.add_argument("keyword", nargs="?", default="", help="Search term")
    search_parser.add_argument("--namespace", "-n", help="Filter by namespace (e.g., community.docker)")
    search_parser.add_argument("--detail", metavar="MODULE", help="Show full docs for a specific module")
    search_parser.set_defaults(func=cmd_search)

    # --- ui ---
    ui_parser = subparsers.add_parser(
        "ui",
        help="Launch the web management dashboard.",
    )
    ui_parser.add_argument("--port", type=int, default=8600, help="Port to listen on (default: 8600)")
    ui_parser.set_defaults(func=cmd_ui)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
