# AnsibleClaw workflow diagrams

These diagrams reflect the current implementation under `src/ansibleclaw/` (CLI, `core/parser.py`, `core/galaxy.py`, `core/packager.py`, `config.AAPSettings`, and `web/app.py`).

## End-to-end: entry points to skill package

```mermaid
flowchart TB
  subgraph actors ["Who drives it"]
    OP["Operator or AI agent"]
  end

  subgraph entry ["Entry points"]
    CLI["ansibleclaw CLI\n(generate | search | ui)"]
    WEB["Web UI\nFastAPI app.py"]
  end

  OP --> CLI
  OP --> WEB

  CLI -->|search| SRCH["parser.search_modules\nansible-doc --list --json + filter"]
  SRCH --> OUTLIST[("Module names + short descriptions")]

  CLI -->|ui| UI["Uvicorn: /skills, /search,\n/generate, /collections, /aap"]
  WEB --> UI

  CLI -->|generate| GENSTART["generate: single module\nor --collection"]
  WEB -->|preview / generate| GENSTART

  GENSTART -->|per module| RESOLVE["parser.resolve_module_doc"]

  RESOLVE --> META["extract_module_metadata\n(params, examples, description)"]
  META --> CTX["_template_context\nAAPSettings: env then .ansibleclaw.yml\n(token presence → aap_configured;\ndefaults baked, not token)"]
  CTX --> RENDER["Jinja2 templates in templates/\n→ SKILL.md, scripts/*, assets/*"]
  RENDER --> PKG["Skill directory\nSKILL.md, run.sh, check.sh,\naap_run.py, playbook.yml\n+ requirements.yml if non-builtin"]

  PKG --> DEST{Destination}
  DEST -->|default| SKDIR["ANSIBLECLAW_SKILLS_DIR\n(./skills/)"]
  DEST -->|--install| AGDIR["~/.cursor/skills/\nor ~/.claude/skills/"]
  DEST -->|--output| CUST["Custom path"]
  CLI -->|optional --zip| ZIP["packager.package_skill_zip\n.zip archive"]
  PKG --> ZIP
  WEB -->|download| ZIP
```

## Module documentation resolution

```mermaid
flowchart TD
  R["resolve_module_doc(module_name,\nauto_install, collection_version)"]
  R --> L{"ansible-doc MODULE --json\nsucceeds?"}
  L -->|yes| LOC["Return doc + doc_source: local"]
  L -->|no| A{"auto_install?"}
  A -->|yes| GI["install_collection\nansible-galaxy collection install"]
  GI --> L2{"ansible-doc succeeds\nafter install?"}
  L2 -->|yes| LOC
  L2 -->|no| G["GalaxyDocProvider.fetch_module_doc\nGalaxy REST API"]
  A -->|no| G
  G --> GAL["Return doc + doc_source: galaxy\n+ version / warning metadata"]
```

Collection-wide generation (`ansibleclaw generate --collection`) first calls `list_modules(namespace)`, then runs the same `resolve_module_doc` → `_write_skill_package` path for each selected module. A separate path builds a **collection overview** skill via `collection_skill_template.md` plus `requirements.yml` only (no per-module scripts).

## Runtime: how an agent uses a generated skill

```mermaid
flowchart TB
  subgraph agentSide ["Where the AI runs"]
    AG["AI agent reads SKILL.md"]
  end

  subgraph cliMode ["CLI mode (dev / direct control)"]
    RUN["scripts/run.sh\nor raw ansible / ansible-playbook"]
    RUN --> AC["ansible-core\non control node"]
    AC --> SSH["SSH / connection plugins"]
    SSH --> H1[("Managed hosts")]
  end

  subgraph aapMode ["AAP mode (production / governed)"]
    AAP["scripts/aap_run.py\nPython 3 stdlib only"]
    AAP --> ENV["AAP_CONTROLLER_URL\nAAP_CONTROLLER_TOKEN\n(+ optional env overrides)"]
    AAP --> API["Controller REST API\n/api/v2 or /api/controller/v2"]
    API --> EE["Execution environment"]
    EE --> H2[("Managed hosts")]
  end

  AG -->|Execution Mode in SKILL| CHOICE{"AAP configured\nand policy says AAP?"}
  CHOICE -->|CLI| RUN
  CHOICE -->|AAP| AAP

  CHK["scripts/check.sh"] --> AC
  CHK --> API
```

`check.sh` validates `ansible` / inventory assumptions when present and, if `AAP_CONTROLLER_URL` is set, pings the Controller (using `AAP_CONTROLLER_TOKEN` for auth).

## Web dashboard and AAP deploy (optional)

```mermaid
flowchart LR
  UI["Browser"] --> APP["app.py routes"]
  APP --> S["List / read skills\nbuilt-ins + generated"]
  APP --> M["Search modules\nHTMX partials"]
  APP --> G["Generate + preview\nsame parser + templates as CLI"]
  APP --> C["Collections manager\ngalaxy install / list"]
  APP --> A["AAP settings + ping\nAAPSettings"]
  APP --> D{"AAP URL + token set?"}
  D -->|yes| JT["Deploy to AAP:\ncreate Job Templates\nvia Controller API"]
  D -->|no| FORMS["Deploy UI disabled\nor shows setup hints"]
```

For a concise historical variant of the build vs runtime split, see also [design.md](../design.md) in the repository root.
