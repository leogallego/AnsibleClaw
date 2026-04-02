"""AnsibleClaw Web Dashboard.

FastAPI application with routes for skills management, module search,
skill generation with preview, and ZIP download.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ansibleclaw.config import (
    AAP_CONTROLLER_TOKEN,
    AAP_CONTROLLER_URL,
    AAP_DEFAULT_CREDENTIAL,
    AAP_DEFAULT_EE,
    AAP_DEFAULT_INVENTORY,
    AAP_DEFAULT_ORGANIZATION,
    AAP_DEFAULT_PROJECT,
    AAP_VERIFY_SSL,
    BUILTINS_DIR,
    INSTALL_PATHS,
    SKILLS_DIR,
    TEMPLATE_DIR,
    TEMPLATE_PATH,
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
        return HTMLResponse(f'<p class="ac-error">{exc}</p>', status_code=400)

    from ansibleclaw.cli import _module_to_skill_name, _write_skill_package
    skill_name = _module_to_skill_name(metadata["module_name"])

    if target == "project":
        output_dir = SKILLS_DIR / skill_name
    elif target in INSTALL_PATHS:
        output_dir = INSTALL_PATHS[target] / skill_name
    elif target == "custom" and custom_path:
        output_dir = Path(custom_path) / skill_name
    else:
        return HTMLResponse("Invalid target", status_code=400)

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
            status_code=400,
        )

    try:
        modules = list_modules(namespace=collection)
    except AnsibleDocError as exc:
        return HTMLResponse(
            f'<span class="ac-error">{exc}</span>', status_code=400,
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
            f'<span class="ac-error">Failed: {exc}</span>', status_code=500,
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
            status_code=400,
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
            status_code=400,
        )
    return HTMLResponse(
        content=(
            f'<span class="ac-success">'
            f"\u2713 Uninstalled {collection}</span>"
        ),
        headers={"HX-Trigger-After-Settle": "collectionsUpdated"},
    )


# --- AAP ---

def _aap_env_info() -> dict:
    """Gather AAP environment variable state."""
    return {
        "url": AAP_CONTROLLER_URL,
        "token": AAP_CONTROLLER_TOKEN,
        "verify_ssl": AAP_VERIFY_SSL,
        "default_inventory": AAP_DEFAULT_INVENTORY,
        "default_credential": AAP_DEFAULT_CREDENTIAL,
        "default_organization": AAP_DEFAULT_ORGANIZATION,
    }


def _aap_is_configured() -> bool:
    return bool(AAP_CONTROLLER_URL and AAP_CONTROLLER_TOKEN)


def _aap_ping() -> bool:
    """Try to reach the AAP Controller /api/v2/ping/ endpoint."""
    if not _aap_is_configured():
        return False
    import ssl
    import urllib.error
    import urllib.request

    url = f"{AAP_CONTROLLER_URL.rstrip('/')}/api/v2/ping/"
    headers = {"Authorization": f"Bearer {AAP_CONTROLLER_TOKEN}"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = None
    if not AAP_VERIFY_SSL:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


@app.middleware("http")
async def inject_aap_status(request: Request, call_next):
    """Make AAP status available to all templates via request.state."""
    request.state.aap_configured = _aap_is_configured()
    request.state.aap_connected = False
    return await call_next(request)


# Override template context to include AAP status in all pages
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
    ctx.setdefault("aap_configured", aap_configured)
    ctx.setdefault("aap_connected", False)

    return _orig_template_response(request, template_name, ctx, **kwargs)


TEMPLATES.TemplateResponse = _patched_template_response


@app.get("/aap", response_class=HTMLResponse)
async def aap_page(request: Request):
    connected = _aap_ping() if _aap_is_configured() else False
    return TEMPLATES.TemplateResponse(request, "aap.html", {
        "page": "aap",
        "aap_env": _aap_env_info(),
        "aap_configured": _aap_is_configured(),
        "aap_connected": connected,
    })


@app.get("/aap/ping", response_class=HTMLResponse)
async def aap_ping():
    if _aap_ping():
        return HTMLResponse('<span class="ac-success">Connection successful</span>')
    return HTMLResponse('<span class="ac-error">Connection failed</span>')


# --- AAP resource listing & deployment ---

def _get_aap_client():
    from ansibleclaw.core.aap import AAPClient, AAPError
    if not _aap_is_configured():
        raise AAPError("AAP is not configured. Set AAP_CONTROLLER_URL and AAP_CONTROLLER_TOKEN.")
    return AAPClient(
        base_url=AAP_CONTROLLER_URL,
        token=AAP_CONTROLLER_TOKEN,
        verify_ssl=AAP_VERIFY_SSL,
        organization=AAP_DEFAULT_ORGANIZATION,
    )


@app.get("/api/aap/projects")
async def api_aap_projects():
    try:
        client = _get_aap_client()
        resources = client.list_projects()
        items = [{"id": r["id"], "name": r["name"]} for r in resources]
        return {"items": items, "default": AAP_DEFAULT_PROJECT}
    except Exception as exc:
        return {"items": [], "error": str(exc)}


@app.get("/api/aap/execution-environments")
async def api_aap_ees():
    try:
        client = _get_aap_client()
        resources = client.list_execution_environments()
        items = [{"id": r["id"], "name": r["name"]} for r in resources]
        return {"items": items, "default": AAP_DEFAULT_EE}
    except Exception as exc:
        return {"items": [], "error": str(exc)}


@app.get("/api/aap/inventories")
async def api_aap_inventories():
    try:
        client = _get_aap_client()
        resources = client.list_inventories()
        items = [{"id": r["id"], "name": r["name"]} for r in resources]
        return {"items": items, "default": AAP_DEFAULT_INVENTORY}
    except Exception as exc:
        return {"items": [], "error": str(exc)}


@app.get("/api/aap/credentials")
async def api_aap_credentials():
    try:
        client = _get_aap_client()
        resources = client.list_credentials()
        items = [{"id": r["id"], "name": r["name"]} for r in resources]
        return {"items": items, "default": AAP_DEFAULT_CREDENTIAL}
    except Exception as exc:
        return {"items": [], "error": str(exc)}


@app.post("/api/aap/deploy-skill", response_class=HTMLResponse)
async def api_aap_deploy_skill(
    skill_name: str = Form(...),
    job_template_name: str = Form(""),
    project_id: str = Form(""),
    scm_url: str = Form(""),
    ee_id: str = Form(""),
    inventory_id: str = Form(...),
    credential_id: str = Form(""),
    collection_fqcn: str = Form(""),
):
    from ansibleclaw.core.aap import AAPError

    try:
        client = _get_aap_client()
    except Exception as exc:
        return HTMLResponse(f'<span class="ac-error">{exc}</span>', status_code=400)

    jt_name = job_template_name or skill_name

    try:
        actual_project_id: int
        if project_id and project_id != "__new__":
            actual_project_id = int(project_id)
        elif scm_url:
            project = client.create_project(
                name=f"AnsibleClaw - {jt_name}",
                scm_url=scm_url,
            )
            actual_project_id = project["id"]
            try:
                client.sync_project(actual_project_id)
            except AAPError:
                pass
        else:
            return HTMLResponse(
                '<span class="ac-error">Select a Project or provide a Git repo URL.</span>',
                status_code=400,
            )

        skill_dir = _resolve_skill_dir(skill_name)
        if skill_dir and (skill_dir / "assets" / "playbook.yml").exists():
            playbook_path = f"skills/{skill_name}/assets/playbook.yml"
        else:
            playbook_path = f"skills/{skill_name}/assets/playbook.yml"

        result = client.create_job_template(
            name=jt_name,
            project_id=actual_project_id,
            playbook=playbook_path,
            inventory_id=int(inventory_id),
            ee_id=int(ee_id) if ee_id else None,
        )

        template_id = result.get("id", "")
        if credential_id:
            try:
                client.add_credential_to_template(template_id, int(credential_id))
            except AAPError:
                pass

        jt_url = f"{AAP_CONTROLLER_URL}/#/templates/job_template/{template_id}/details"
        collection_note = ""
        if collection_fqcn:
            collection_note = (
                f' <small>(Ensure your EE includes <code>{collection_fqcn}</code>)</small>'
            )

        return HTMLResponse(
            f'<span class="ac-success">'
            f'\u2713 Job Template <strong>{jt_name}</strong> created '
            f'(<a href="{jt_url}" target="_blank">View in AAP</a>)'
            f'{collection_note}</span>'
        )
    except AAPError as exc:
        return HTMLResponse(
            f'<span class="ac-error">Deploy failed: {exc}</span>',
            status_code=400,
        )


@app.post("/api/aap/deploy-collection", response_class=HTMLResponse)
async def api_aap_deploy_collection(
    collection: str = Form(...),
    project_id: str = Form(""),
    scm_url: str = Form(""),
    ee_id: str = Form(""),
    inventory_id: str = Form(...),
    credential_id: str = Form(""),
):
    from ansibleclaw.core.aap import AAPError
    from ansibleclaw.cli import _module_to_skill_name

    try:
        client = _get_aap_client()
    except Exception as exc:
        return HTMLResponse(f'<span class="ac-error">{exc}</span>', status_code=400)

    actual_project_id: int
    if project_id and project_id != "__new__":
        actual_project_id = int(project_id)
    elif scm_url:
        try:
            project = client.create_project(
                name=f"AnsibleClaw - {collection}",
                scm_url=scm_url,
            )
            actual_project_id = project["id"]
            try:
                client.sync_project(actual_project_id)
            except AAPError:
                pass
        except AAPError as exc:
            return HTMLResponse(
                f'<span class="ac-error">Project creation failed: {exc}</span>',
                status_code=400,
            )
    else:
        return HTMLResponse(
            '<span class="ac-error">Select a Project or provide a Git repo URL.</span>',
            status_code=400,
        )

    try:
        modules = list_modules(namespace=collection)
    except AnsibleDocError as exc:
        return HTMLResponse(
            f'<span class="ac-error">Cannot list modules: {exc}</span>',
            status_code=400,
        )

    successes: list[str] = []
    failures: list[str] = []

    for module_name in sorted(modules.keys()):
        skill_dir_name = _module_to_skill_name(module_name)
        skill_dir = _resolve_skill_dir(skill_dir_name)
        if not skill_dir or not (skill_dir / "assets" / "playbook.yml").exists():
            failures.append(f"{module_name}: skill not generated yet")
            continue

        jt_name = skill_dir_name.replace("_", "-")
        playbook_path = f"skills/{skill_dir_name}/assets/playbook.yml"
        try:
            result = client.create_job_template(
                name=jt_name,
                project_id=actual_project_id,
                playbook=playbook_path,
                inventory_id=int(inventory_id),
                ee_id=int(ee_id) if ee_id else None,
            )
            template_id = result.get("id", "")
            if credential_id:
                try:
                    client.add_credential_to_template(template_id, int(credential_id))
                except AAPError:
                    pass
            successes.append(f"{jt_name} (ID: {template_id})")
        except AAPError as exc:
            failures.append(f"{module_name}: {exc}")

    parts: list[str] = []
    if successes:
        items = "".join(f"<li>{s}</li>" for s in successes)
        parts.append(
            f'<p class="ac-success">\u2713 {len(successes)} Job Template(s) created:</p>'
            f"<ul>{items}</ul>"
        )
    if failures:
        items = "".join(f"<li>{f}</li>" for f in failures)
        parts.append(
            f'<p class="ac-error">{len(failures)} failed:</p>'
            f"<ul>{items}</ul>"
        )
    if not parts:
        parts.append('<span class="ac-warning">No module skills found for this collection.</span>')

    return HTMLResponse("".join(parts))
