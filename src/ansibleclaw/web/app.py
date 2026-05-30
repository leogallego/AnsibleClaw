"""AnsibleClaw Web Dashboard.

FastAPI application with routes for skills management, module search,
skill generation with preview, and ZIP download.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ansibleclaw.config import (
    AAPSettings,
    AISettings,
    BUILTINS_DIR,
    INSTALL_PATHS,
    SKILLS_DIR,
    TEMPLATE_DIR,
    TEMPLATE_PATH,
    local_inventory_path,
)
from ansibleclaw.core.packager import package_skill_zip_bytes
from ansibleclaw.core.parser import (
    AnsibleDocError,
    extract_module_metadata,
    get_module_doc,
    install_collection,
    list_collections,
    list_modules,
    resolve_module_doc,
    search_modules,
    uninstall_collection,
)

WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="AnsibleClaw", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


def _read_skill_frontmatter(skill_dir: Path) -> dict:
    """Read YAML frontmatter from a SKILL.md file."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return {"name": skill_dir.name, "description": ""}
    content = skill_file.read_text()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1])
                return fm if isinstance(fm, dict) else {}
            except yaml.YAMLError:
                pass
    return {"name": skill_dir.name, "description": ""}


def _scan_skill_dirs(base: Path, skill_type: str) -> dict[str, dict]:
    """Scan a directory for skill subdirectories and return {name: info}."""
    results: dict[str, dict] = {}
    if not base.exists():
        return results
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            fm = _read_skill_frontmatter(d)
            results[d.name] = {
                "dir_name": d.name,
                "name": fm.get("name", d.name),
                "description": fm.get("description", ""),
                "type": skill_type,
                "path": str(d),
            }
    return results


def _list_skills() -> list[dict]:
    """List all skills from builtins and user SKILLS_DIR (user overrides builtins)."""
    merged = _scan_skill_dirs(BUILTINS_DIR, "built-in")
    merged.update(_scan_skill_dirs(SKILLS_DIR, "generated"))
    return list(merged.values())


def _resolve_skill_dir(name: str) -> Path | None:
    """Find a skill directory by name, checking SKILLS_DIR first then BUILTINS_DIR."""
    user_dir = SKILLS_DIR / name
    if user_dir.exists() and (user_dir / "SKILL.md").exists():
        return user_dir
    builtin_dir = BUILTINS_DIR / name
    if builtin_dir.exists() and (builtin_dir / "SKILL.md").exists():
        return builtin_dir
    return None


def _is_builtin(name: str) -> bool:
    """Check whether a skill lives in the builtins directory."""
    return (BUILTINS_DIR / name / "SKILL.md").exists()


def _render_skill_md(metadata: dict) -> str:
    """Render skill template -- reuses the same logic as CLI."""
    from jinja2 import Environment, FileSystemLoader
    from ansibleclaw.cli import (
        _build_example_args,
        _collection_fqcn,
        _module_to_skill_name,
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_PATH.parent)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(TEMPLATE_PATH.name)
    module_name = metadata["module_name"]
    skill_name = _module_to_skill_name(module_name).replace("ansible_", "")
    example_args = _build_example_args(metadata["params"], metadata.get("examples", ""))

    from ansibleclaw.config import AAPSettings

    ctx = dict(
        module_name=module_name,
        skill_name=skill_name,
        short_description=metadata["short_description"],
        params=metadata["params"],
        examples=metadata["examples"].strip() if metadata["examples"] else "",
        example_args=example_args,
        collection_fqcn=_collection_fqcn(module_name),
    )
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
    ctx["aap_scm_url"] = AAPSettings.get("default_scm_url").strip()

    return template.render(**ctx)


# --- Routes ---

@app.get("/", response_class=RedirectResponse)
async def index():
    return RedirectResponse(url="/skills")


@app.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request):
    skills = _list_skills()
    return TEMPLATES.TemplateResponse(request, "skills.html", {
        "skills": skills,
        "page": "skills",
    })


@app.get("/skills/{name}", response_class=HTMLResponse)
async def skill_detail(request: Request, name: str, deploy: str = ""):
    skill_dir = _resolve_skill_dir(name)
    if skill_dir is None:
        return HTMLResponse("Skill not found", status_code=404)
    content = (skill_dir / "SKILL.md").read_text()

    collection_fqcn = ""
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        try:
            raw = skill_md.read_text()
            if raw.startswith("---"):
                fm_end = raw.index("---", 3)
                fm = yaml.safe_load(raw[3:fm_end])
                collection_fqcn = fm.get("collection", "") if fm else ""
        except Exception:
            pass

    return TEMPLATES.TemplateResponse(request, "skill_detail.html", {
        "name": name,
        "content": content,
        "page": "skills",
        "show_deploy": deploy == "aap",
        "deploy_target": "skill",
        "deploy_name": name,
        "deploy_action": "/api/aap/deploy-skill",
        "collection_fqcn": collection_fqcn,
        "jt_name_prefix": AAPSettings.get("job_template_prefix"),
    })


@app.delete("/skills/{name}", response_class=HTMLResponse)
async def delete_skill(name: str):
    if _is_builtin(name):
        return HTMLResponse("Cannot delete built-in skills", status_code=400)
    skill_dir = SKILLS_DIR / name
    if not skill_dir.exists():
        return HTMLResponse("Skill not found", status_code=404)
    shutil.rmtree(skill_dir)
    return HTMLResponse("")


@app.post("/skills/{name}/install", response_class=HTMLResponse)
async def install_skill(name: str, platform: str = Form(...)):
    skill_dir = _resolve_skill_dir(name)
    if skill_dir is None:
        return HTMLResponse("Skill not found", status_code=404)
    platform = platform.lower()
    if platform not in INSTALL_PATHS:
        return HTMLResponse(f"Unknown platform: {platform}", status_code=400)
    target = INSTALL_PATHS[platform] / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(skill_dir, target)
    return HTMLResponse(
        f'<span class="ac-success">\u2713 Installed to {target}</span>'
    )


@app.post("/skills/{name}/uninstall", response_class=HTMLResponse)
async def uninstall_skill(name: str, platform: str = Form(...)):
    platform = platform.lower()
    if platform not in INSTALL_PATHS:
        return HTMLResponse(f"Unknown platform: {platform}", status_code=400)
    target = INSTALL_PATHS[platform] / name
    if not target.exists():
        return HTMLResponse(
            f'<span class="ac-success">No copy at {target} (already absent).</span>'
        )
    if not target.is_dir():
        return HTMLResponse(f"Not a directory: {target}", status_code=400)
    shutil.rmtree(target)
    return HTMLResponse(
        f'<span class="ac-success">\u2713 Removed from {target}</span>'
    )


@app.get("/skills/{name}/download")
async def download_skill(name: str):
    skill_dir = _resolve_skill_dir(name)
    if skill_dir is None:
        return HTMLResponse("Skill not found", status_code=404)
    zip_bytes = package_skill_zip_bytes(skill_dir)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "search.html", {
        "page": "search",
    })


@app.get("/search/results", response_class=HTMLResponse)
async def search_results(request: Request, q: str = "", ns: str = ""):
    if not q and not ns:
        return HTMLResponse("")
    try:
        if q:
            results = search_modules(q, namespace=ns or None)
        else:
            results = list_modules(namespace=ns or None)
    except AnsibleDocError as exc:
        return HTMLResponse(f'<p class="ac-error">{exc}</p>')
    return TEMPLATES.TemplateResponse(request, "_search_results.html", {
        "results": results,
        "query": q,
    })


@app.get("/search/detail/{module:path}", response_class=HTMLResponse)
async def module_detail(request: Request, module: str):
    try:
        doc = get_module_doc(module)
        metadata = extract_module_metadata(doc)
    except AnsibleDocError as exc:
        return HTMLResponse(f'<p class="ac-error">{exc}</p>')
    return TEMPLATES.TemplateResponse(request, "_module_detail.html", {
        "metadata": metadata,
    })


@app.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "generate.html", {
        "page": "generate",
        "platforms": list(INSTALL_PATHS.keys()),
    })


@app.get("/generate/preview", response_class=HTMLResponse)
async def generate_preview(request: Request, module: str = ""):
    if not module:
        return HTMLResponse("")
    try:
        doc, doc_meta = resolve_module_doc(module)
        metadata = extract_module_metadata(doc)
        metadata.update(doc_meta)
        preview = _render_skill_md(metadata)
    except AnsibleDocError as exc:
        return HTMLResponse(f'<p class="ac-error">{exc}</p>')
    source_note = ""
    if doc_meta.get("doc_source") == "galaxy":
        ver = doc_meta.get("doc_version", "")
        source_note = (
            f'<p class="ac-warning">Documentation sourced from Galaxy '
            f"(v{ver}). Install the collection locally for exact docs.</p>"
        )
    return HTMLResponse(f"{source_note}<pre><code>{preview}</code></pre>")


@app.post("/generate", response_class=HTMLResponse)
async def generate_skill(
    module: str = Form(...),
    target: str = Form("project"),
    custom_path: str = Form(""),
):
    try:
        doc, doc_meta = resolve_module_doc(module)
        metadata = extract_module_metadata(doc)
        metadata.update(doc_meta)
    except AnsibleDocError as exc:
        return HTMLResponse(f'<p class="ac-error">{exc}</p>')

    from ansibleclaw.cli import _module_to_skill_name, _write_skill_package
    skill_name = _module_to_skill_name(metadata["module_name"])

    if target == "project":
        output_dir = SKILLS_DIR / skill_name
    elif target in INSTALL_PATHS:
        output_dir = INSTALL_PATHS[target] / skill_name
    elif target == "custom" and custom_path:
        output_dir = Path(custom_path) / skill_name
    else:
        return HTMLResponse('<p class="ac-error">Invalid target</p>')

    _write_skill_package(output_dir, metadata)

    download_link = ""
    if target == "project":
        download_link = (
            f' &mdash; <a href="/skills/{skill_name}/download">Download ZIP</a>'
        )

    source_note = ""
    if doc_meta.get("doc_source") == "galaxy":
        source_note = " (docs from Galaxy)"

    return HTMLResponse(
        f'<p class="ac-success">Skill generated{source_note}: '
        f"<code>{output_dir}</code>"
        f" (SKILL.md, scripts/, assets/){download_link}</p>"
    )


# --- Compose ---


@app.get("/compose", response_class=HTMLResponse)
async def compose_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "compose.html", {
        "page": "compose",
        "platforms": list(INSTALL_PATHS.keys()),
    })


@app.get("/api/compose/modules")
async def compose_list_modules():
    """Return all available modules for the autocomplete picker.

    Runs ``ansible-doc --list --json`` in a thread to avoid blocking the
    event loop.  The result is a flat list of ``{fqcn, description}`` objects.
    """
    from fastapi.responses import JSONResponse

    loop = asyncio.get_running_loop()
    try:
        modules = await loop.run_in_executor(None, lambda: list_modules())
    except AnsibleDocError as exc:
        return JSONResponse({"modules": [], "error": str(exc)})

    items = [
        {"fqcn": fqcn, "description": desc or ""}
        for fqcn, desc in sorted(modules.items())
    ]
    return JSONResponse({"modules": items})


@app.get("/api/compose/resolve-module")
async def compose_resolve_module(name: str = ""):
    """Validate a fully-qualified module name via ``ansible-doc``.

    Requires a full FQCN (``namespace.collection.module``).  Returns
    JSON ``{"valid": true, "fqcn": "..."}`` on success or
    ``{"valid": false, "error": "..."}`` on failure.
    """
    from fastapi.responses import JSONResponse

    name = name.strip()
    if not name:
        return JSONResponse({"valid": False, "error": "Module name is required."})

    parts = name.split(".")
    if len(parts) < 3:
        return JSONResponse({
            "valid": False,
            "error": f"'{name}' is not a fully-qualified name. "
                     f"Use the full FQCN, e.g. ansible.builtin.package.",
        })

    def _validate(module: str) -> bool:
        doc = get_module_doc(module)
        if not doc:
            return False
        fqcn = next(iter(doc), None)
        return (
            fqcn is not None
            and fqcn == module
            and "doc" in doc.get(fqcn, {})
        )

    loop = asyncio.get_running_loop()
    try:
        valid = await loop.run_in_executor(None, lambda: _validate(name))
    except AnsibleDocError:
        valid = False

    if valid:
        return JSONResponse({"valid": True, "fqcn": name})
    return JSONResponse({"valid": False, "error": f"Module '{name}' not found."})


@app.get("/compose/preview", response_class=HTMLResponse)
async def compose_preview(
    request: Request,
    name: str = "",
    description: str = "",
    modules: list[str] = Query(default=[]),
):
    if not name or not modules:
        return HTMLResponse("")

    from ansibleclaw.cli import _render_composite_skill

    modules_metadata: list[dict] = []
    for module_name in modules:
        try:
            doc, doc_meta = resolve_module_doc(module_name)
            meta = extract_module_metadata(doc)
            meta.update(doc_meta)
            modules_metadata.append(meta)
        except AnsibleDocError as exc:
            return HTMLResponse(
                f'<p class="ac-error">Failed to fetch docs for '
                f"<code>{module_name}</code>: {exc}</p>"
            )

    if not description:
        description = f"Composite skill combining {len(modules)} Ansible modules"

    try:
        preview = _render_composite_skill(name, description, modules_metadata)
    except Exception as exc:
        return HTMLResponse(f'<p class="ac-error">Render error: {exc}</p>')

    return HTMLResponse(f"<pre><code>{preview}</code></pre>")


@app.post("/compose", response_class=HTMLResponse)
async def compose_skill(request: Request):
    form = await request.form()
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    modules = form.getlist("modules")
    target = form.get("target", "project")
    custom_path = form.get("custom_path", "")

    if not name:
        return HTMLResponse('<p class="ac-error">Skill name is required.</p>')
    if not modules:
        return HTMLResponse('<p class="ac-error">At least one module is required.</p>')

    from ansibleclaw.cli import _write_composite_skill_package

    modules_metadata: list[dict] = []
    for module_name in modules:
        try:
            doc, doc_meta = resolve_module_doc(module_name)
            meta = extract_module_metadata(doc)
            meta.update(doc_meta)
            modules_metadata.append(meta)
        except AnsibleDocError as exc:
            return HTMLResponse(
                f'<p class="ac-error">Failed to fetch docs for '
                f"<code>{module_name}</code>: {exc}</p>"
            )

    if not description:
        description = f"Composite skill combining {len(modules)} Ansible modules"

    from ansibleclaw.cli import _sanitize_skill_dir_name
    skill_dir_name = _sanitize_skill_dir_name(name)

    if target == "project":
        output_dir = SKILLS_DIR / skill_dir_name
    elif target in INSTALL_PATHS:
        output_dir = INSTALL_PATHS[target] / skill_dir_name
    elif target == "custom" and custom_path:
        output_dir = Path(custom_path) / skill_dir_name
    else:
        return HTMLResponse('<p class="ac-error">Invalid target</p>')

    try:
        _write_composite_skill_package(output_dir, name, description, modules_metadata)
    except Exception as exc:
        return HTMLResponse(f'<p class="ac-error">Generation failed: {exc}</p>')

    download_link = ""
    if target == "project":
        download_link = (
            f' &mdash; <a href="/skills/{skill_dir_name}/download">Download ZIP</a>'
        )

    return HTMLResponse(
        f'<p class="ac-success">Composite skill generated: '
        f"<code>{output_dir}</code>"
        f" ({len(modules)} modules, SKILL.md, scripts/, assets/){download_link}</p>"
    )


_DEFAULT_LOCAL_INVENTORY = (
    "# Local / CLI inventory (development). Production runs use AAP Controller inventories.\n"
    "all:\n"
    "  hosts: {}\n"
)


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    path = local_inventory_path()
    if path.exists():
        content = path.read_text()
    else:
        content = _DEFAULT_LOCAL_INVENTORY
    return TEMPLATES.TemplateResponse(request, "inventory.html", {
        "page": "inventory",
        "inventory_path": str(path),
        "inventory_content": content,
        "save_ok": None,
        "save_error": None,
    })


@app.post("/inventory", response_class=HTMLResponse)
async def inventory_save(request: Request, content: str = Form("")):
    path = local_inventory_path()
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return TEMPLATES.TemplateResponse(request, "inventory.html", {
            "page": "inventory",
            "inventory_path": str(path),
            "inventory_content": content,
            "save_ok": None,
            "save_error": f"Invalid YAML: {exc}",
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return TEMPLATES.TemplateResponse(request, "inventory.html", {
        "page": "inventory",
        "inventory_path": str(path),
        "inventory_content": content,
        "save_ok": "Inventory saved.",
        "save_error": None,
    })


# --- AI configuration status ---


@app.get("/api/ai/status")
async def api_ai_status():
    """Return whether AI refinement is configured and current settings."""
    configured = AISettings.is_configured()
    return JSONResponse({
        "available": configured,
        "endpoint": AISettings.get("endpoint"),
        "model": AISettings.get("model", ""),
        "has_api_key": bool(AISettings.get("api_key")),
    })


@app.post("/api/ai/save")
async def api_ai_save(request: Request):
    """Save AI endpoint configuration to .ansibleclaw.yml."""
    body = await request.json()
    endpoint = body.get("endpoint", "").strip()
    model = body.get("model", "").strip()
    api_key = body.get("api_key", "").strip()

    settings_path = Path.cwd() / ".ansibleclaw.yml"
    existing: dict = {}
    if settings_path.exists():
        try:
            existing = yaml.safe_load(settings_path.read_text()) or {}
        except Exception:
            pass

    ai_section: dict = {}
    if endpoint:
        ai_section["endpoint"] = endpoint
    if model:
        ai_section["model"] = model
    if api_key:
        ai_section["api_key"] = api_key

    if ai_section:
        existing["ai"] = ai_section
    elif "ai" in existing:
        del existing["ai"]

    settings_path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))
    AISettings.invalidate_cache()

    return JSONResponse({"saved": True, "available": bool(endpoint)})


@app.post("/api/ai/models")
async def api_ai_models(request: Request):
    """Retrieve available models from an OpenAI-compatible endpoint."""
    import json as _json
    import urllib.error
    import urllib.request

    body = await request.json()
    endpoint = (body.get("endpoint") or "").strip().rstrip("/")
    api_key = (body.get("api_key") or "").strip()

    if not endpoint:
        return JSONResponse({"error": "No endpoint provided"}, status_code=400)

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{endpoint}/models"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return JSONResponse(
                {"error": "Authentication required", "needs_api_key": True},
                status_code=401,
            )
        return JSONResponse(
            {"error": f"HTTP {exc.code}: {exc.reason}"}, status_code=502
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)

    models: list[str] = []
    if isinstance(data, dict) and "data" in data:
        for m in data["data"]:
            model_id = m.get("id") if isinstance(m, dict) else str(m)
            if model_id:
                models.append(model_id)
    models.sort()
    return JSONResponse({"models": models})


# --- Dev/Test: playbook discovery and local execution ---

_devtest_process: Optional[subprocess.Popen] = None


@app.get("/api/devtest/playbooks")
async def api_devtest_playbooks():
    """Scan skills for playbooks and return a JSON list."""
    results: list[dict] = []
    for skill in _list_skills():
        skill_dir = Path(skill["path"])
        assets_dir = skill_dir / "assets"
        if not assets_dir.exists():
            continue
        for yml in sorted(assets_dir.rglob("*.yml")):
            if yml.name in ("requirements.yml",) or yml.name.startswith("."):
                continue
            rel = str(yml.relative_to(skill_dir))
            results.append({
                "skill": skill["dir_name"],
                "skill_name": skill["name"],
                "playbook": rel,
                "playbook_abs": str(yml),
                "type": skill["type"],
            })
    return results


def _devtest_validate_path(path_str: str) -> tuple[Path | None, Response | None]:
    """Validate a playbook path is within allowed directories. Returns (resolved_path, error_response)."""
    if not path_str:
        return None, None
    pb = Path(path_str).resolve()
    skills_resolved = SKILLS_DIR.resolve()
    builtins_resolved = BUILTINS_DIR.resolve()
    if not (str(pb).startswith(str(skills_resolved)) or str(pb).startswith(str(builtins_resolved))):
        return None, Response("Path outside allowed directories", media_type="text/plain", status_code=403)
    return pb, None


@app.get("/api/devtest/playbook-content")
async def api_devtest_playbook_content(path: str = Query("")):
    """Return the text content of a playbook file for preview."""
    if not path:
        return Response("No path specified", media_type="text/plain", status_code=400)
    pb, err = _devtest_validate_path(path)
    if err:
        return err
    if not pb.is_file():
        return Response("File not found", media_type="text/plain", status_code=404)
    try:
        content = pb.read_text(errors="replace")
        return Response(content, media_type="text/plain")
    except Exception:
        return Response("Cannot read file", media_type="text/plain", status_code=500)


@app.post("/api/devtest/playbook-save")
async def api_devtest_playbook_save(request: Request):
    """Write edited playbook content back to disk."""
    body = await request.json()
    path_str = body.get("path", "").strip()
    content = body.get("content", "")
    if not path_str:
        return JSONResponse({"error": "No path specified"}, status_code=400)
    pb, err = _devtest_validate_path(path_str)
    if err:
        return JSONResponse({"error": "Path outside allowed directories"}, status_code=403)
    if not pb.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        pb.write_text(content)
        return JSONResponse({"saved": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/devtest/refine")
async def api_devtest_refine(request: Request):
    """Use an OpenAI-compatible endpoint to refine a playbook based on user intent."""
    from starlette.responses import StreamingResponse
    import urllib.request
    import urllib.error
    import json as _json

    if not AISettings.is_configured():
        return JSONResponse({"error": "AI is not configured. Add an 'ai:' section to .ansibleclaw.yml with 'endpoint', 'model', and optionally 'api_key'."}, status_code=400)

    body = await request.json()
    playbook_content = body.get("playbook_content", "").strip()
    intent = body.get("intent", "").strip()
    inventory_content = body.get("inventory_content", "").strip()

    if not intent:
        return JSONResponse({"error": "No intent provided"}, status_code=400)
    if not playbook_content:
        return JSONResponse({"error": "No playbook content provided"}, status_code=400)

    system_prompt = (
        "You are an expert Ansible automation engineer. "
        "The user will give you a template playbook (which may contain CHANGEME placeholders or example-only tasks) "
        "and describe what they want it to do. "
        "Rewrite the playbook so it is production-ready for the described intent. "
        "Return ONLY the complete, valid YAML playbook — no explanations, no markdown fences, no commentary. "
        "Preserve the overall structure (hosts, become, collections) but replace all placeholders and examples "
        "with real, working tasks that accomplish the user's goal."
    )
    if inventory_content:
        system_prompt += (
            "\n\nThe user's current Ansible inventory is:\n```\n" + inventory_content + "\n```\n"
            "Use host groups and variables from this inventory where appropriate."
        )

    user_msg = f"## Intent\n{intent}\n\n## Current Playbook\n```yaml\n{playbook_content}\n```"

    endpoint = AISettings.get("endpoint").rstrip("/")
    model = AISettings.get("model", "default")
    api_key = AISettings.get("api_key", "")

    payload = _json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": True,
        "temperature": 0.3,
    }).encode()

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def stream():
        try:
            req = urllib.request.Request(
                f"{endpoint}/chat/completions",
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
                    except (_json.JSONDecodeError, IndexError, KeyError):
                        continue
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
            yield f"\n--- AI Error ({exc.code}): {err_body} ---\n"
        except Exception as exc:
            yield f"\n--- AI Error: {exc} ---\n"

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


@app.post("/api/devtest/run")
async def api_devtest_run(request: Request):
    """Run ansible-playbook against local inventory with streaming output.

    If ``playbook_content`` is provided in the body, write it to a temp file
    and run that instead of the on-disk file (allows running unsaved edits).
    """
    from starlette.responses import StreamingResponse
    import shlex

    global _devtest_process

    body = await request.json()
    playbook_path = body.get("playbook_path", "").strip()
    playbook_content = body.get("playbook_content")
    mode = body.get("mode", "check")
    extra_args = body.get("extra_args", "").strip()

    if not playbook_path:
        return JSONResponse({"error": "No playbook specified"}, status_code=400)

    pb, err = _devtest_validate_path(playbook_path)
    if err:
        return JSONResponse({"error": "Playbook path is outside allowed directories"}, status_code=403)
    if not pb.is_file():
        return JSONResponse({"error": f"Playbook not found: {playbook_path}"}, status_code=404)

    ansible_cmd = shutil.which("ansible-playbook")
    if not ansible_cmd:
        return JSONResponse({"error": "ansible-playbook not found on PATH"}, status_code=500)

    tmp_file = None
    run_path = str(pb)
    if playbook_content is not None:
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", prefix="ansibleclaw_run_",
            dir=pb.parent, delete=False,
        )
        tmp_file.write(playbook_content)
        tmp_file.close()
        run_path = tmp_file.name

    inv_path = local_inventory_path()
    cmd = [ansible_cmd, run_path, "-i", str(inv_path)]
    if mode == "check":
        cmd += ["--check", "--diff"]
    if extra_args:
        cmd += shlex.split(extra_args)

    def stream():
        global _devtest_process
        try:
            _devtest_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in iter(_devtest_process.stdout.readline, ""):
                yield line
            _devtest_process.stdout.close()
            rc = _devtest_process.wait()
            yield f"\n--- Exit code: {rc} ---\n"
        except Exception as exc:
            yield f"\n--- Error: {exc} ---\n"
        finally:
            _devtest_process = None
            if tmp_file is not None:
                try:
                    os.unlink(tmp_file.name)
                except OSError:
                    pass

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


@app.post("/api/devtest/stop")
async def api_devtest_stop():
    """Stop a running ansible-playbook process."""
    global _devtest_process
    if _devtest_process and _devtest_process.poll() is None:
        _devtest_process.terminate()
        try:
            _devtest_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _devtest_process.kill()
        _devtest_process = None
        return {"stopped": True}
    return {"stopped": False, "message": "No process running"}


# --- Collections ---

@app.get("/collections", response_class=HTMLResponse)
async def collections_page(request: Request):
    try:
        collections = list_collections()
        module_counts: dict[str, int] = {}
        for coll in collections:
            try:
                modules = list_modules(namespace=coll["fqcn"])
                module_counts[coll["fqcn"]] = len(modules)
            except AnsibleDocError:
                module_counts[coll["fqcn"]] = 0
    except AnsibleDocError as exc:
        collections = []
        module_counts = {}
    return TEMPLATES.TemplateResponse(request, "collections.html", {
        "page": "collections",
        "collections": collections,
        "module_counts": module_counts,
    })


@app.get("/collections/{namespace}/{name}", response_class=HTMLResponse)
async def collection_detail(request: Request, namespace: str, name: str):
    fqcn = f"{namespace}.{name}"
    try:
        modules = list_modules(namespace=fqcn)
    except AnsibleDocError as exc:
        return HTMLResponse(f'<p class="ac-error">{exc}</p>', status_code=404)

    coll_info: dict[str, str] = {"fqcn": fqcn, "namespace": namespace, "name": name}
    try:
        all_colls = list_collections()
        for c in all_colls:
            if c["fqcn"] == fqcn:
                coll_info.update(c)
                break
    except AnsibleDocError:
        pass

    return TEMPLATES.TemplateResponse(request, "collection_detail.html", {
        "page": "collections",
        "collection": coll_info,
        "modules": modules,
        "jt_name_prefix": AAPSettings.get("job_template_prefix"),
    })


@app.get("/api/collection-contents", response_class=HTMLResponse)
async def api_collection_contents(
    request: Request,
    collection: str = Query(""),
):
    if not collection:
        return HTMLResponse("")

    source = "local"
    version = ""
    modules: dict[str, str] = {}

    try:
        modules = list_modules(namespace=collection)
        source = "local"
    except AnsibleDocError:
        try:
            from ansibleclaw.core.galaxy import GalaxyDocProvider, GalaxyError
            provider = GalaxyDocProvider()
            modules, meta = provider.list_collection_modules(collection)
            source = "galaxy"
            version = meta.get("version", "")
        except Exception as exc:
            return HTMLResponse(
                f'<span class="ac-error">Could not fetch contents for '
                f"{collection}: {exc}</span>"
            )

    return TEMPLATES.TemplateResponse(request, "_collection_contents.html", {
        "collection": collection,
        "modules": modules,
        "source": source,
        "version": version,
    })


@app.post("/api/generate-batch", response_class=HTMLResponse)
async def api_generate_batch(request: Request):
    form = await request.form()
    modules = form.getlist("modules")
    if not modules:
        return HTMLResponse(
            '<span class="ac-warning">No modules selected.</span>'
        )

    from ansibleclaw.cli import _module_to_skill_name, _write_skill_package

    successes: list[str] = []
    failures: list[str] = []
    for module_name in modules:
        try:
            doc, doc_meta = resolve_module_doc(module_name)
            metadata = extract_module_metadata(doc)
            metadata.update(doc_meta)
            skill_name = _module_to_skill_name(metadata["module_name"])
            output_dir = SKILLS_DIR / skill_name
            _write_skill_package(output_dir, metadata)
            successes.append(f"{module_name} &rarr; {skill_name}")
        except Exception as exc:
            failures.append(f"{module_name}: {exc}")

    parts: list[str] = []
    if successes:
        items = "".join(f"<li>{s}</li>" for s in successes)
        parts.append(
            f'<p class="ac-success">{len(successes)} skill(s) generated:</p>'
            f"<ul>{items}</ul>"
        )
    if failures:
        items = "".join(f"<li>{f}</li>" for f in failures)
        parts.append(
            f'<p class="ac-error">{len(failures)} failed:</p>'
            f"<ul>{items}</ul>"
        )
    return HTMLResponse("".join(parts))


@app.post("/api/generate-collection-overview", response_class=HTMLResponse)
async def api_generate_collection_overview(
    collection: str = Form(...),
):
    from ansibleclaw.cli import (
        _write_collection_skill_package,
    )

    parts = collection.split(".")
    if len(parts) != 2:
        return HTMLResponse(
            '<span class="ac-error">Invalid collection FQCN.</span>',
        )

    try:
        modules = list_modules(namespace=collection)
    except AnsibleDocError as exc:
        return HTMLResponse(
            f'<span class="ac-error">{exc}</span>',
        )

    modules_metadata: list[dict] = []
    for module_name in sorted(modules.keys()):
        try:
            doc, doc_meta = resolve_module_doc(module_name)
            meta = extract_module_metadata(doc)
            meta.update(doc_meta)
            modules_metadata.append(meta)
        except Exception:
            modules_metadata.append({
                "module_name": module_name,
                "short_description": modules.get(module_name, ""),
                "params": [],
                "examples": "",
            })

    skill_dir_name = f"ansible_{parts[1]}"
    output_dir = SKILLS_DIR / skill_dir_name
    try:
        _write_collection_skill_package(output_dir, collection, modules_metadata)
    except Exception as exc:
        return HTMLResponse(
            f'<span class="ac-error">Failed: {exc}</span>',
        )

    return HTMLResponse(
        f'<span class="ac-success">Collection overview skill generated: '
        f"<code>{output_dir}</code> &mdash; "
        f'<a href="/skills/{skill_dir_name}">View Skill</a></span>'
    )


@app.post("/api/install-collection", response_class=HTMLResponse)
async def api_install_collection(
    collection: str = Form(...),
    version: str = Form(""),
):
    try:
        install_collection(collection, version=version or None)
    except AnsibleDocError as exc:
        return HTMLResponse(
            f'<span class="ac-error">Install failed: {exc}</span>',
        )
    ver_str = f" {version}" if version else ""
    return HTMLResponse(
        content=(
            f'<span class="ac-success">'
            f"\u2713 Installed {collection}{ver_str}</span>"
        ),
        headers={"HX-Trigger-After-Settle": "collectionsUpdated"},
    )


@app.post("/api/uninstall-collection", response_class=HTMLResponse)
async def api_uninstall_collection(
    collection: str = Form(...),
):
    try:
        uninstall_collection(collection)
    except AnsibleDocError as exc:
        return HTMLResponse(
            f'<span class="ac-error">Uninstall failed: {exc}</span>',
        )
    return HTMLResponse(
        content=(
            f'<span class="ac-success">'
            f"\u2713 Uninstalled {collection}</span>"
        ),
        headers={"HX-Trigger-After-Settle": "collectionsUpdated"},
    )


# --- AAP ---


def _aap_html_step(msg: str) -> str:
    return (
        f'<div style="padding:0.2rem 0;color:var(--pf-t--global--text--color--subtle);">'
        f"\u23f3 {msg}</div>\n"
    )


def _aap_html_ok(msg: str) -> str:
    return f'<div class="ac-success" style="padding:0.2rem 0;">\u2713 {msg}</div>\n'


def _aap_html_err(msg: str) -> str:
    return f'<div class="ac-error" style="padding:0.2rem 0;">\u2717 {msg}</div>\n'


def _aap_is_configured() -> bool:
    return bool(AAPSettings.get("url") and AAPSettings.get("token"))


def _aap_ping_request(base_url: str, api_prefix: str) -> tuple[bool, str | None]:
    """GET ``{base}{api_prefix}/ping/``. Returns ``(ok, error_detail)``."""
    import ssl
    import urllib.error
    import urllib.request

    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {AAPSettings.get('token')}"}
    ctx = None
    if not AAPSettings.get_bool("verify_ssl"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    url = f"{base}{api_prefix}/ping/"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, context=ctx, timeout=3):
            return True, None
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        reason = exc.reason
        return False, str(reason) if reason else str(exc)
    except OSError as exc:
        return False, str(exc)


def _aap_ping() -> bool:
    """Try to reach the AAP Controller ping endpoint.

    Probes both ``/api/v2/ping/`` (classic) and
    ``/api/controller/v2/ping/`` (AAP 2.5 gateway).
    """
    if not _aap_is_configured():
        return False
    base = AAPSettings.get("url")
    for prefix in ("/api/v2", "/api/controller/v2"):
        ok, _ = _aap_ping_request(base, prefix)
        if ok:
            return True
    return False


_AAP_PING_TTL_OK = 60.0
_AAP_PING_TTL_FAIL = 120.0
_aap_ping_singleton: tuple[str, float, bool] | None = None


def _aap_ping_cache_key() -> str:
    return f"{AAPSettings.get('url')}|{AAPSettings.get('token')}"


def _aap_seed_ping_cache(ok: bool) -> None:
    """Store ping result for nav indicator and TTL cache."""
    global _aap_ping_singleton
    if not _aap_is_configured():
        _aap_ping_singleton = None
        return
    key = _aap_ping_cache_key()
    ttl = _AAP_PING_TTL_OK if ok else _AAP_PING_TTL_FAIL
    _aap_ping_singleton = (key, time.monotonic() + ttl, ok)


def _invalidate_aap_ping_cache() -> None:
    global _aap_ping_singleton
    _aap_ping_singleton = None


def _aap_ping_cached(*, force: bool = False) -> bool:
    """Return last-known AAP reachability; refresh with real ping when cache miss or force."""
    if not _aap_is_configured():
        return False
    key = _aap_ping_cache_key()
    now = time.monotonic()
    global _aap_ping_singleton
    if (
        not force
        and _aap_ping_singleton is not None
        and _aap_ping_singleton[0] == key
        and now < _aap_ping_singleton[1]
    ):
        return _aap_ping_singleton[2]
    ok = _aap_ping()
    ttl = _AAP_PING_TTL_OK if ok else _AAP_PING_TTL_FAIL
    _aap_ping_singleton = (key, now + ttl, ok)
    return ok


def _aap_ping_cached_nonblocking() -> bool | None:
    """Read-only cache lookup.  Returns ``None`` when the cache is cold
    (never blocks on a real ping).  The caller should treat ``None`` as
    "status unknown — fetch asynchronously".
    """
    if not _aap_is_configured():
        return False
    key = _aap_ping_cache_key()
    now = time.monotonic()
    if (
        _aap_ping_singleton is not None
        and _aap_ping_singleton[0] == key
        and now < _aap_ping_singleton[1]
    ):
        return _aap_ping_singleton[2]
    return None


def _aap_ping_background() -> None:
    """Run the (blocking) AAP ping and store the result in cache.

    Meant to be called from a daemon thread so the event loop is never
    blocked.
    """
    try:
        _aap_ping_cached(force=True)
    except Exception:
        pass


@app.on_event("startup")
async def _warm_aap_ping_cache() -> None:
    """Fire-and-forget AAP ping in a background thread so the first
    page load is never blocked."""
    if _aap_is_configured():
        t = threading.Thread(target=_aap_ping_background, daemon=True)
        t.start()


@app.middleware("http")
async def inject_aap_status(request: Request, call_next):
    """Make AAP status available to all templates via request.state.

    Uses a *non-blocking* cache read so the event loop is never stalled
    by a synchronous HTTP ping.  When the cache is cold the template
    renders an HTMX placeholder that fetches the real status lazily.
    """
    request.state.aap_configured = _aap_is_configured()
    cached = _aap_ping_cached_nonblocking() if request.state.aap_configured else False
    request.state.aap_connected = cached if cached is not None else False
    request.state.aap_status_unknown = cached is None and request.state.aap_configured
    return await call_next(request)


_orig_template_response = TEMPLATES.TemplateResponse


def _patched_template_response(request_or_name, name_or_ctx=None, context=None, **kwargs):
    """Inject aap_configured/aap_connected into every template context."""
    if isinstance(request_or_name, Request):
        request = request_or_name
        ctx = name_or_ctx if isinstance(name_or_ctx, dict) else (context or {})
        template_name = name_or_ctx if isinstance(name_or_ctx, str) else ""
    else:
        template_name = request_or_name
        ctx = name_or_ctx or context or {}
        request = ctx.get("request")

    aap_configured = getattr(request.state, "aap_configured", False) if request else False
    aap_connected = (
        getattr(request.state, "aap_connected", False) if request else False
    )
    aap_status_unknown = (
        getattr(request.state, "aap_status_unknown", False) if request else False
    )
    ctx.setdefault("aap_configured", aap_configured)
    ctx.setdefault("aap_connected", aap_connected)
    ctx.setdefault("aap_status_unknown", aap_status_unknown)

    return _orig_template_response(request, template_name, ctx, **kwargs)


TEMPLATES.TemplateResponse = _patched_template_response


@app.get("/aap/nav-status", response_class=HTMLResponse)
async def aap_nav_status():
    """Tiny HTMX fragment returning the AAP dot indicator for the nav bar.

    Uses the non-blocking cache read so the response is always instant.
    If the cache is cold, kicks off a background thread to refresh it.
    """
    configured = _aap_is_configured()
    if not configured:
        return HTMLResponse("")

    cached = _aap_ping_cached_nonblocking()
    if cached is None:
        threading.Thread(target=_aap_ping_background, daemon=True).start()
        return HTMLResponse(
            '<span class="ac-aap-dot ac-aap-dot--configured" '
            'title="AAP Configured (checking...)">&#9679;</span>'
        )
    if cached:
        return HTMLResponse(
            '<span class="ac-aap-dot ac-aap-dot--connected" '
            'title="AAP Connected">&#9679;</span>'
        )
    return HTMLResponse(
        '<span class="ac-aap-dot ac-aap-dot--configured" '
        'title="AAP Configured (unreachable)">&#9679;</span>'
    )


@app.get("/api/aap/dashboard")
async def api_aap_dashboard():
    """Aggregated data for the AAP dashboard: resource counts, JT list, UI URLs."""
    import concurrent.futures

    def _do_dashboard():
        try:
            client = _get_aap_client()
        except Exception as exc:
            return {"error": str(exc)}

        def _count(method):
            try:
                return len(method())
            except Exception:
                return 0

        def _jt_list():
            try:
                raw = client.list_job_templates()
                prefix = (AAPSettings.get("job_template_prefix") or "").strip().lower()
                items = []
                for jt in raw:
                    items.append({
                        "id": jt["id"],
                        "name": jt.get("name", ""),
                        "project_name": jt.get("summary_fields", {}).get("project", {}).get("name", ""),
                        "status": jt.get("status", ""),
                        "url": client.ui_url("job_template", jt["id"]),
                        "is_claw": bool(prefix and jt.get("name", "").lower().startswith(prefix)),
                    })
                return items
            except Exception:
                return []

        def _project_list():
            try:
                raw = client.list_projects()
                return [
                    {
                        "id": p["id"],
                        "name": p.get("name", ""),
                        "scm_url": p.get("scm_url", ""),
                        "status": p.get("status", ""),
                        "url": client.ui_url("project", p["id"]),
                    }
                    for p in raw
                ]
            except Exception:
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            fut_jts = pool.submit(_jt_list)
            fut_projs = pool.submit(_project_list)
            fut_inv = pool.submit(_count, client.list_inventories)
            fut_ee = pool.submit(_count, client.list_execution_environments)
            fut_cred = pool.submit(_count, client.list_credentials)

        return {
            "job_templates": fut_jts.result(),
            "projects": fut_projs.result(),
            "inventory_count": fut_inv.result(),
            "ee_count": fut_ee.result(),
            "credential_count": fut_cred.result(),
            "base_url": AAPSettings.get("url").rstrip("/"),
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do_dashboard)


@app.get("/aap", response_class=HTMLResponse)
async def aap_page(request: Request):
    configured = _aap_is_configured()
    settings = AAPSettings.get_all()
    sources = {k: AAPSettings.source_of(k) for k in settings}
    return TEMPLATES.TemplateResponse(request, "aap.html", {
        "page": "aap",
        "aap_settings": settings,
        "aap_sources": sources,
        "aap_configured": configured,
    })


@app.post("/aap/settings", response_class=HTMLResponse)
async def aap_save_settings(
    request: Request,
    url: str = Form(""),
    token: str = Form(""),
    verify_ssl: str = Form(""),
    default_inventory: str = Form(""),
    default_credential: str = Form(""),
    default_organization: str = Form(""),
    default_project: str = Form(""),
    default_ee: str = Form(""),
    default_scm_url: str = Form(""),
    job_template_prefix: str = Form(""),
):
    settings = {
        "url": url.strip(),
        "token": token.strip(),
        "verify_ssl": "true" if verify_ssl else "false",
        "default_inventory": default_inventory.strip(),
        "default_credential": default_credential.strip(),
        "default_organization": default_organization.strip() or "Default",
        "default_project": default_project.strip(),
        "default_ee": default_ee.strip(),
        "default_scm_url": default_scm_url.strip(),
        "job_template_prefix": job_template_prefix.strip(),
    }
    AAPSettings.save(settings)
    _invalidate_aap_client()

    configured = _aap_is_configured()
    loop = asyncio.get_running_loop()
    connected = (
        await loop.run_in_executor(None, lambda: _aap_ping_cached(force=True))
        if configured
        else False
    )

    if configured and connected:
        msg = '<span class="ac-success">\u2713 Settings saved. Connection successful.</span>'
    elif configured:
        msg = (
            '<span class="ac-warning">'
            "\u26a0 Settings saved but connection failed. "
            "Check the URL and token.</span>"
        )
    else:
        msg = '<span class="ac-success">\u2713 Settings saved.</span>'

    return HTMLResponse(
        msg,
        headers={"HX-Trigger-After-Settle": "aapSettingsUpdated"},
    )


@app.get("/aap/ping-stream")
async def aap_ping_stream():
    """Stream HTML fragments for each connectivity check (for live UI updates)."""
    from starlette.responses import StreamingResponse

    def chunks():
        if not _aap_is_configured():
            yield _aap_html_err("Set Controller URL and token first.")
            return
        base = AAPSettings.get("url").rstrip("/")
        yield _aap_html_step(f"Target controller: <code>{base}</code>")
        yield _aap_html_step("Probing <code>/api/v2/ping/</code> (classic API)\u2026")
        ok, err = _aap_ping_request(base, "/api/v2")
        if ok:
            yield _aap_html_ok("Controller responded on <code>/api/v2</code>.")
            _aap_seed_ping_cache(True)
            yield _aap_html_ok("<strong>Connection successful.</strong>")
            return
        yield _aap_html_err(err or "Unreachable")
        yield _aap_html_step("Probing <code>/api/controller/v2/ping/</code> (AAP 2.5 gateway)\u2026")
        ok2, err2 = _aap_ping_request(base, "/api/controller/v2")
        if ok2:
            yield _aap_html_ok("Controller responded on gateway API.")
            _aap_seed_ping_cache(True)
            yield _aap_html_ok("<strong>Connection successful.</strong>")
            return
        yield _aap_html_err(err2 or "Unreachable")
        _aap_seed_ping_cache(False)
        yield _aap_html_err("<strong>Connection failed</strong> on both API paths.")

    return StreamingResponse(chunks(), media_type="text/html; charset=utf-8")


# --- AAP resource listing & deployment ---

def _publish_skills_to_repo(repo_url: str, skill_names: list[str]) -> str | None:
    """Push full skill packages (SKILL.md, assets/, scripts/) to a git repo.

    Returns None on success or an error message string on failure.
    """
    import shutil
    import subprocess
    import tempfile

    if not repo_url:
        return "No git repo URL provided"

    parent = tempfile.mkdtemp(prefix="ansibleclaw-publish-")
    clone_dir = str(Path(parent) / "repo")
    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, clone_dir],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return f"Git clone failed: {r.stderr.strip()}"

        copied = 0
        for skill_name in skill_names:
            src = SKILLS_DIR / skill_name
            dst = Path(clone_dir) / "skills" / skill_name
            if not src.exists():
                continue
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            copied += sum(1 for _ in dst.rglob("*") if _.is_file())

        if copied == 0:
            return f"No skill files found locally under {SKILLS_DIR} for: {', '.join(skill_names)}"

        r = subprocess.run(
            ["git", "add", "skills/"],
            cwd=clone_dir, capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return f"Git add failed: {r.stderr.strip()}"

        r = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=clone_dir, capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            return None

        names_str = ", ".join(skill_names)
        r = subprocess.run(
            ["git", "commit", "-m", f"AnsibleClaw: publish {names_str}",
             "--author", "AnsibleClaw <ansibleclaw@noreply>"],
            cwd=clone_dir, capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return f"Git commit failed: {r.stderr.strip()}"

        r = subprocess.run(
            ["git", "push"],
            cwd=clone_dir, capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return f"Git push failed: {r.stderr.strip()}"

        return None
    except subprocess.TimeoutExpired:
        return "Git operation timed out"
    except Exception as exc:
        return f"Publish failed: {exc}"
    finally:
        shutil.rmtree(parent, ignore_errors=True)


_aap_client_cache: dict[str, "AAPClient"] = {}  # noqa: F821


def _get_aap_client():
    """Return a cached AAPClient so prefix detection only happens once."""
    from ansibleclaw.core.aap import AAPClient, AAPError
    if not _aap_is_configured():
        raise AAPError("AAP is not configured. Set AAP_CONTROLLER_URL and AAP_CONTROLLER_TOKEN.")
    cache_key = f"{AAPSettings.get('url')}|{AAPSettings.get('token')}"
    client = _aap_client_cache.get(cache_key)
    if client is None:
        client = AAPClient(
            base_url=AAPSettings.get("url"),
            token=AAPSettings.get("token"),
            verify_ssl=AAPSettings.get_bool("verify_ssl"),
            organization=AAPSettings.get("default_organization"),
        )
        _aap_client_cache.clear()
        _aap_client_cache[cache_key] = client
    return client


def _invalidate_aap_client():
    _aap_client_cache.clear()
    _invalidate_aap_ping_cache()


def _aap_list_resource_sync(list_method, default_key):
    """Fetch a single AAP resource list. Blocking — call from executor."""
    try:
        client = _get_aap_client()
        resources = list_method(client)
        items = [{"id": r["id"], "name": r["name"]} for r in resources]
        return {"items": items, "default": AAPSettings.get(default_key)}
    except Exception as exc:
        return {"items": [], "error": str(exc)}


@app.get("/api/aap/organizations")
async def api_aap_organizations():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _aap_list_resource_sync, lambda c: c.list_organizations(), "default_organization")


@app.get("/api/aap/projects")
async def api_aap_projects():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _aap_list_resource_sync, lambda c: c.list_projects(), "default_project")


@app.get("/api/aap/execution-environments")
async def api_aap_ees():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _aap_list_resource_sync, lambda c: c.list_execution_environments(), "default_ee")


@app.get("/api/aap/inventories")
async def api_aap_inventories():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _aap_list_resource_sync, lambda c: c.list_inventories(), "default_inventory")


@app.get("/api/aap/credentials")
async def api_aap_credentials():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _aap_list_resource_sync, lambda c: c.list_credentials(), "default_credential")


@app.get("/api/aap/resources")
async def api_aap_all_resources():
    """Fetch projects, EEs, inventories, credentials, and organizations in one call.

    Uses a thread-pool so the five AAP API calls run concurrently, and the
    cached AAPClient avoids redundant prefix detection.  Runs entirely off
    the event loop via ``run_in_executor``.
    """
    import concurrent.futures

    def _do_resources():
        try:
            client = _get_aap_client()
        except Exception as exc:
            return {k: {"items": [], "error": str(exc)} for k in (
                "projects", "execution_environments", "inventories",
                "credentials", "organizations",
            )}

        def _fetch(method, default_key, extra_fields=()):
            try:
                raw = method()
                items = []
                for r in raw:
                    item = {"id": r["id"], "name": r["name"]}
                    for f in extra_fields:
                        item[f] = r.get(f, "")
                    items.append(item)
                return {"items": items, "default": AAPSettings.get(default_key)}
            except Exception as exc:
                return {"items": [], "error": str(exc)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            fut_proj = pool.submit(_fetch, client.list_projects, "default_project", ("scm_url",))
            fut_ee = pool.submit(_fetch, client.list_execution_environments, "default_ee")
            fut_inv = pool.submit(_fetch, client.list_inventories, "default_inventory")
            fut_cred = pool.submit(_fetch, client.list_credentials, "default_credential")
            fut_org = pool.submit(_fetch, client.list_organizations, "default_organization")

        return {
            "projects": fut_proj.result(),
            "execution_environments": fut_ee.result(),
            "inventories": fut_inv.result(),
            "credentials": fut_cred.result(),
            "organizations": fut_org.result(),
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do_resources)


@app.get("/api/aap/projects-list")
async def api_aap_projects_list():
    """Lightweight endpoint returning only the projects list (id, name, scm_url)."""
    def _fetch():
        try:
            client = _get_aap_client()
            raw = client.list_projects()
            items = [
                {"id": r["id"], "name": r["name"], "scm_url": r.get("scm_url", "")}
                for r in raw
            ]
            return {"items": items}
        except Exception as exc:
            return {"items": [], "error": str(exc)}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


@app.get("/api/aap/project-context/{project_id}")
async def api_aap_project_context(project_id: int):
    """Fetch project details plus org/inventory/credential/EE lists in one call.

    Returns the project's scm_url, owning organisation name, and the resolved
    default-EE name so the frontend can auto-select them.  Runs entirely off
    the event loop via ``run_in_executor``.
    """
    import concurrent.futures

    def _do_context():
        try:
            client = _get_aap_client()
        except Exception as exc:
            return {"error": str(exc)}

        try:
            project = client.get_project(project_id)
        except Exception as exc:
            return {"error": f"Failed to fetch project: {exc}"}

        def _fetch_list(method):
            try:
                raw = method()
                return {"items": [{"id": r["id"], "name": r["name"]} for r in raw]}
            except Exception as exc:
                return {"items": [], "error": str(exc)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            fut_org = pool.submit(_fetch_list, client.list_organizations)
            fut_inv = pool.submit(_fetch_list, client.list_inventories)
            fut_cred = pool.submit(_fetch_list, client.list_credentials)
            fut_ee = pool.submit(_fetch_list, client.list_execution_environments)

        org_id = project.get("organization")
        org_name = ""
        org_result = fut_org.result()
        for org in org_result.get("items", []):
            if org["id"] == org_id:
                org_name = org["name"]
                break

        ee_id = project.get("default_environment")
        ee_name = ""
        ee_result = fut_ee.result()
        if ee_id:
            for ee in ee_result.get("items", []):
                if ee["id"] == ee_id:
                    ee_name = ee["name"]
                    break

        return {
            "project": {
                "id": project["id"],
                "name": project["name"],
                "scm_url": project.get("scm_url", ""),
                "organization": org_id,
                "default_environment": ee_id,
            },
            "organization_name": org_name,
            "ee_name": ee_name,
            "organizations": org_result,
            "inventories": fut_inv.result(),
            "credentials": fut_cred.result(),
            "execution_environments": ee_result,
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do_context)


@app.get("/api/aap/project-playbooks/{project_id}")
async def api_aap_project_playbooks(project_id: int):
    """List playbooks AAP sees for a given project (diagnostic helper)."""
    def _fetch():
        try:
            client = _get_aap_client()
            playbooks = client.list_project_playbooks(project_id)
            project_info = client.get_project(project_id)
            return {
                "project_id": project_id,
                "scm_url": project_info.get("scm_url", ""),
                "playbooks": playbooks,
            }
        except Exception as exc:
            return {"error": str(exc)}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


def _step(msg: str) -> str:
    return _aap_html_step(msg)


def _ok(msg: str) -> str:
    return _aap_html_ok(msg)


def _err(msg: str) -> str:
    return _aap_html_err(msg)


def _prefixed_job_template_name(base: str) -> str:
    """Apply ``job_template_prefix`` so AAP admins can spot AnsibleClaw-created JTs."""
    base = (base or "").strip()
    if not base:
        return base
    prefix = (AAPSettings.get("job_template_prefix") or "").strip()
    if not prefix:
        return base
    if base.lower().startswith(prefix.lower()):
        return base
    if prefix.endswith((" ", "\t", "-", "_", ":")):
        return f"{prefix}{base}"
    return f"{prefix} {base}"


@app.post("/api/aap/deploy-skill")
async def api_aap_deploy_skill(
    skill_name: str = Form(...),
    job_template_name: str = Form(""),
    project_id: str = Form(""),
    playbook_path: str = Form(""),
    ee_id: str = Form(""),
    inventory_id: str = Form(...),
    credential_id: str = Form(""),
    collection_fqcn: str = Form(""),
):
    from starlette.responses import StreamingResponse

    def steps():
        from ansibleclaw.core.aap import AAPError

        try:
            client = _get_aap_client()
        except Exception as exc:
            yield _err(str(exc))
            return

        if not project_id:
            yield _err("Select a Project.")
            return

        raw_jt = (job_template_name or skill_name).strip()
        jt_name = _prefixed_job_template_name(raw_jt)
        actual_project_id = int(project_id)
        effective_playbook = playbook_path.strip() or f"skills/{skill_name}/assets/playbook.yml"

        try:
            yield _step("Fetching project info\u2026")
            project_info = client.get_project(actual_project_id)
            scm_url = project_info.get("scm_url", "")
            yield _ok(f"Project: <strong>{project_info.get('name', project_id)}</strong>")

            if scm_url:
                yield _step("Publishing skills to git repo\u2026")
                pub_err = _publish_skills_to_repo(scm_url, [skill_name])
                if pub_err:
                    yield _err(f"Publish to git failed: {pub_err}")
                    return
                yield _ok("Skills pushed to git repo")

                yield _step("Syncing AAP project (this may take a moment)\u2026")
                client.sync_project_and_wait(actual_project_id)
                yield _ok("Project synced")

            yield _step(f"Creating Job Template <code>{jt_name}</code>\u2026")
            result = client.create_job_template(
                name=jt_name,
                project_id=actual_project_id,
                playbook=effective_playbook,
                inventory_id=int(inventory_id),
                ee_id=int(ee_id) if ee_id else None,
            )
            template_id = result.get("id", "")
            yield _ok(f"Job Template <strong>{jt_name}</strong> created (ID: {template_id})")

            if credential_id:
                yield _step("Attaching credential\u2026")
                try:
                    client.add_credential_to_template(template_id, int(credential_id))
                    yield _ok("Credential attached")
                except AAPError:
                    yield _err("Could not attach credential (non-fatal)")

            jt_url = client.ui_url("job_template", template_id)
            collection_note = ""
            if collection_fqcn:
                collection_note = (
                    f' <small>(Ensure your EE includes <code>{collection_fqcn}</code>)</small>'
                )
            yield (
                f'<div style="margin-top:0.5rem;padding:0.5rem 0.75rem;border-radius:var(--pf-t--global--border--radius--small);'
                f'background:var(--pf-t--global--background--color--secondary--default);">'
                f'<span class="ac-success"><strong>Deploy complete.</strong> '
                f'<a href="{jt_url}" target="_blank">View Job Template in AAP</a>'
                f'{collection_note}</span></div>\n'
            )
        except AAPError as exc:
            yield _err(f"Deploy failed: {exc}")

    return StreamingResponse(steps(), media_type="text/html")


@app.post("/api/aap/deploy-collection")
async def api_aap_deploy_collection(
    collection: str = Form(...),
    project_id: str = Form(""),
    playbook_path: str = Form(""),
    ee_id: str = Form(""),
    inventory_id: str = Form(...),
    credential_id: str = Form(""),
):
    from starlette.responses import StreamingResponse

    def steps():
        from ansibleclaw.core.aap import AAPError
        from ansibleclaw.cli import _module_to_skill_name

        try:
            client = _get_aap_client()
        except Exception as exc:
            yield _err(str(exc))
            return

        if not project_id:
            yield _err("Select a Project.")
            return

        actual_project_id = int(project_id)

        yield _step("Listing modules in collection\u2026")
        try:
            modules = list_modules(namespace=collection)
        except AnsibleDocError as exc:
            yield _err(f"Cannot list modules: {exc}")
            return

        all_skill_names = [
            _module_to_skill_name(m) for m in sorted(modules.keys())
        ]
        yield _ok(f"Found {len(all_skill_names)} module(s) in <strong>{collection}</strong>")

        yield _step("Fetching project info\u2026")
        try:
            project_info = client.get_project(actual_project_id)
        except AAPError as exc:
            yield _err(f"Cannot read project: {exc}")
            return
        yield _ok(f"Project: <strong>{project_info.get('name', project_id)}</strong>")

        scm_url = project_info.get("scm_url", "")
        if scm_url:
            yield _step(f"Publishing {len(all_skill_names)} skill(s) to git repo\u2026")
            pub_err = _publish_skills_to_repo(scm_url, all_skill_names)
            if pub_err:
                yield _err(f"Publish to git failed: {pub_err}")
                return
            yield _ok("Skills pushed to git repo")

            yield _step("Syncing AAP project (this may take a moment)\u2026")
            try:
                client.sync_project_and_wait(actual_project_id)
            except AAPError as exc:
                yield _err(f"Project sync failed: {exc}")
                return
            yield _ok("Project synced")

        base_playbook_dir = playbook_path.strip().rstrip("/") if playbook_path.strip() else ""

        yield _step("Creating Job Templates\u2026")
        successes = 0
        failures = []
        for skill_dir_name in all_skill_names:
            jt_name = _prefixed_job_template_name(skill_dir_name.replace("_", "-"))
            if base_playbook_dir:
                effective_pb = f"{base_playbook_dir}/skills/{skill_dir_name}/assets/playbook.yml"
            else:
                effective_pb = f"skills/{skill_dir_name}/assets/playbook.yml"
            try:
                result = client.create_job_template(
                    name=jt_name,
                    project_id=actual_project_id,
                    playbook=effective_pb,
                    inventory_id=int(inventory_id),
                    ee_id=int(ee_id) if ee_id else None,
                )
                template_id = result.get("id", "")
                if credential_id:
                    try:
                        client.add_credential_to_template(template_id, int(credential_id))
                    except AAPError:
                        pass
                successes += 1
                yield _ok(f"<strong>{jt_name}</strong> (ID: {template_id})")
            except AAPError as exc:
                failures.append(jt_name)
                yield _err(f"<strong>{jt_name}</strong>: {exc}")

        summary_parts = []
        if successes:
            summary_parts.append(f"{successes} created")
        if failures:
            summary_parts.append(f"{len(failures)} failed")
        summary = ", ".join(summary_parts) if summary_parts else "No modules found"

        yield (
            f'<div style="margin-top:0.5rem;padding:0.5rem 0.75rem;border-radius:var(--pf-t--global--border--radius--small);'
            f'background:var(--pf-t--global--background--color--secondary--default);">'
            f'<strong>Deploy complete.</strong> {summary}</div>\n'
        )

    return StreamingResponse(steps(), media_type="text/html")


# =====================================================================
# Gemini CLI Agent — ttyd integration
# =====================================================================

_gemini_logger = logging.getLogger("ansibleclaw.agents.gemini")

_gemini_ttyd_process: Optional[subprocess.Popen] = None
_gemini_ttyd_port: Optional[int] = None


def _is_ttyd_installed() -> bool:
    return shutil.which("ttyd") is not None


def _find_gemini_command() -> Optional[str]:
    return shutil.which("gemini")


def _find_available_port(start: int = 7682, attempts: int = 100) -> int:
    for offset in range(attempts):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No available port in range {start}-{start + attempts}")


def _start_ttyd_for_gemini(cwd: str | None = None) -> dict:
    global _gemini_ttyd_process, _gemini_ttyd_port

    if _gemini_ttyd_process is not None and _gemini_ttyd_process.poll() is None:
        return {
            "success": True,
            "already_running": True,
            "port": _gemini_ttyd_port,
            "ws_url": "/ws/gemini",
        }

    if not _is_ttyd_installed():
        return {
            "success": False,
            "error": "ttyd is not installed",
            "install_instructions": {
                "macos": "brew install ttyd",
                "ubuntu": "sudo apt install ttyd",
            },
        }

    gemini_path = _find_gemini_command()
    if not gemini_path:
        return {"success": False, "error": "gemini CLI is not installed"}

    try:
        port = _find_available_port()
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}

    env = os.environ.copy()
    if "HOME" not in env:
        env["HOME"] = os.path.expanduser("~")

    work_dir = cwd or os.getcwd()

    ttyd_cmd = [
        "ttyd",
        "--port", str(port),
        "--interface", "127.0.0.1",
        "--writable",
        gemini_path,
    ]

    _gemini_logger.info("Starting ttyd: %s (cwd=%s)", " ".join(ttyd_cmd), work_dir)

    try:
        _gemini_ttyd_process = subprocess.Popen(
            ttyd_cmd,
            env=env,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _gemini_ttyd_port = port

        max_wait = 10.0
        poll_interval = 0.3
        waited = 0.0
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval

            if _gemini_ttyd_process.poll() is not None:
                exit_code = _gemini_ttyd_process.returncode
                _, stderr_output = _gemini_ttyd_process.communicate(timeout=1)
                stderr_str = stderr_output.decode("utf-8", errors="replace") if stderr_output else ""
                _gemini_logger.error("ttyd exited with code %s: %s", exit_code, stderr_str)
                _gemini_ttyd_process = None
                _gemini_ttyd_port = None
                return {"success": False, "error": f"ttyd exited with code {exit_code}: {stderr_str}"}

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    break
        else:
            _gemini_logger.error("ttyd not listening on port %s after %.1fs", port, max_wait)
            _gemini_ttyd_process.terminate()
            _gemini_ttyd_process = None
            _gemini_ttyd_port = None
            return {"success": False, "error": f"ttyd not listening on port {port} after {max_wait}s"}

        _gemini_logger.info("ttyd started on port %s, pid %s", port, _gemini_ttyd_process.pid)
        return {
            "success": True,
            "already_running": False,
            "port": port,
            "ws_url": "/ws/gemini",
            "pid": _gemini_ttyd_process.pid,
        }
    except Exception as exc:
        _gemini_logger.error("Failed to start ttyd: %s", exc)
        return {"success": False, "error": str(exc)}


def _stop_gemini_ttyd() -> dict:
    global _gemini_ttyd_process, _gemini_ttyd_port

    if _gemini_ttyd_process is None:
        return {"success": True, "message": "ttyd was not running"}

    if _gemini_ttyd_process.poll() is not None:
        _gemini_ttyd_process = None
        _gemini_ttyd_port = None
        return {"success": True, "message": "ttyd had already exited"}

    try:
        pid = _gemini_ttyd_process.pid
        _gemini_ttyd_process.terminate()
        try:
            _gemini_ttyd_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _gemini_ttyd_process.kill()
            _gemini_ttyd_process.wait()
        _gemini_ttyd_process = None
        _gemini_ttyd_port = None
        _gemini_logger.info("ttyd stopped (pid %s)", pid)
        return {"success": True, "message": f"ttyd stopped (pid: {pid})"}
    except Exception as exc:
        _gemini_logger.error("Error stopping ttyd: %s", exc)
        return {"success": False, "error": str(exc)}


@app.get("/api/agents/gemini/status")
async def api_gemini_status():
    gemini_path = _find_gemini_command()
    return {
        "ttyd_available": _is_ttyd_installed(),
        "gemini_installed": gemini_path is not None,
        "gemini_path": gemini_path,
        "ttyd_running": (
            _gemini_ttyd_process is not None
            and _gemini_ttyd_process.poll() is None
        ),
        "ttyd_port": _gemini_ttyd_port,
    }


@app.post("/api/agents/gemini/start-terminal")
async def api_gemini_start_terminal(request: Request):
    cwd = None
    try:
        body = await request.json()
        cwd = body.get("cwd")
    except Exception:
        pass
    result = _start_ttyd_for_gemini(cwd=cwd)
    return JSONResponse(result)


@app.post("/api/agents/gemini/stop-terminal")
async def api_gemini_stop_terminal():
    return JSONResponse(_stop_gemini_ttyd())



@app.get("/agents/gemini")
async def agents_gemini_page(request: Request, cwd: str = Query("")):
    default_cwd = cwd.strip() if cwd.strip() else str(Path.cwd())
    return TEMPLATES.TemplateResponse(
        request,
        "agents_gemini.html",
        {"page": "agents-gemini", "default_cwd": default_cwd},
    )


# =====================================================================
# Starter Pack — archive upload, browse, and router skill generation
# =====================================================================

_sp_logger = logging.getLogger("ansibleclaw.starterpack")

_starter_pack_dir: Optional[Path] = None
_starter_pack_use_cases: list[dict] = []

_SP_CATEGORIES = [
    (range(1, 33), "Linux Operations"),
    (range(81, 86), "Windows Operations"),
    (range(101, 104), "VMware vSphere Operations"),
]


def _sp_category(folder_name: str) -> str:
    m = re.match(r"^(\d+)", folder_name)
    if not m:
        return "Other"
    num = int(m.group(1))
    for rng, label in _SP_CATEGORIES:
        if num in rng:
            return label
    return "Other"


def _sp_extract_archive(data: bytes, filename: str) -> Path:
    global _starter_pack_dir
    if _starter_pack_dir and _starter_pack_dir.exists():
        shutil.rmtree(_starter_pack_dir, ignore_errors=True)

    tmp = Path(tempfile.mkdtemp(prefix="ansibleclaw_sp_")).resolve()

    lower = filename.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    (tmp / info.filename).mkdir(parents=True, exist_ok=True)
                    continue
                dest = (tmp / info.filename).resolve()
                if not str(dest).startswith(str(tmp)):
                    continue
                zf.extract(info, tmp)
    elif lower.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
        with tarfile.open(fileobj=BytesIO(data)) as tf:
            safe_members = []
            for member in tf.getmembers():
                dest = (tmp / member.name).resolve()
                if str(dest).startswith(str(tmp)):
                    safe_members.append(member)
            tf.extractall(tmp, members=safe_members, filter="data")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"Unsupported archive format: {filename}")

    _starter_pack_dir = _sp_find_use_case_root(tmp)
    _sp_logger.info(
        "Extracted %s -> %s (%d top-level items)",
        filename, _starter_pack_dir,
        len(list(_starter_pack_dir.iterdir())),
    )
    return _starter_pack_dir


def _sp_find_use_case_root(base: Path) -> Path:
    """Drill into wrapper directories until we find the level with use case folders."""
    _skip = {"__MACOSX", ".DS_Store"}
    for _ in range(5):
        children = [
            c for c in base.iterdir()
            if not c.name.startswith(".") and c.name not in _skip
        ]
        dirs = [c for c in children if c.is_dir()]
        if not dirs:
            return base
        has_yml_dirs = any(
            list(d.glob("*.yml")) or list(d.glob("*.yaml")) or list(d.rglob("*.yml"))
            for d in dirs
        )
        if has_yml_dirs and len(dirs) > 1:
            return base
        if len(dirs) == 1 and len(children) <= 2:
            base = dirs[0]
            continue
        return base
    return base


def _sp_scan_use_cases(base: Path) -> list[dict]:
    global _starter_pack_use_cases
    cases = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name == "__MACOSX":
            continue

        yml_files = list(d.glob("*.yml")) + list(d.glob("*.yaml"))
        playbooks = [
            f.name for f in yml_files
            if f.name not in ("requirements.yml",)
            and not f.name.startswith(".")
        ]

        templates = [f.name for f in d.glob("*.j2")]

        if not playbooks and not templates:
            sub_ymls = list(d.rglob("*.yml")) + list(d.rglob("*.yaml"))
            if sub_ymls:
                playbooks = [
                    str(f.relative_to(d)) for f in sub_ymls
                    if f.name not in ("requirements.yml",)
                    and not f.name.startswith(".")
                ]
            sub_j2 = list(d.rglob("*.j2"))
            if sub_j2:
                templates = [str(f.relative_to(d)) for f in sub_j2]

        if not playbooks:
            continue

        other = []
        for f in d.iterdir():
            if f.is_file() and f.suffix not in (".yml", ".yaml", ".j2"):
                fname = f.name.lower()
                if fname not in ("readme.md", "readme.txt", "readme"):
                    other.append(f.name)

        readme_text = ""
        for rn in ("README.md", "readme.md", "README.txt", "README",
                    "README.MD", "Readme.md"):
            rp = d / rn
            if rp.is_file():
                try:
                    readme_text = rp.read_text(errors="replace")
                except Exception:
                    pass
                break

        desc = ""
        if readme_text:
            for line in readme_text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    desc = stripped[:200]
                    break

        cases.append({
            "name": d.name,
            "category": _sp_category(d.name),
            "description": desc,
            "readme": readme_text,
            "playbooks": sorted(playbooks),
            "templates": sorted(templates),
            "other_files": sorted(other),
        })

    _starter_pack_use_cases = cases
    _sp_logger.info("Scanned %d use cases from %s", len(cases), base)
    return cases


def _sp_generate_router_skill(
    skill_name: str,
    selected_names: list[str],
    target: str,
    custom_path: str = "",
) -> dict:
    if not _starter_pack_dir or not _starter_pack_use_cases:
        return {"success": False, "error": "No starter pack uploaded"}

    selected = [uc for uc in _starter_pack_use_cases if uc["name"] in selected_names]
    if not selected:
        return {"success": False, "error": "No use cases selected"}

    dir_name = re.sub(r"[^a-zA-Z0-9_]", "_", skill_name).strip("_").lower()
    if not dir_name:
        dir_name = "starter_pack"

    if target == "project":
        output_dir = SKILLS_DIR / dir_name
    elif target in INSTALL_PATHS:
        output_dir = INSTALL_PATHS[target] / dir_name
    elif target == "custom" and custom_path:
        output_dir = Path(custom_path) / dir_name
    else:
        output_dir = SKILLS_DIR / dir_name

    output_dir.mkdir(parents=True, exist_ok=True)

    aap = AAPSettings.get_all()
    aap_configured = bool(aap.get("url") and aap.get("token"))

    skill_template_dir = Path(__file__).resolve().parent.parent / "templates"
    sp_template_path = skill_template_dir / "starter_pack_skill.md.j2"

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(skill_template_dir)))
    tmpl = env.get_template("starter_pack_skill.md.j2")

    categories_ordered = []
    cat_map: dict[str, list] = {}
    for uc in selected:
        cat = uc["category"]
        if cat not in cat_map:
            cat_map[cat] = []
            categories_ordered.append(cat)
        cat_map[cat].append(uc)

    skill_md = tmpl.render(
        skill_name=skill_name,
        dir_name=dir_name,
        use_cases=selected,
        categories=categories_ordered,
        categories_map=cat_map,
        aap_configured=aap_configured,
        aap_url=aap.get("url", ""),
        aap_inventory=aap.get("default_inventory", ""),
        aap_credential=aap.get("default_credential", ""),
        aap_project=aap.get("default_project", ""),
        aap_organization=aap.get("default_organization", "Default"),
        aap_ee=aap.get("default_ee", ""),
    )

    (output_dir / "SKILL.md").write_text(skill_md)

    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    run_sh = "#!/usr/bin/env bash\nset -euo pipefail\n"
    run_sh += 'USE_CASE="${1:?Usage: run.sh <use_case_folder> [--apply]}"\n'
    run_sh += 'SHIFT_ARGS="${@:2}"\n'
    run_sh += 'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
    run_sh += 'ASSETS_DIR="$SCRIPT_DIR/../assets"\n'
    run_sh += 'PLAYBOOK=$(find "$ASSETS_DIR/$USE_CASE" -maxdepth 1 -name "*.yml" | head -1)\n'
    run_sh += 'if [ -z "$PLAYBOOK" ]; then echo "No playbook found in $USE_CASE"; exit 1; fi\n'
    run_sh += 'if [[ " $SHIFT_ARGS " == *" --apply "* ]]; then\n'
    run_sh += '  ansible-playbook "$PLAYBOOK"\n'
    run_sh += 'else\n'
    run_sh += '  ansible-playbook "$PLAYBOOK" --check --diff\n'
    run_sh += 'fi\n'
    (scripts_dir / "run.sh").write_text(run_sh)
    (scripts_dir / "run.sh").chmod(0o755)

    check_sh = "#!/usr/bin/env bash\nset -euo pipefail\n"
    check_sh += 'command -v ansible-playbook >/dev/null 2>&1 || { echo "ansible-core not found"; exit 1; }\n'
    check_sh += 'echo "ansible-playbook: $(ansible-playbook --version | head -1)"\n'
    check_sh += 'if [ -n "${AAP_CONTROLLER_URL:-}" ]; then\n'
    check_sh += '  echo "AAP Controller: $AAP_CONTROLLER_URL"\n'
    check_sh += '  curl -sf -o /dev/null -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" "${AAP_CONTROLLER_URL}/api/v2/ping/" && echo "AAP: reachable" || echo "AAP: unreachable"\n'
    check_sh += 'fi\n'
    (scripts_dir / "check.sh").write_text(check_sh)
    (scripts_dir / "check.sh").chmod(0o755)

    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    for uc in selected:
        src = _starter_pack_dir / uc["name"]
        dst = assets_dir / uc["name"]
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    _sp_logger.info("Router skill generated: %s (%d use cases)", output_dir, len(selected))

    return {
        "success": True,
        "skill_name": dir_name,
        "output_dir": str(output_dir),
        "use_case_count": len(selected),
        "target": target,
    }


# --- Starter Pack API endpoints ---

@app.get("/starter-pack")
async def starter_pack_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request,
        "starter_pack.html",
        {
            "page": "starter-pack",
            "use_cases": _starter_pack_use_cases,
            "has_upload": _starter_pack_dir is not None,
            "platforms": list(INSTALL_PATHS.keys()),
        },
    )


@app.post("/api/starter-pack/upload")
async def api_starter_pack_upload(file: UploadFile):
    if not file.filename:
        return JSONResponse({"success": False, "error": "No file provided"})

    data = await file.read()
    if len(data) == 0:
        return JSONResponse({"success": False, "error": "Empty file"})

    try:
        base = _sp_extract_archive(data, file.filename)
        cases = _sp_scan_use_cases(base)
        return JSONResponse({
            "success": True,
            "use_case_count": len(cases),
            "use_cases": cases,
        })
    except Exception as exc:
        _sp_logger.error("Starter pack upload failed: %s", exc)
        return JSONResponse({"success": False, "error": str(exc)})


@app.get("/api/starter-pack/use-case/{name}/readme")
async def api_starter_pack_readme(name: str):
    if not _starter_pack_dir:
        return JSONResponse({"error": "No starter pack uploaded"}, status_code=404)
    uc_dir = (_starter_pack_dir / name).resolve()
    if not str(uc_dir).startswith(str(_starter_pack_dir.resolve())):
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    for rn in ("README.md", "readme.md", "README.txt", "README"):
        rp = uc_dir / rn
        if rp.is_file():
            return Response(rp.read_text(errors="replace"), media_type="text/plain")
    return Response("No README found.", media_type="text/plain")


@app.get("/api/starter-pack/use-case/{name}/file/{path:path}")
async def api_starter_pack_file(name: str, path: str):
    if not _starter_pack_dir:
        return JSONResponse({"error": "No starter pack uploaded"}, status_code=404)
    file_path = (_starter_pack_dir / name / path).resolve()
    if not str(file_path).startswith(str(_starter_pack_dir.resolve())):
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    if not file_path.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        content = file_path.read_text(errors="replace")
        return Response(content, media_type="text/plain")
    except Exception:
        return JSONResponse({"error": "Cannot read file"}, status_code=400)


@app.post("/api/starter-pack/generate")
async def api_starter_pack_generate(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON"})

    skill_name = body.get("skill_name", "starter_pack")
    selected = body.get("selected_use_cases", [])
    target = body.get("target", "project")
    custom_path = body.get("custom_path", "")

    result = _sp_generate_router_skill(skill_name, selected, target, custom_path)
    return JSONResponse(result)
