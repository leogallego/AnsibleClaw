"""Ansible module documentation scraper.

Wraps `ansible-doc` CLI to extract structured module information
for skill generation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class AnsibleDocError(Exception):
    """Raised when ansible-doc fails or returns unexpected output."""


def _find_ansible_doc() -> str:
    """Locate the ansible-doc binary, preferring the current Python environment."""
    env_bin = Path(sys.executable).parent / "ansible-doc"
    if env_bin.exists():
        return str(env_bin)
    found = shutil.which("ansible-doc")
    if found:
        return found
    raise AnsibleDocError(
        "ansible-doc not found. Install ansible-core: pip install ansible-core"
    )


def _run_ansible_doc(*args: str) -> str:
    """Execute ansible-doc with the given arguments and return stdout."""
    ansible_doc = _find_ansible_doc()
    cmd = [ansible_doc, *args]
    env = None
    from ansibleclaw.config import COLLECTIONS_PATH
    if COLLECTIONS_PATH:
        env = {**os.environ, "ANSIBLE_COLLECTIONS_PATH": COLLECTIONS_PATH}
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except FileNotFoundError:
        raise AnsibleDocError(
            "ansible-doc not found. Install ansible-core: pip install ansible-core"
        )
    except subprocess.TimeoutExpired:
        raise AnsibleDocError(f"ansible-doc timed out: {' '.join(cmd)}")

    if result.returncode != 0:
        raise AnsibleDocError(
            f"ansible-doc failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def get_module_doc(module_name: str) -> dict[str, Any]:
    """Fetch full documentation for a single module.

    Returns the parsed JSON from `ansible-doc <module> --json`.
    The top-level dict is keyed by the fully-qualified module name.

    Raises :class:`AnsibleDocError` when the module cannot be found or
    when ``ansible-doc`` returns empty/invalid output.
    """
    raw = _run_ansible_doc(module_name, "--json")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnsibleDocError(f"Failed to parse ansible-doc JSON: {exc}")
    if not doc:
        raise AnsibleDocError(
            f"Module '{module_name}' not found (ansible-doc returned empty output)."
        )
    return doc


def list_modules(namespace: str | None = None) -> dict[str, str]:
    """List available modules with short descriptions.

    Args:
        namespace: Optional namespace filter (e.g., "community.docker").
                   If None, lists all modules.

    Returns:
        Dict mapping fully-qualified module names to their short descriptions.
    """
    args = ["--list", "--json"]
    if namespace:
        args.append(namespace)
    raw = _run_ansible_doc(*args)
    try:
        modules = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnsibleDocError(f"Failed to parse module list JSON: {exc}")
    return modules


def search_modules(keyword: str, namespace: str | None = None) -> dict[str, str]:
    """Search modules by keyword in name or description.

    Args:
        keyword: Search term (case-insensitive).
        namespace: Optional namespace to restrict the search.

    Returns:
        Filtered dict of matching module names -> descriptions.
    """
    all_modules = list_modules(namespace)
    keyword_lower = keyword.lower()
    return {
        name: desc
        for name, desc in all_modules.items()
        if keyword_lower in name.lower() or keyword_lower in (desc or "").lower()
    }


def extract_params(module_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract parameter specs from a module doc.

    Args:
        module_doc: The full JSON from get_module_doc().

    Returns:
        List of parameter dicts with keys:
        name, type, required, default, choices, description, aliases
    """
    module_name = _get_module_name(module_doc)
    doc_entry = module_doc[module_name].get("doc", {})
    options = doc_entry.get("options", {})

    params = []
    for param_name, spec in options.items():
        description = spec.get("description", [])
        if isinstance(description, list):
            description = " ".join(description)

        params.append({
            "name": param_name,
            "type": spec.get("type", "str"),
            "required": spec.get("required", False),
            "default": spec.get("default"),
            "choices": spec.get("choices"),
            "description": description,
            "aliases": spec.get("aliases", []),
        })

    params.sort(key=lambda p: (not p["required"], p["name"]))
    return params


def extract_examples(module_doc: dict[str, Any]) -> str:
    """Extract example YAML snippets from a module doc.

    Returns the raw examples string (YAML) from ansible-doc.
    """
    module_name = _get_module_name(module_doc)
    return module_doc[module_name].get("examples", "")


def _get_module_name(module_doc: dict[str, Any]) -> str:
    """Return the first key from a module doc dict, or raise on empty."""
    if not module_doc:
        raise AnsibleDocError("Module not found or ansible-doc returned empty output.")
    return next(iter(module_doc))


def extract_short_description(module_doc: dict[str, Any]) -> str:
    """Extract the module's one-line description."""
    module_name = _get_module_name(module_doc)
    doc_entry = module_doc[module_name].get("doc", {})
    desc = doc_entry.get("short_description", "")
    return desc.strip() if desc else ""


def extract_module_metadata(module_doc: dict[str, Any]) -> dict[str, Any]:
    """Extract all metadata needed for skill generation.

    Convenience function that combines extract_params, extract_examples,
    and extract_short_description into a single dict.
    """
    module_name = _get_module_name(module_doc)
    return {
        "module_name": module_name,
        "short_description": extract_short_description(module_doc),
        "params": extract_params(module_doc),
        "examples": extract_examples(module_doc),
    }


# ---------------------------------------------------------------------------
# Fallback resolution: local ansible-doc -> Galaxy API
# ---------------------------------------------------------------------------

def resolve_module_doc(
    module_name: str,
    collection_version: str | None = None,
    auto_install: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve module documentation with a fallback chain.

    1. Try local ``ansible-doc`` (ground truth).
    2. If *auto_install* is True, attempt ``ansible-galaxy collection install``
       and retry local.
    3. Fall back to Galaxy REST API.

    Returns ``(module_doc, meta)`` where *meta* contains at minimum
    ``{"doc_source": "local"|"galaxy"}`` plus optional ``doc_version``
    and ``doc_warning`` when Galaxy was used.
    """
    local_err: AnsibleDocError | None = None
    try:
        doc = get_module_doc(module_name)
        return doc, {"doc_source": "local"}
    except AnsibleDocError as exc:
        local_err = exc

    if auto_install:
        collection_fqcn = _extract_collection_fqcn(module_name)
        if collection_fqcn:
            try:
                install_collection(collection_fqcn)
                doc = get_module_doc(module_name)
                return doc, {"doc_source": "local"}
            except (AnsibleDocError, subprocess.SubprocessError):
                pass

    try:
        from ansibleclaw.core.galaxy import GalaxyDocProvider, detect_pinned_version
        provider = GalaxyDocProvider()
        version = collection_version or detect_pinned_version(module_name)
        return provider.fetch_module_doc(module_name, version=version)
    except Exception as galaxy_err:
        raise AnsibleDocError(
            f"Module documentation unavailable.\n"
            f"  Local:  {local_err}\n"
            f"  Galaxy: {galaxy_err}\n"
            f"Hint: install the collection with "
            f"ansible-galaxy collection install "
            f"{_extract_collection_fqcn(module_name) or module_name}"
        )


# ---------------------------------------------------------------------------
# Collection management helpers
# ---------------------------------------------------------------------------

def _extract_collection_fqcn(module_name: str) -> str:
    """Extract ``namespace.collection`` from a module FQCN."""
    parts = module_name.split(".")
    if len(parts) >= 3 and f"{parts[0]}.{parts[1]}" != "ansible.builtin":
        return f"{parts[0]}.{parts[1]}"
    return ""


def install_collection(collection_fqcn: str, version: str | None = None) -> None:
    """Install a collection via ``ansible-galaxy collection install``."""
    galaxy_bin = Path(sys.executable).parent / "ansible-galaxy"
    if not galaxy_bin.exists():
        found = shutil.which("ansible-galaxy")
        if not found:
            raise AnsibleDocError("ansible-galaxy not found")
        galaxy_bin = Path(found)

    target = f"{collection_fqcn}:{version}" if version else collection_fqcn
    cmd = [str(galaxy_bin), "collection", "install", target, "--force"]
    env = None
    from ansibleclaw.config import COLLECTIONS_PATH
    if COLLECTIONS_PATH:
        env = {**os.environ, "ANSIBLE_COLLECTIONS_PATH": COLLECTIONS_PATH}
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, env=env,
    )
    if result.returncode != 0:
        raise AnsibleDocError(
            f"ansible-galaxy collection install failed: {result.stderr.strip()}"
        )


def uninstall_collection(collection_fqcn: str) -> None:
    """Remove an installed collection by deleting its directory."""
    collections = list_collections()
    target = None
    for c in collections:
        if c["fqcn"] == collection_fqcn:
            target = c
            break
    if target is None:
        raise AnsibleDocError(f"Collection '{collection_fqcn}' is not installed.")

    parts = collection_fqcn.split(".", 1)
    if len(parts) != 2:
        raise AnsibleDocError(f"Invalid collection FQCN: {collection_fqcn}")

    coll_dir = Path(target["path"]) / parts[0] / parts[1]
    if not coll_dir.exists():
        raise AnsibleDocError(f"Collection directory not found: {coll_dir}")

    shutil.rmtree(coll_dir)


def list_collections() -> list[dict[str, str]]:
    """List installed collections via ``ansible-galaxy collection list``.

    Returns a list of dicts with keys: namespace, name, version, path.
    """
    galaxy_bin = Path(sys.executable).parent / "ansible-galaxy"
    if not galaxy_bin.exists():
        found = shutil.which("ansible-galaxy")
        if not found:
            raise AnsibleDocError("ansible-galaxy not found")
        galaxy_bin = Path(found)

    cmd = [str(galaxy_bin), "collection", "list", "--format", "json"]
    env = None
    from ansibleclaw.config import COLLECTIONS_PATH
    if COLLECTIONS_PATH:
        env = {**os.environ, "ANSIBLE_COLLECTIONS_PATH": COLLECTIONS_PATH}
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, env=env,
        )
    except subprocess.TimeoutExpired:
        raise AnsibleDocError("ansible-galaxy collection list timed out")

    if result.returncode != 0:
        raise AnsibleDocError(
            f"ansible-galaxy collection list failed: {result.stderr.strip()}"
        )

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AnsibleDocError(f"Failed to parse collection list JSON: {exc}")

    collections: list[dict[str, str]] = []
    for path, entries in raw.items():
        for fqcn, info in entries.items():
            parts = fqcn.split(".", 1)
            collections.append({
                "namespace": parts[0] if len(parts) > 1 else "",
                "name": parts[1] if len(parts) > 1 else fqcn,
                "fqcn": fqcn,
                "version": info.get("version", ""),
                "path": path,
            })
    collections.sort(key=lambda c: c["fqcn"])
    return collections
