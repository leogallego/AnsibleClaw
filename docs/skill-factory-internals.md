# Skill Factory Internals

How AnsibleClaw converts an Ansible module into a dual-mode skill package.

---

## Overview

The skill factory is a build-time pipeline with four phases:

1. **Scrape** -- shell out to `ansible-doc --json` and get structured module documentation
2. **Extract** -- normalize the JSON into a flat metadata dict (params, examples, description)
3. **Context** -- derive template variables (skill name, example CLI args) from the metadata
4. **Render** -- feed the context into 5 Jinja2 templates to produce the skill package

The output is a self-contained directory that works in two modes: direct CLI for development, and AAP Controller API for production.

```
ansible_package/
├── SKILL.md              # Dual-mode instructions (CLI + AAP)
├── scripts/
│   ├── run.sh            # CLI wrapper (dry-run by default)
│   ├── check.sh          # Prerequisite checker (CLI + AAP)
│   └── aap_run.py        # AAP Controller API helper (stdlib only)
└── assets/
    └── playbook.yml      # Ready-to-use Ansible playbook
```

---

## Phase 1: Scrape ansible-doc

**File:** `src/ansibleclaw/core/parser.py`

When you run:

```bash
ansibleclaw generate "ansible.builtin.package"
```

The CLI entrypoint (`cli.py:cmd_generate`) calls `get_module_doc()`, which shells out to the real `ansible-doc` binary:

```python
# parser.py
def get_module_doc(module_name: str) -> dict[str, Any]:
    raw = _run_ansible_doc(module_name, "--json")
    doc = json.loads(raw)
    return doc
```

Under the hood, `_run_ansible_doc` locates the `ansible-doc` binary (preferring the current venv), then runs:

```bash
ansible-doc ansible.builtin.package --json
```

The JSON that comes back is a dict keyed by the fully-qualified module name:

```json
{
    "ansible.builtin.package": {
        "doc": {
            "module": "ansible.builtin.package",
            "short_description": "Generic OS package manager",
            "description": ["Installs, upgrades, removes packages using the OS package manager."],
            "options": {
                "name": {
                    "description": ["Package name, or package specifier with version."],
                    "type": "str",
                    "required": true
                },
                "state": {
                    "description": ["Whether to install (present), or remove (absent) a package."],
                    "type": "str",
                    "required": true,
                    "choices": ["present", "absent", "latest"]
                },
                "use": {
                    "description": ["The required package manager module to use."],
                    "type": "str",
                    "required": false,
                    "default": "auto",
                    "choices": ["auto", "apt", "dnf", "yum"]
                }
            }
        },
        "examples": "- name: Install ntpdate\n  ansible.builtin.package:\n    name: ntpdate\n    state: present\n"
    }
}
```

---

## Phase 2: Extract Metadata

**File:** `src/ansibleclaw/core/parser.py`

Back in `cmd_generate`, the raw doc is passed to `extract_module_metadata()`, which combines three extractors:

```python
# parser.py
def extract_module_metadata(module_doc):
    module_name = _get_module_name(module_doc)
    return {
        "module_name": module_name,
        "short_description": extract_short_description(module_doc),
        "params": extract_params(module_doc),
        "examples": extract_examples(module_doc),
    }
```

### extract_params

Iterates over `doc.options`, normalizes each parameter into a consistent dict, then **sorts required params first** (alphabetical within each group):

```python
# parser.py
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
```

### extract_examples

Returns the raw YAML examples string from `ansible-doc`. This is the content that appears verbatim in the generated SKILL.md and drives the playbook.yml tasks.

### extract_short_description

Pulls the one-line description from `doc.short_description`.

### Result

For `ansible.builtin.package`, the metadata dict is:

```python
{
    "module_name": "ansible.builtin.package",
    "short_description": "Generic OS package manager",
    "params": [
        {"name": "name",  "type": "str", "required": True,  "default": None,   "choices": None,                            "description": "Package name, or..."},
        {"name": "state", "type": "str", "required": True,  "default": None,   "choices": ["present", "absent", "latest"], "description": "Whether to install..."},
        {"name": "use",   "type": "str", "required": False, "default": "auto", "choices": ["auto", "apt", "dnf", "yum"],  "description": "The required package..."},
    ],
    "examples": "- name: Install ntpdate\n  ansible.builtin.package:\n    name: ntpdate\n    state: present",
}
```

---

## Phase 3: Build Template Context

**File:** `src/ansibleclaw/cli.py`

The metadata is transformed into a template context. The core module variables plus AAP configuration (when configured) are passed to all Jinja2 templates:

```python
# cli.py
def _template_context(metadata):
    params = metadata["params"]
    example_args = _build_example_args(params, metadata.get("examples", ""))
    ctx = {
        "module_name": metadata["module_name"],
        "skill_name": _module_to_skill_name(metadata["module_name"]).replace("ansible_", ""),
        "short_description": metadata["short_description"],
        "params": params,
        "examples": metadata["examples"].strip() if metadata["examples"] else "",
        "example_args": example_args,
        "collection_fqcn": _collection_fqcn(metadata["module_name"]),
    }
    # AAP settings baked into generated skills when configured
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
    return ctx
```

### skill_name derivation

`_module_to_skill_name` extracts the short name from the FQCN:

```python
# cli.py
def _module_to_skill_name(module_name):
    short = module_name.rsplit(".", 1)[-1]   # "ansible.builtin.package" -> "package"
    return f"ansible_{short}"                 # -> "ansible_package"
```

Then `.replace("ansible_", "")` strips the prefix for the template: `skill_name = "package"`.

The `ansible_` prefix is used for the **directory name** (`ansible_package/`), while the bare `skill_name` is used **inside templates** (e.g., YAML frontmatter `name: ansible-package`, job template suggestion `package-deploy`).

### example_args derivation

`_build_example_args` creates a one-liner CLI example string like `"name=ntpdate state=present"`. It uses a two-step priority system:

**Step 1 -- Extract concrete values from YAML examples:**

```python
# cli.py
def _extract_example_values(examples_yaml):
    values = {}
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
```

From `"    name: ntpdate\n    state: present\n"`, this extracts `{"name": "ntpdate", "state": "present"}`.

**Step 2 -- Build the args string with a priority chain:**

For each **required** parameter:
1. Use the concrete value from examples (if found)
2. Use the first choice value (if parameter has choices)
3. Use `true` (if parameter is a boolean)
4. Fall back to a placeholder like `name=<name>`

If no required params exist, fall back to the first 2 params with defaults or placeholders.

```python
# cli.py
for p in params:
    if p["required"]:
        name = p["name"]
        if name in concrete:          # "name" -> "ntpdate" (from examples)
            parts.append(f"{name}={concrete[name]}")
        elif p["choices"]:            # "state" -> "present" (from examples, or first choice)
            parts.append(f"{name}={p['choices'][0]}")
        elif p["type"] == "bool":
            parts.append(f"{name}=true")
        else:
            parts.append(f"{name}=<{name}>")
```

### Result

For `ansible.builtin.package`, the final context is:

```python
{
    "module_name":        "ansible.builtin.package",
    "skill_name":         "package",
    "short_description":  "Generic OS package manager",
    "params":             [... 3 param dicts, required first ...],
    "examples":           "- name: Install ntpdate\n  ansible.builtin.package:\n    name: ntpdate\n    state: present",
    "example_args":       "name=ntpdate state=present",
}
```

---

## Phase 4: Render Templates and Write Files

**File:** `src/ansibleclaw/cli.py`

`_write_skill_package` renders 5 Jinja2 templates with the same context dict and writes the output files:

```python
# cli.py
def _write_skill_package(output_dir, metadata):
    env = _get_template_env()
    ctx = _template_context(metadata)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. SKILL.md
    skill_template = env.get_template(TEMPLATE_PATH.name)
    (output_dir / "SKILL.md").write_text(skill_template.render(**ctx))

    # 2-3. scripts/run.sh, scripts/check.sh
    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    for script_name in ("run.sh", "check.sh"):
        template = env.get_template(f"{script_name}.j2")
        script_path = scripts_dir / script_name
        script_path.write_text(template.render(**ctx))
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | ...)

    # 4. scripts/aap_run.py
    aap_template = env.get_template("aap_run.py.j2")
    aap_path = scripts_dir / "aap_run.py"
    aap_path.write_text(aap_template.render(**ctx))
    aap_path.chmod(aap_path.stat().st_mode | stat.S_IEXEC | ...)

    # 5. assets/playbook.yml
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    playbook_template = env.get_template("playbook.yml.j2")
    (assets_dir / "playbook.yml").write_text(playbook_template.render(**ctx))
```

### How each template uses the context

All 5 templates receive the same context variables (core module data + AAP settings). Each picks the ones it needs:

#### skill_template.md → SKILL.md

| Variable | Where it appears |
|----------|-----------------|
| `module_name` | Title, CLI examples, ad-hoc command body |
| `skill_name` | YAML frontmatter (`name: ansible-package`), "When to Use" prose, job template name |
| `short_description` | Frontmatter description, page subtitle |
| `params` | Parameters table (iterates with `{% for p in params %}`), choices section |
| `examples` | "Examples from Ansible Documentation" code block (conditionally included) |
| `example_args` | CLI quick examples, AAP ad-hoc examples |
| `collection_fqcn` | Collection requirement section |
| `aap_configured` | Controls Execution Mode routing: AAP vs CLI sections |
| `aap_url` | Baked into AAP mode settings table and check.sh |
| `aap_inventory` | Pre-fills ad-hoc and create-jt commands |
| `aap_credential` | Pre-fills ad-hoc and create-jt commands |
| `aap_project` | Pre-fills create-jt commands |
| `aap_ee` | Shown in AAP settings table |

The parameters table is generated by:

```jinja2
{% for p in params -%}
| `{{ p.name }}` | {{ p.type }} | {{ "yes" if p.required else "no" }} | {{ p.default if p.default is not none else "-" }} | {{ p.description | truncate(120) }} |
{% endfor %}
```

Which renders to:

```markdown
| `name` | str | yes | - | Package name, or package specifier with version. |
| `state` | str | yes | - | Whether to install (present), or remove (absent)... |
| `use` | str | no | auto | The required package manager module to use. |
```

#### run.sh.j2 → scripts/run.sh

| Variable | Where it appears |
|----------|-----------------|
| `module_name` | `MODULE="ansible.builtin.package"`, passed to `ansible -m $MODULE` |
| `example_args` | Help text examples |

#### check.sh.j2 → scripts/check.sh

| Variable | Where it appears |
|----------|-----------------|
| `module_name` | `MODULE="ansible.builtin.package"`, checked via `ansible-doc -t module $MODULE` |
| (derived) | Namespace parts split from `module_name` for collection detection |

The AAP section uses the baked URL (if available) or `AAP_CONTROLLER_URL` env var, then checks token, controller reachability via `/api/v2/ping/` (falls back to `/api/controller/v2/ping/`), and that `aap_run.py` exists.

#### aap_run.py.j2 → scripts/aap_run.py

| Variable | Where it appears |
|----------|-----------------|
| `module_name` | `MODULE = "ansible.builtin.package"` (baked into the script) |
| `skill_name` | Default playbook path in `create-jt` subcommand |
| `short_description` | argparse help text |
| `aap_url` | `_BAKED_URL` fallback default |
| `aap_verify_ssl` | `_BAKED_VERIFY_SSL` fallback default |
| `aap_inventory` | `_BAKED_INVENTORY` fallback default |
| `aap_credential` | `_BAKED_CREDENTIAL` fallback default |
| `aap_project` | `_BAKED_PROJECT` fallback default |
| `aap_organization` | `_BAKED_ORGANIZATION` fallback default |
| `aap_ee` | `_BAKED_EE` fallback default |

The `_cfg()` function resolves: env var > baked value > error. The token is never baked (always from `AAP_CONTROLLER_TOKEN` env var).

Subcommands: `adhoc`, `launch`, `create-jt`, and `status`.

The module name is baked in so the agent only needs to provide module **arguments**, not the module name itself: `aap_run.py adhoc "name=nginx state=present"`.

#### playbook.yml.j2 → assets/playbook.yml

| Variable | Where it appears |
|----------|-----------------|
| `short_description` | Play name: `- name: "Generic OS package manager"` |
| `module_name` | Task module reference (fallback path only) |
| `examples` | If present, used verbatim as the tasks list |
| `params` | If no examples, generates placeholder tasks from required params |

The template logic:

```jinja2
{% if examples %}
{{ examples | indent(4, first=true) }}
{% else %}
    - name: "Run {{ module_name }}"
      {{ module_name }}:
{% for p in params %}
{% if p.required %}
        {{ p.name }}: "CHANGEME"
{% endif %}
{% endfor %}
{% endif %}
```

If `ansible-doc` provides examples (most modules do), they're used directly -- giving you real-world tasks. Otherwise, the fallback generates a minimal task with `CHANGEME` placeholders.

---

## Complete Data Flow

```
ansibleclaw generate "ansible.builtin.package"
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  Phase 1: SCRAPE                                         │
│  subprocess: ansible-doc ansible.builtin.package --json  │
│  returns: raw JSON blob from Ansible                     │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│  Phase 2: EXTRACT                                        │
│  extract_module_metadata(doc) →                          │
│    ├── module_name:        "ansible.builtin.package"     │
│    ├── short_description:  "Generic OS package manager"  │
│    ├── params:             [{name, type, required, ...}] │
│    └── examples:           "- name: Install ntpdate..."  │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│  Phase 3: CONTEXT                                        │
│  _template_context(metadata) →                           │
│    ├── module_name:        (pass through)                │
│    ├── skill_name:         "package"                     │
│    ├── short_description:  (pass through)                │
│    ├── params:             (pass through)                │
│    ├── examples:           (stripped whitespace)          │
│    └── example_args:       "name=ntpdate state=present"  │
│         ▲                                                │
│         └── _build_example_args()                        │
│              ├── _extract_example_values(yaml)            │
│              │    → {"name":"ntpdate","state":"present"}  │
│              └── match required params → concrete values  │
└────────────────────────┬─────────────────────────────────┘
                         │
          ┌──────────────┼────────────┬──────────────┬──────────────┐
          ▼              ▼            ▼              ▼              ▼
   skill_template.md  run.sh.j2  check.sh.j2  aap_run.py.j2  playbook.yml.j2
          │              │            │              │              │
          ▼              ▼            ▼              ▼              ▼
       SKILL.md       run.sh     check.sh      aap_run.py    playbook.yml
```

---

## Output Directory Routing

The final output directory is determined by CLI flags:

```python
# cli.py
def _resolve_output_dir(args, skill_name):
    if args.install:           # --install cursor  → ~/.cursor/skills/ansible_package/
        return INSTALL_PATHS[platform] / skill_name
    elif args.output:          # --output /tmp/     → /tmp/ansible_package/
        return Path(args.output) / skill_name
    else:                      # default            → ./skills/ansible_package/
        return SKILLS_DIR / skill_name
```

| Command | Output Path |
|---------|------------|
| `ansibleclaw generate "ansible.builtin.package"` | `./skills/ansible_package/` |
| `ansibleclaw generate "ansible.builtin.package" --install cursor` | `~/.cursor/skills/ansible_package/` |
| `ansibleclaw generate "ansible.builtin.package" --install claude` | `~/.claude/skills/ansible_package/` |
| `ansibleclaw generate "ansible.builtin.package" --output /tmp/` | `/tmp/ansible_package/` |

---

## Key Source Files

| File | Role |
|------|------|
| `src/ansibleclaw/cli.py` | CLI entrypoint, template context builder, package writer |
| `src/ansibleclaw/core/parser.py` | `ansible-doc` subprocess wrapper, metadata extraction |
| `src/ansibleclaw/config.py` | Paths (templates, skills dir, install targets), AAP env vars |
| `src/ansibleclaw/templates/skill_template.md` | Jinja2 template for SKILL.md (dual-mode: CLI + AAP) |
| `src/ansibleclaw/templates/run.sh.j2` | Jinja2 template for CLI wrapper script |
| `src/ansibleclaw/templates/check.sh.j2` | Jinja2 template for prerequisite checker (CLI + AAP) |
| `src/ansibleclaw/templates/aap_run.py.j2` | Jinja2 template for AAP Controller API helper |
| `src/ansibleclaw/templates/playbook.yml.j2` | Jinja2 template for Ansible playbook |
| `tests/conftest.py` | Sample `ansible-doc` JSON fixture for testing |
| `tests/test_template.py` | Template rendering tests (including AAP sections) |
| `tests/test_cli.py` | End-to-end generation tests |
