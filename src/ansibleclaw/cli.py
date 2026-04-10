"""AnsibleClaw CLI entrypoint.

Subcommands:
    generate  -- Generate a skill package for an Ansible module
    compose   -- Generate a composite skill from multiple modules
    search    -- Search available Ansible modules by keyword
    uninstall -- Remove a skill from an agent platform install directory
    ui        -- Launch the web management dashboard
"""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from ansibleclaw import __version__
from ansibleclaw.config import INSTALL_PATHS, SKILLS_DIR, TEMPLATE_DIR, TEMPLATE_PATH
from ansibleclaw.core.parser import (
    AnsibleDocError,
    extract_module_metadata,
    get_module_doc,
    list_modules,
    resolve_module_doc,
    search_modules,
)


def _sanitize_skill_dir_name(name: str) -> str:
    """Sanitize a user-provided name into a safe directory name.

    Lowercases, replaces non-alphanumeric runs with underscores, strips
    leading/trailing underscores, and prepends ``ansible_``.
    """
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        slug = "unnamed"
    return f"ansible_{slug}"


def _module_to_skill_name(module_name: str) -> str:
    """Convert a module FQCN to a skill directory name.

    Includes the collection name for non-builtin modules to avoid collisions.
    e.g. 'ansible.builtin.package' -> 'ansible_package'
          'community.general.redis' -> 'ansible_general_redis'
          'community.docker.docker_container' -> 'ansible_docker_docker_container'
    """
    parts = module_name.split(".")
    if len(parts) >= 3 and f"{parts[0]}.{parts[1]}" != "ansible.builtin":
        return f"ansible_{parts[1]}_{parts[-1]}"
    return f"ansible_{parts[-1]}"


def _get_template_env():
    """Create a Jinja2 environment pointed at the templates directory."""
    from jinja2 import Environment, FileSystemLoader

    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _collection_fqcn(module_name: str) -> str:
    """Extract collection FQCN from a module name, or empty for builtins."""
    parts = module_name.split(".")
    if len(parts) >= 3 and f"{parts[0]}.{parts[1]}" != "ansible.builtin":
        return f"{parts[0]}.{parts[1]}"
    return ""


def _template_context(metadata: dict) -> dict:
    """Build the shared template context from module metadata."""
    from ansibleclaw.config import AAPSettings

    module_name = metadata["module_name"]
    params = metadata["params"]
    example_args = _build_example_args(params, metadata.get("examples", ""))
    ctx = {
        "module_name": module_name,
        "skill_name": _module_to_skill_name(module_name).replace("ansible_", ""),
        "short_description": metadata["short_description"],
        "params": params,
        "examples": metadata["examples"].strip() if metadata["examples"] else "",
        "example_args": example_args,
        "collection_fqcn": _collection_fqcn(module_name),
    }
    doc_source = metadata.get("doc_source", "local")
    if doc_source != "local":
        ctx["doc_source"] = doc_source
        ctx["doc_version"] = metadata.get("doc_version", "")
        ctx["doc_warning"] = metadata.get("doc_warning", "")

    aap_url = AAPSettings.get("url")
    aap_token = AAPSettings.get("token")
    ctx["aap_configured"] = bool(aap_url and aap_token)
    ctx["aap_url"] = aap_url
    ctx["aap_verify_ssl"] = AAPSettings.get("verify_ssl")
    ctx["aap_inventory"] = AAPSettings.get("default_inventory")
    ctx["aap_credential"] = AAPSettings.get("default_credential")
    ctx["aap_project"] = AAPSettings.get("default_project")
    ctx["aap_ee"] = AAPSettings.get("default_ee")
    ctx["aap_organization"] = AAPSettings.get("default_organization")
    scm = AAPSettings.get("default_scm_url").strip()
    ctx["aap_scm_url"] = scm

    return ctx


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

    for script_name in ("run.sh", "check.sh", "publish_playbook.sh"):
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

    if ctx.get("collection_fqcn"):
        req_template = env.get_template("requirements.yml.j2")
        (assets_dir / "requirements.yml").write_text(req_template.render(**ctx))


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


def _write_collection_skill_package(
    output_dir: Path,
    collection_fqcn: str,
    modules_metadata: list[dict],
) -> None:
    """Write a collection-level overview skill (SKILL.md + requirements.yml)."""
    env = _get_template_env()
    template = env.get_template("collection_skill_template.md")

    parts = collection_fqcn.split(".")
    collection_name = parts[1] if len(parts) == 2 else collection_fqcn

    ctx = {
        "collection_fqcn": collection_fqcn,
        "collection_name": collection_name,
        "modules": modules_metadata,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "SKILL.md").write_text(template.render(**ctx))

    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    req_template = env.get_template("requirements.yml.j2")
    (assets_dir / "requirements.yml").write_text(
        req_template.render(
            module_name=f"{collection_fqcn} (collection)",
            collection_fqcn=collection_fqcn,
        )
    )


# ---------------------------------------------------------------------------
# Recipe parsing for composite skills
# ---------------------------------------------------------------------------


def _parse_recipe(path: Path) -> dict[str, Any]:
    """Parse a compose recipe YAML file.

    Supports two formats:

    Simple (module list as strings)::

        name: web-server-setup
        description: Deploy and configure a web server
        modules:
          - ansible.builtin.package
          - ansible.builtin.service

    Extended (modules with pre-filled vars)::

        name: web-server-setup
        description: Deploy and configure a web server
        modules:
          - name: ansible.builtin.package
            vars:
              name: nginx
              state: present

    Returns ``{"name": str, "description": str, "modules": list}``
    where each module entry is ``{"name": str, "vars": dict | None}``.
    """
    import yaml

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Recipe file must be a YAML mapping, got {type(raw).__name__}")

    name = raw.get("name", "")
    if not name:
        raise ValueError("Recipe file must contain a 'name' field")

    description = raw.get("description", "")
    raw_modules = raw.get("modules", [])
    if not raw_modules:
        raise ValueError("Recipe file must contain a non-empty 'modules' list")

    modules: list[dict[str, Any]] = []
    for entry in raw_modules:
        if isinstance(entry, str):
            modules.append({"name": entry, "vars": None})
        elif isinstance(entry, dict):
            mod_name = entry.get("name", "")
            if not mod_name:
                raise ValueError(f"Module entry must have a 'name' field: {entry}")
            modules.append({"name": mod_name, "vars": entry.get("vars")})
        else:
            raise ValueError(f"Invalid module entry: {entry}")

    return {"name": name, "description": description, "modules": modules}


# ---------------------------------------------------------------------------
# Composite skill context and writer
# ---------------------------------------------------------------------------


def _composite_template_context(
    name: str,
    description: str,
    modules_metadata: list[dict],
) -> dict:
    """Build template context for a multi-module composite skill."""
    from ansibleclaw.config import AAPSettings

    collection_fqcns = sorted({
        _collection_fqcn(m["module_name"])
        for m in modules_metadata
        if _collection_fqcn(m["module_name"])
    })

    ctx: dict[str, Any] = {
        "skill_name": name,
        "description": description,
        "modules": modules_metadata,
        "collection_fqcns": collection_fqcns,
    }

    aap_url = AAPSettings.get("url")
    aap_token = AAPSettings.get("token")
    ctx["aap_configured"] = bool(aap_url and aap_token)
    ctx["aap_url"] = aap_url
    ctx["aap_verify_ssl"] = AAPSettings.get("verify_ssl")
    ctx["aap_inventory"] = AAPSettings.get("default_inventory")
    ctx["aap_credential"] = AAPSettings.get("default_credential")
    ctx["aap_project"] = AAPSettings.get("default_project")
    ctx["aap_ee"] = AAPSettings.get("default_ee")
    ctx["aap_organization"] = AAPSettings.get("default_organization")
    ctx["aap_scm_url"] = AAPSettings.get("default_scm_url").strip()

    return ctx


def _render_composite_skill(
    name: str,
    description: str,
    modules_metadata: list[dict],
) -> str:
    """Render the composite skill template and return SKILL.md content."""
    env = _get_template_env()
    template = env.get_template("composite_skill_template.md")
    ctx = _composite_template_context(name, description, modules_metadata)
    return template.render(**ctx)


def _write_composite_skill_package(
    output_dir: Path,
    name: str,
    description: str,
    modules_metadata: list[dict],
) -> None:
    """Write the full composite skill package."""
    env = _get_template_env()
    ctx = _composite_template_context(name, description, modules_metadata)

    output_dir.mkdir(parents=True, exist_ok=True)

    skill_template = env.get_template("composite_skill_template.md")
    (output_dir / "SKILL.md").write_text(skill_template.render(**ctx))

    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    for script_name in ("composite_run.sh", "composite_check.sh", "composite_publish_playbook.sh"):
        template = env.get_template(f"{script_name}.j2")
        out_name = script_name.replace("composite_", "")
        script_path = scripts_dir / out_name
        script_path.write_text(template.render(**ctx))
        script_path.chmod(
            script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
        )

    aap_template = env.get_template("composite_aap_run.py.j2")
    aap_path = scripts_dir / "aap_run.py"
    aap_path.write_text(aap_template.render(**ctx))
    aap_path.chmod(aap_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    playbook_template = env.get_template("composite_playbook.yml.j2")
    (assets_dir / "playbook.yml").write_text(playbook_template.render(**ctx))

    if ctx["collection_fqcns"]:
        req_template = env.get_template("composite_requirements.yml.j2")
        (assets_dir / "requirements.yml").write_text(req_template.render(**ctx))


def _generate_single(
    module_name: str,
    args: argparse.Namespace,
) -> Path:
    """Generate a single module skill and return its output dir."""
    auto_install = getattr(args, "auto_install", False)
    collection_version = getattr(args, "collection_version", None)

    doc, doc_meta = resolve_module_doc(
        module_name,
        collection_version=collection_version,
        auto_install=auto_install,
    )

    if doc_meta.get("doc_source") == "galaxy":
        ver = doc_meta.get("doc_version", "")
        print(f"  (sourced from Galaxy, collection version {ver})")
        if doc_meta.get("doc_warning"):
            print(f"  Warning: {doc_meta['doc_warning']}")

    metadata = extract_module_metadata(doc)
    metadata.update(doc_meta)
    skill_name = _module_to_skill_name(metadata["module_name"])
    output_dir = _resolve_output_dir(args, skill_name)

    _write_skill_package(output_dir, metadata)
    return output_dir


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate skill package(s) for Ansible module(s) or a whole collection."""
    collection = getattr(args, "collection", None)

    if collection:
        filter_modules = None
        if getattr(args, "modules", None):
            filter_modules = {
                m.strip() for m in args.modules.split(",") if m.strip()
            }

        print(f"Listing modules in {collection}...")
        try:
            all_modules = list_modules(namespace=collection)
        except AnsibleDocError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        if filter_modules:
            target_modules = {}
            for name, desc in all_modules.items():
                short = name.rsplit(".", 1)[-1]
                if name in filter_modules or short in filter_modules:
                    target_modules[name] = desc
            if not target_modules:
                print(f"Error: none of the specified modules found in {collection}", file=sys.stderr)
                sys.exit(1)
        else:
            target_modules = all_modules

        print(f"Generating skills for {len(target_modules)} module(s)...")
        successes = 0
        failures = 0
        for module_name in sorted(target_modules.keys()):
            print(f"  {module_name}...", end=" ")
            try:
                output_dir = _generate_single(module_name, args)
                print(f"-> {output_dir.name}")
                successes += 1
            except Exception as exc:
                print(f"FAILED: {exc}")
                failures += 1

        print(f"\nDone: {successes} generated, {failures} failed.")
        return

    module_name = args.module
    if not module_name:
        print("Error: module name is required (or use --collection)", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching documentation for {module_name}...")
    try:
        output_dir = _generate_single(module_name, args)
    except AnsibleDocError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Skill generated: {output_dir}/")
    print(
        "  SKILL.md, scripts/run.sh, scripts/check.sh, scripts/publish_playbook.sh, "
        "scripts/aap_run.py, assets/playbook.yml"
    )

    if getattr(args, "zip", False):
        from ansibleclaw.core.packager import package_skill_zip
        zip_path = package_skill_zip(output_dir)
        print(f"  Packaged: {zip_path}")


def cmd_compose(args: argparse.Namespace) -> None:
    """Generate a composite skill package from multiple Ansible modules."""
    auto_install = getattr(args, "auto_install", False)
    collection_version = getattr(args, "collection_version", None)

    if args.file:
        recipe_path = Path(args.file)
        if not recipe_path.exists():
            print(f"Error: recipe file not found: {recipe_path}", file=sys.stderr)
            sys.exit(1)
        try:
            recipe = _parse_recipe(recipe_path)
        except (ValueError, Exception) as exc:
            print(f"Error: invalid recipe file: {exc}", file=sys.stderr)
            sys.exit(1)
        name = args.name or recipe["name"]
        description = args.description or recipe.get("description", "")
        module_entries = recipe["modules"]
    elif args.modules:
        if not args.name:
            print("Error: --name is required when using --modules", file=sys.stderr)
            sys.exit(1)
        name = args.name
        description = args.description or ""
        raw_modules = [m.strip() for m in args.modules.split(",") if m.strip()]
        if not raw_modules:
            print("Error: --modules must contain at least one module", file=sys.stderr)
            sys.exit(1)
        module_entries = [{"name": m, "vars": None} for m in raw_modules]
    else:
        print("Error: --modules or --file is required", file=sys.stderr)
        sys.exit(1)

    if not description:
        description = f"Composite skill combining {len(module_entries)} Ansible modules"

    skill_dir_name = _sanitize_skill_dir_name(name)

    print(f"Composing skill '{name}' from {len(module_entries)} module(s)...")
    modules_metadata: list[dict] = []
    for entry in module_entries:
        module_name = entry["name"]
        print(f"  Fetching docs for {module_name}...", end=" ")
        try:
            doc, doc_meta = resolve_module_doc(
                module_name,
                collection_version=collection_version,
                auto_install=auto_install,
            )
            metadata = extract_module_metadata(doc)
            metadata.update(doc_meta)
            if entry.get("vars"):
                metadata["prefilled_vars"] = entry["vars"]
            modules_metadata.append(metadata)
            print("OK")
        except AnsibleDocError as exc:
            print(f"FAILED: {exc}")
            sys.exit(1)

    output_dir = _resolve_output_dir(args, skill_dir_name)
    _write_composite_skill_package(output_dir, name, description, modules_metadata)

    print(f"\nComposite skill generated: {output_dir}/")
    print(
        "  SKILL.md, scripts/run.sh, scripts/check.sh, scripts/publish_playbook.sh, "
        "scripts/aap_run.py, assets/playbook.yml"
    )

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


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Remove a skill directory from an agent platform install path."""
    platform = args.platform.lower()
    if platform not in INSTALL_PATHS:
        supported = ", ".join(sorted(INSTALL_PATHS))
        print(f"Error: Unknown platform '{platform}'. Supported: {supported}", file=sys.stderr)
        sys.exit(1)
    skill_name = args.skill_name.strip()
    if not skill_name:
        print("Error: skill name is required (directory name, e.g. ansible_package)", file=sys.stderr)
        sys.exit(1)
    target = INSTALL_PATHS[platform] / skill_name
    if not target.exists():
        print(f"Nothing to remove: {target} does not exist.")
        return
    if not target.is_dir():
        print(f"Error: {target} is not a directory", file=sys.stderr)
        sys.exit(1)
    shutil.rmtree(target)
    print(f"Removed {target}")


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
    gen_parser.add_argument("module", nargs="?", default="", help="Fully-qualified module name (e.g., ansible.builtin.package)")
    gen_parser.add_argument(
        "--install", metavar="PLATFORM",
        help="Install to agent platform (cursor, claude, gemini)",
    )
    gen_parser.add_argument("--output", metavar="DIR", help="Custom output directory")
    gen_parser.add_argument("--zip", action="store_true", help="Also create a .zip archive for distribution")
    gen_parser.add_argument(
        "--auto-install", action="store_true",
        help="Automatically install the collection via ansible-galaxy if not present locally",
    )
    gen_parser.add_argument(
        "--collection-version", metavar="VER",
        help="Pin the collection version for Galaxy fallback docs (e.g., 9.2.0)",
    )
    gen_parser.add_argument(
        "--collection", metavar="FQCN",
        help="Generate skills for all modules in a collection (e.g., ansible.posix)",
    )
    gen_parser.add_argument(
        "--modules", metavar="LIST",
        help="Comma-separated module short names to include (used with --collection)",
    )
    gen_parser.set_defaults(func=cmd_generate)

    # --- compose ---
    compose_parser = subparsers.add_parser(
        "compose",
        help="Generate a composite skill from multiple modules.",
    )
    compose_parser.add_argument(
        "--name", metavar="NAME",
        help="Skill name (e.g., web-server-setup). Required with --modules.",
    )
    compose_parser.add_argument(
        "--description", metavar="TEXT",
        help="Short description of the composite skill",
    )
    compose_parser.add_argument(
        "--modules", metavar="LIST",
        help="Comma-separated module FQCNs (e.g., ansible.builtin.package,ansible.builtin.service)",
    )
    compose_parser.add_argument(
        "-f", "--file", metavar="PATH",
        help="Recipe YAML file defining the composition",
    )
    compose_parser.add_argument(
        "--install", metavar="PLATFORM",
        help="Install to agent platform (cursor, claude, gemini)",
    )
    compose_parser.add_argument("--output", metavar="DIR", help="Custom output directory")
    compose_parser.add_argument("--zip", action="store_true", help="Also create a .zip archive")
    compose_parser.add_argument(
        "--auto-install", action="store_true",
        help="Automatically install collections via ansible-galaxy if not present locally",
    )
    compose_parser.add_argument(
        "--collection-version", metavar="VER",
        help="Pin the collection version for Galaxy fallback docs",
    )
    compose_parser.set_defaults(func=cmd_compose)

    # --- search ---
    search_parser = subparsers.add_parser(
        "search",
        help="Search available Ansible modules by keyword.",
    )
    search_parser.add_argument("keyword", nargs="?", default="", help="Search term")
    search_parser.add_argument("--namespace", "-n", help="Filter by namespace (e.g., community.docker)")
    search_parser.add_argument("--detail", metavar="MODULE", help="Show full docs for a specific module")
    search_parser.set_defaults(func=cmd_search)

    # --- uninstall ---
    uninst_parser = subparsers.add_parser(
        "uninstall",
        help="Remove a skill from an agent platform directory (~/.cursor/skills, etc.).",
    )
    uninst_parser.add_argument(
        "skill_name",
        help="Skill directory name (e.g. ansible_package)",
    )
    uninst_parser.add_argument(
        "--platform", metavar="PLATFORM", required=True,
        help=f"Agent platform: {', '.join(sorted(INSTALL_PATHS))}",
    )
    uninst_parser.set_defaults(func=cmd_uninstall)

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
