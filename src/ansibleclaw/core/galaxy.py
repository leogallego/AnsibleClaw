"""Galaxy REST API doc provider.

Fetches module documentation from Ansible Galaxy (or a private Automation Hub)
when the collection is not installed locally.  Uses only stdlib (urllib + json).
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

from ansibleclaw.config import GALAXY_URL


class GalaxyError(Exception):
    """Raised when a Galaxy API request fails."""


class GalaxyDocProvider:
    """Fetch and parse module docs from the Galaxy v3 API."""

    def __init__(self, base_url: str | None = None):
        self._base = (base_url or GALAXY_URL).rstrip("/")
        self._ctx = ssl.create_default_context()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_module_doc(
        self,
        module_name: str,
        version: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Fetch module documentation from Galaxy.

        Returns (module_doc, meta) where *module_doc* mimics the format
        returned by ``ansible-doc --json`` (top-level key = FQCN) and
        *meta* contains provenance fields (doc_source, doc_version, …).
        """
        namespace, name, short_module = _parse_fqcn(module_name)
        resolved_version = version or self._latest_version(namespace, name)
        is_latest = version is None

        blob = self._fetch_docs_blob(namespace, name, resolved_version)
        module_entry = self._find_module(blob, short_module)
        if module_entry is None:
            raise GalaxyError(
                f"Module '{short_module}' not found in "
                f"{namespace}.{name} {resolved_version} docs-blob."
            )

        doc = self._transform_to_ansible_doc_format(
            module_name, module_entry,
        )

        meta: dict[str, str] = {
            "doc_source": "galaxy",
            "doc_version": resolved_version,
        }
        if is_latest:
            meta["doc_warning"] = (
                f"Documentation sourced from Galaxy "
                f"({namespace}.{name} {resolved_version}). "
                f"Your installed version may differ."
            )
        return doc, meta

    def list_collection_modules(
        self,
        collection_fqcn: str,
        version: str | None = None,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """List modules in a collection from the Galaxy docs-blob.

        Returns ``(modules, meta)`` where *modules* is ``{fqcn: description}``
        and *meta* has ``source`` and ``version`` keys.
        """
        parts = collection_fqcn.split(".")
        if len(parts) != 2:
            raise GalaxyError(
                f"'{collection_fqcn}' is not a valid collection FQCN "
                f"(expected namespace.name)."
            )
        namespace, name = parts
        resolved_version = version or self._latest_version(namespace, name)

        blob = self._fetch_docs_blob(namespace, name, resolved_version)
        modules: dict[str, str] = {}
        for item in blob.get("contents", []):
            if item.get("content_type") == "module":
                short = item.get("content_name", "")
                fqcn = f"{collection_fqcn}.{short}"
                desc = item.get("doc_strings", {}).get("doc", {}).get(
                    "short_description", ""
                ) or ""
                modules[fqcn] = desc

        meta = {"source": "galaxy", "version": resolved_version}
        return modules, meta

    def latest_version(self, namespace: str, name: str) -> str:
        """Return the latest published version string."""
        return self._latest_version(namespace, name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_get(self, path: str) -> dict[str, Any]:
        url = f"{self._base}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise GalaxyError(f"Galaxy API error (HTTP {exc.code}): {url}")
        except urllib.error.URLError as exc:
            raise GalaxyError(f"Galaxy connection error: {exc.reason}")

    def _latest_version(self, namespace: str, name: str) -> str:
        path = (
            f"/api/v3/plugin/ansible/content/published/collections/index/"
            f"{namespace}/{name}/versions/"
            f"?limit=1&ordering=-version&format=json"
        )
        data = self._api_get(path)
        versions = data.get("data", [])
        if not versions:
            raise GalaxyError(
                f"No versions found for {namespace}.{name} on Galaxy."
            )
        return versions[0]["version"]

    def _fetch_docs_blob(
        self, namespace: str, name: str, version: str,
    ) -> dict[str, Any]:
        path = (
            f"/api/v3/plugin/ansible/content/published/collections/index/"
            f"{namespace}/{name}/versions/{version}/docs-blob/?format=json"
        )
        data = self._api_get(path)
        return data.get("docs_blob", data)

    @staticmethod
    def _find_module(
        blob: dict[str, Any], short_name: str,
    ) -> dict[str, Any] | None:
        for item in blob.get("contents", []):
            if (
                item.get("content_type") == "module"
                and item.get("content_name") == short_name
            ):
                return item
        return None

    @staticmethod
    def _transform_to_ansible_doc_format(
        fqcn: str, entry: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a Galaxy docs-blob content entry into the dict shape
        that ``ansible-doc <module> --json`` produces.

        Galaxy stores options as a *list* of dicts (each with a ``name``
        key); ansible-doc stores them as a *dict* keyed by option name.
        """
        ds = entry.get("doc_strings", {})
        raw_doc = ds.get("doc", {})

        raw_options = raw_doc.get("options", [])
        if isinstance(raw_options, list):
            options_dict: dict[str, Any] = {}
            for opt in raw_options:
                opt_copy = dict(opt)
                opt_name = opt_copy.pop("name", None)
                if opt_name:
                    options_dict[opt_name] = opt_copy
        else:
            options_dict = raw_options

        doc_section = {
            "short_description": raw_doc.get("short_description", ""),
            "description": raw_doc.get("description", []),
            "options": options_dict,
            "author": raw_doc.get("author", []),
            "notes": raw_doc.get("notes", []),
            "version_added": raw_doc.get("version_added", ""),
        }

        return {
            fqcn: {
                "doc": doc_section,
                "examples": ds.get("examples", ""),
                "return": ds.get("return", []),
                "metadata": ds.get("metadata", {}),
            }
        }


def _parse_fqcn(module_name: str) -> tuple[str, str, str]:
    """Split ``namespace.collection.module`` into its three parts."""
    parts = module_name.split(".")
    if len(parts) < 3:
        raise GalaxyError(
            f"'{module_name}' is not a fully-qualified collection name "
            f"(expected namespace.collection.module)."
        )
    return parts[0], parts[1], parts[-1]


def detect_pinned_version(module_name: str) -> str | None:
    """Scan common project files for a pinned collection version.

    Checks (in order):
        1. requirements.yml / collections/requirements.yml
        2. execution-environment.yml

    Returns the version string if found, else None.
    """
    import yaml
    from pathlib import Path

    namespace, name, _ = _parse_fqcn(module_name)
    collection_fqcn = f"{namespace}.{name}"

    candidates = [
        Path("requirements.yml"),
        Path("collections/requirements.yml"),
        Path("execution-environment.yml"),
    ]

    for path in candidates:
        if not path.exists():
            continue
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        version = _find_version_in_requirements(data, collection_fqcn)
        if version:
            return version

        ee_deps = data.get("dependencies", {})
        if isinstance(ee_deps, dict):
            galaxy_section = ee_deps.get("galaxy", {})
            if isinstance(galaxy_section, dict):
                version = _find_version_in_requirements(
                    galaxy_section, collection_fqcn,
                )
                if version:
                    return version

    return None


def _find_version_in_requirements(
    data: dict, collection_fqcn: str,
) -> str | None:
    collections = data.get("collections", [])
    if not isinstance(collections, list):
        return None
    for entry in collections:
        if isinstance(entry, dict) and entry.get("name") == collection_fqcn:
            return entry.get("version")
        if isinstance(entry, str) and entry == collection_fqcn:
            return None
    return None
