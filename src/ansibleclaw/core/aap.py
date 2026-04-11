"""AAP Controller REST API client.

Lightweight wrapper around the AAP/AWX v2 REST API for listing resources
and creating Job Templates.  Uses only stdlib (urllib + json).

Supports both classic AWX / AAP 2.4 (``/api/v2/``) and AAP 2.5+ Gateway
(``/api/controller/v2/``).  The correct prefix is auto-detected on the
first API call and cached for the lifetime of the client.
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


# Prefixes to probe, in order.  The first one that responds to a lightweight
# GET is used for all subsequent requests.
_API_PREFIXES = [
    "/api/v2",
    "/api/controller/v2",
]


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
        self._api_prefix: str | None = None

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

    def _raw_request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    # ------------------------------------------------------------------
    # API prefix auto-detection
    # ------------------------------------------------------------------

    def _detect_prefix(self) -> str:
        """Probe known API prefixes and return the first that responds."""
        for prefix in _API_PREFIXES:
            try:
                url = f"{self._base}{prefix}/ping/"
                self._raw_request("GET", url)
                return prefix
            except AAPError:
                continue
        return _API_PREFIXES[0]

    @property
    def api_prefix(self) -> str:
        if self._api_prefix is None:
            self._api_prefix = self._detect_prefix()
        return self._api_prefix

    # ------------------------------------------------------------------
    # Request wrappers that use the detected prefix
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a request against ``{base}/{api_prefix}{path}``."""
        url = f"{self._base}{self.api_prefix}{path}"
        return self._raw_request(method, url, data)

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
        try:
            return self._list_resources("/organizations/")
        except AAPError:
            pass
        # AAP 2.5 may serve orgs from the gateway API instead of controller.
        try:
            url = f"{self._base}/api/gateway/v1/organizations/?page_size=200"
            data = self._raw_request("GET", url)
            return data.get("results", [])
        except AAPError:
            return [{"id": 1, "name": self._org}]

    def list_projects(self) -> list[dict[str, Any]]:
        return self._list_resources("/projects/")

    def get_project(self, project_id: int) -> dict[str, Any]:
        return self._get(f"/projects/{project_id}/")

    def list_execution_environments(self) -> list[dict[str, Any]]:
        return self._list_resources("/execution_environments/")

    def list_inventories(self) -> list[dict[str, Any]]:
        return self._list_resources("/inventories/")

    def list_credentials(self, credential_type: str = "Machine") -> list[dict[str, Any]]:
        encoded = urllib.parse.quote(credential_type)
        return self._list_resources(
            "/credentials/",
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
        return self.resolve_id("/organizations/", self._org)

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
        return self._post("/projects/", payload)

    def sync_project(self, project_id: int) -> dict[str, Any]:
        return self._post(f"/projects/{project_id}/update/", {})

    def list_project_playbooks(self, project_id: int) -> list[str]:
        """Return the list of playbook paths AAP knows about for a project."""
        data = self._get(f"/projects/{project_id}/playbooks/")
        if isinstance(data, list):
            return data
        return data.get("results", data.get("playbooks", []))

    def sync_project_and_wait(
        self,
        project_id: int,
        timeout: int = 120,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Trigger a project sync and block until it finishes or times out."""
        import time

        result = self.sync_project(project_id)
        job_url = result.get("url")
        if not job_url:
            return result

        full_url = f"{self._base}{job_url}" if job_url.startswith("/") else job_url
        terminal = {"successful", "failed", "error", "canceled"}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self._raw_request("GET", full_url)
            status = job.get("status", "unknown")
            if status in terminal:
                if status != "successful":
                    raise AAPError(
                        f"Project sync {status}: "
                        f"{job.get('result_traceback', '')[:200]}"
                    )
                return job
            time.sleep(poll_interval)
        raise AAPError(f"Project sync timed out after {timeout}s")

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
        return self._post("/job_templates/", payload)

    def add_credential_to_template(
        self,
        template_id: int,
        credential_id: int,
    ) -> None:
        self._post(
            f"/job_templates/{template_id}/credentials/",
            {"id": credential_id},
        )

    def list_job_templates(self) -> list[dict[str, Any]]:
        return self._list_resources("/job_templates/")

    # ------------------------------------------------------------------
    # AAP UI deep-link generation
    # ------------------------------------------------------------------

    # AAP 2.5+ gateway uses path-based UI routes; classic AWX/2.4 uses
    # hash-based routes.  We pick the pattern based on the detected API
    # prefix.
    _GATEWAY_UI_PATHS: dict[str, str] = {
        "project": "/execution/projects/{id}/details",
        "job_template": "/execution/templates/job_template/{id}/details",
        "inventory": "/infrastructure/inventories/{id}/details",
        "credential": "/access/credentials/{id}/details",
        "organization": "/access/organizations/{id}/details",
        "execution_environment": "/infrastructure/execution-environments/{id}/details",
        "job": "/execution/jobs/{id}/output",
    }

    _CLASSIC_UI_PATHS: dict[str, str] = {
        "project": "/#/projects/{id}",
        "job_template": "/#/templates/job_template/{id}/details",
        "inventory": "/#/inventories/{id}",
        "credential": "/#/credentials/{id}",
        "organization": "/#/organizations/{id}",
        "execution_environment": "/#/execution_environments/{id}",
        "job": "/#/jobs/{id}/output",
    }

    def ui_url(self, resource_type: str, resource_id: int | str) -> str:
        """Build a URL to a resource's page in the AAP web UI."""
        is_gateway = self.api_prefix == "/api/controller/v2"
        paths = self._GATEWAY_UI_PATHS if is_gateway else self._CLASSIC_UI_PATHS
        pattern = paths.get(resource_type, "")
        if not pattern:
            return self._base
        return self._base + pattern.format(id=resource_id)
