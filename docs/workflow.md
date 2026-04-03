# AnsibleClaw workflow diagrams

**Stakeholder-friendly view:** [Business view: personas and outcomes](#business-view-personas-and-outcomes). **Technical detail:** diagrams further down mirror `src/ansibleclaw/`.

---

## Business view: personas and outcomes

From a **business owner** perspective, the goal is not “run a generator” — it is **faster, safer change** with **clear ownership**: who defines standard work, who governs production, and how everyday questions get answers that match policy.

**AnsibleClaw** sits between **your Ansible practice** and **the AI tools people already use**. It does not replace people or Ansible Automation Platform (AAP); it connects them by packaging **approved automation know-how** into **skills** the **AI agent** is instructed to follow.

### Who is usually in the picture

| Persona | Typical concern | Role with AnsibleClaw |
|--------|-----------------|------------------------|
| **Business owner** | Risk, speed, compliance, cost of mistakes | Sets expectations: production changes must be traceable; experiments may be looser. Does not operate the tools day to day. |
| **Ansible admin** | Correct playbooks, modules, collections, inventory truth | Chooses what to turn into skills, generates and reviews packages, keeps content aligned with how Ansible is actually used. |
| **AAP admin** | Who may run what, on which inventory, with which credentials | Owns Controller setup, RBAC, job templates, audit. Skills can point to AAP for **governed** execution when this role has configured it. |
| **AI agent** | (Product behavior, not a human job title) | Reads skills and responds to users using **your** steps and terminology — not a random web article. |
| **Knowledge worker** | “I need X done on the servers” | Asks in plain language; still subject to the same gates Ansible/AAP admins defined. |

### How the personas connect (one picture)

```mermaid
flowchart TB
  subgraph owner ["Business owner"]
    O1["Sets priorities:\nstandardization, safety, audit"]
    O2["Does not pick modules or\nclick buttons in AAP day to day"]
  end

  subgraph ansibleRole ["Ansible admin"]
    A1["Owns automation content:\nplaybooks, modules, standards"]
    A2["Uses AnsibleClaw to build & refresh\n'skills' from that content"]
    A3["Shares skills with the org\n(repo, ZIP, assistant config)"]
  end

  subgraph aapRole ["AAP admin"]
    P1["Owns production platform:\naccess, inventories, credentials"]
    P2["Defines what 'production run'\nmeans in your company"]
    P3["Optional: job templates & policies\nskills can reference"]
  end

  subgraph digital ["AI agent + employees"]
    AI["AI agent\nreads skills, proposes steps\nin plain language"]
    U["Knowledge workers\nask questions, request changes"]
    U --> AI
  end

  owner -.->|"expectations"| ansibleRole
  owner -.->|"governance goals"| aapRole
  ansibleRole -->|"approved know-how"| AI
  aapRole -->|"when to use Controller\nvs local try-out"| AI
  A2 --> A3
```

Solid arrows are **handoffs of rules or content**. Dotted lines are **accountability / expectations**, not file transfers.

### Typical story (sequence)

```mermaid
sequenceDiagram
  participant BO as Business owner
  participant AA as Ansible admin
  participant AAP as AAP admin
  participant KW as Knowledge worker
  participant AI as AI agent

  Note over BO: Fewer ad-hoc fixes; clearer audit for production

  BO->>AA: Prioritize standard tasks (patching, baselines, …)
  BO->>AAP: Governed execution for production

  AA->>AA: Build or update Ansible content
  AA->>AA: Generate skills with AnsibleClaw (review)
  AA->>AI: Publish skills for org-approved guidance

  AAP->>AAP: Inventories, credentials, RBAC, job templates
  Note over AAP: Skills describe when to use Controller

  KW->>AI: Plain-language request (e.g. install X on group Y)
  AI->>KW: Steps from skill (try-out vs AAP per policy)
  Note over KW,AI: Production still follows AAP rules
```

**In one sentence for executives:** AnsibleClaw lets the **Ansible admin** publish **trusted automation guidance** the **AI agent** follows, while the **AAP admin** keeps **production** under **platform control** — so **knowledge workers** move faster without bypassing **how the business said work should be done**.

---

## Technical: entry points to skill package

Diagram below reflects the implementation under `src/ansibleclaw/` (CLI, `core/parser.py`, `core/galaxy.py`, `core/packager.py`, `config.AAPSettings`, and `web/app.py`).

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
