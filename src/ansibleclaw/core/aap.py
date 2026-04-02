"""AAP Controller REST API client.

Lightweight wrapper around the AAP/AWX v2 REST API for listing resources
and creating Job Templates.  Uses only stdlib (urllib + json).
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class AAPError(Exception):
    """Raised when an AAP API request fails."""


class AAPClient:
    """Interact with an AAP/AWX Controller via its REST API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        verify_ssl: bool = True,
        organization: str = "Default",
    ):
        self._base = base_url.rstrip("/")
        self._token = token
        self._verify = verify_ssl
        self._org = organization

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _ssl_ctx(self) -> ssl.SSLContext | None:
        if not self._verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                req, context=self._ssl_ctx(), timeout=30,
            ) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode() if exc.fp else ""
            raise AAPError(
                f"AAP API error (HTTP {exc.code}) {method} {url}: {detail}"
            )
        except urllib.error.URLError as exc:
            raise AAPError(f"AAP connection error: {exc.reason}")

    def _get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, data)

    # ------------------------------------------------------------------
    # Resource listing
    # ------------------------------------------------------------------

    def _list_resources(
        self,
        endpoint: str,
        extra_params: str = "",
        page_size: int = 200,
    ) -> list[dict[str, Any]]:
        sep = "&" if "?" in endpoint else "?"
        path = f"{endpoint}{sep}page_size={page_size}{extra_params}"
        data = self._get(path)
        return data.get("results", [])

    def list_organizations(self) -> list[dict[str, Any]]:
        return self._list_resources("/api/v2/organizations/")

    def list_projects(self) -> list[dict[str, Any]]:
        return self._list_resources("/api/v2/projects/")

    def list_execution_environments(self) -> list[dict[str, Any]]:
        return self._list_resources("/api/v2/execution_environments/")

    def list_inventories(self) -> list[dict[str, Any]]:
        return self._list_resources("/api/v2/inventories/")

    def list_credentials(self, credential_type: str = "Machine") -> list[dict[str, Any]]:
        encoded = urllib.parse.quote(credential_type)
        return self._list_resources(
            "/api/v2/credentials/",
            extra_params=f"&credential_type__name={encoded}",
        )

    # ------------------------------------------------------------------
    # Resolve helpers
    # ------------------------------------------------------------------

    def resolve_id(
        self,
        endpoint: str,
        name_or_id: str,
    ) -> int:
        """Resolve a resource name (or numeric ID string) to a numeric ID."""
        if name_or_id.isdigit():
            return int(name_or_id)
        encoded = urllib.parse.quote(name_or_id)
        data = self._get(f"{endpoint}?name={encoded}")
        results = data.get("results", [])
        if not results:
            raise AAPError(f"Resource '{name_or_id}' not found at {endpoint}")
        return results[0]["id"]

    def resolve_organization_id(self) -> int:
        return self.resolve_id("/api/v2/organizations/", self._org)

    # ------------------------------------------------------------------
    # Project management
    # ------------------------------------------------------------------

    def create_project(
        self,
        name: str,
        scm_url: str,
        scm_credential_id: int | None = None,
        organization_id: int | None = None,
    ) -> dict[str, Any]:
        org_id = organization_id or self.resolve_organization_id()
        payload: dict[str, Any] = {
            "name": name,
            "organization": org_id,
            "scm_type": "git",
            "scm_url": scm_url,
        }
        if scm_credential_id:
            payload["credential"] = scm_credential_id
        return self._post("/api/v2/projects/", payload)

    def sync_project(self, project_id: int) -> dict[str, Any]:
        return self._post(f"/api/v2/projects/{project_id}/update/", {})

    # ------------------------------------------------------------------
    # Job Template creation
    # ------------------------------------------------------------------

    def create_job_template(
        self,
        name: str,
        project_id: int,
        playbook: str,
        inventory_id: int,
        ee_id: int | None = None,
        extra_vars: str = "",
        ask_credential_on_launch: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "job_type": "run",
            "project": project_id,
            "playbook": playbook,
            "inventory": inventory_id,
            "ask_credential_on_launch": ask_credential_on_launch,
        }
        if ee_id:
            payload["execution_environment"] = ee_id
        if extra_vars:
            payload["extra_vars"] = extra_vars
        return self._post("/api/v2/job_templates/", payload)

    def add_credential_to_template(
        self,
        template_id: int,
        credential_id: int,
    ) -> None:
        self._post(
            f"/api/v2/job_templates/{template_id}/credentials/",
            {"id": credential_id},
        )
