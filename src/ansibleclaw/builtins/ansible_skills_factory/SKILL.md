---
name: ansible-skills-factory
description: >-
  Generate specialized SKILL.md files for Ansible modules on-demand using ansibleclaw generate.
  Use when you encounter a complex module and need a dedicated skill with full parameter docs,
  usage examples, and safety guidance. Requires ansibleclaw to be installed.
---

# Ansible Skills Factory

Generate rich, specialized SKILL.md files for any Ansible module by scraping its `ansible-doc`
documentation. The generated skill is immediately usable by AI agents.

## Prerequisites

This skill requires `ansibleclaw` to be installed:

```bash
pip install ansibleclaw
```

The other built-in skills (ansible_manager, ansible_search) only require `ansible-core`.

## When to Generate a Skill

Generate a dedicated skill when:

- A module has **complex parameters** you want documented in a structured way
- You will **reuse the module frequently** and want a quick reference
- You want **tailored examples** adapted to the `ansible` CLI format
- The `ansible_search` skill shows a module you haven't used before

Do **not** generate a skill for:

- Simple modules you can use directly via `ansible_manager` (e.g., `ansible.builtin.ping`)
- Modules you will only use once

## Usage

### Generate into the project skills directory (default)

```bash
ansibleclaw generate "community.general.redis"
```

Output: `skills/ansible_redis/SKILL.md` -- immediately available in the project.

### Install directly into an AI agent

```bash
ansibleclaw generate "community.general.redis" --install cursor
ansibleclaw generate "community.general.redis" --install claude
```

This writes to `~/.cursor/skills/ansible_redis/SKILL.md` or `~/.claude/skills/ansible_redis/SKILL.md`.

### Custom output path

```bash
ansibleclaw generate "community.general.redis" --output /path/to/skills/
```

## The Self-Expansion Workflow

1. **Search**: Find the right module
   ```bash
   ansible-doc --list community.general | grep redis
   ```

2. **Generate**: Create a specialized skill
   ```bash
   ansibleclaw generate "community.general.redis"
   ```

3. **Read**: The CLI prints the output path -- read the generated SKILL.md for parameter guidance

4. **Use**: Open the generated SKILL.md and follow **Execution Mode -- READ THIS FIRST** at the top: use `scripts/aap_run.py` when **AAP mode** is active (do **not** use `scripts/run.sh` for AAP — it is CLI-only); otherwise use local `ansible` / `ansible-playbook` as described in the **How to Execute (CLI)** section.

## What Gets Generated

Each generated skill package contains:

```
skills/ansible_redis/
  SKILL.md              # Dual-mode: CLI (local + file inventory) or AAP (Controller + Controller inventory)
  scripts/
    run.sh              # Local CLI wrapper (not for AAP mode)
    check.sh            # Prerequisite checks (CLI + AAP)
    aap_run.py          # AAP Controller API helper (Python stdlib only)
  assets/
    playbook.yml        # Playbook for ansible-playbook
```

The SKILL.md includes:

- **YAML frontmatter** with name and description for agent auto-discovery
- **Execution Mode** routing block (AAP or CLI) -- READ THIS FIRST section at the top
- **Parameters table** with type, required, default, choices, and description
- **How to Execute (AAP)** section with `aap_run.py` commands when AAP is configured: **Job Template first** (create-jt, launch, status), **ad-hoc demoted** as optional, with pre-filled defaults
- **How to Execute (CLI)** section with `ansible` CLI examples, inventory options, and JSON output when in CLI mode
- **Safety guidance** (dry-run, become, idempotency)

### Execution Mode Routing

Generated skills have an **Execution Mode** section at the top that directs you to the correct path:

- **AAP mode** (production, when configured): Execution goes through `scripts/aap_run.py` against Ansible Automation Platform. **Do not use `scripts/run.sh`** in this mode — it invokes local `ansible` only. **Inventory is managed in AAP** (inventories, groups, and sources in the Controller UI or API)—not from static files under the repo’s `inventory/` directory. The SKILL.md lists pre-filled Controller settings (URL, default AAP inventory name or ID, credential, project). The `aap_run.py` script ships with baked defaults -- only `AAP_CONTROLLER_TOKEN` env var is required.
- **CLI mode** (default, local/dev): Direct `ansible` commands with **file-based inventory** (`ansible.cfg`, `-i`, or `ANSIBLE_INVENTORY`) or ad hoc host lists. **AAP production → Controller inventory; CLI / local dev → file inventory** (project path or explicit path).

The `scripts/aap_run.py` helper uses only Python stdlib (`urllib` + `json`) -- no extra pip install needed. Subcommands: `adhoc`, `launch`, `create-jt`, `status`.
See the `ansible_aap_guide` skill for full AAP setup instructions.

## Composing Multi-Module Skills

When a task requires **multiple modules** working together, use `ansibleclaw compose` to generate a **single unified skill** with a combined playbook, shared scripts, and documentation for all modules.

### When to compose (vs. generating individually)

Compose when:

- The task requires **multiple modules in sequence** (e.g., install package, copy config, start service)
- Modules come from **different collections** but serve one workflow
- You want a **single playbook** the agent can customize and run

Generate individually when:

- You need a standalone reference for one module
- The modules are unrelated

### Compose from the command line

```bash
ansibleclaw compose --name "web-server-setup" \
  --modules ansible.builtin.package,ansible.builtin.template,ansible.builtin.service,ansible.posix.firewalld \
  --description "Deploy and configure a web server with firewall rules"
```

Output: `skills/ansible_web_server_setup/` with a multi-task playbook covering all four modules.

### Install directly into an AI agent

```bash
ansibleclaw compose --name "docker-stack" \
  --modules community.docker.docker_network,community.docker.docker_volume,community.docker.docker_container \
  --install cursor
```

### Compose from a recipe file

Create a `recipe.yml`:

```yaml
name: web-server-setup
description: Deploy and configure Nginx with firewall rules
modules:
  - name: ansible.builtin.package
    vars:
      name: nginx
      state: present
  - name: ansible.builtin.template
    vars:
      src: templates/nginx.conf.j2
      dest: /etc/nginx/nginx.conf
  - name: ansible.builtin.service
    vars:
      name: nginx
      state: started
      enabled: true
```

Then generate:

```bash
ansibleclaw compose -f recipe.yml
```

When `vars` are provided in the recipe, the generated playbook pre-fills those values instead of placeholders.

### What gets generated (composite)

```
skills/ansible_web_server_setup/
  SKILL.md              # Dual-mode docs for all modules combined
  scripts/
    run.sh              # Playbook runner (ansible-playbook wrapper)
    check.sh            # Validates all modules and collections
    publish_playbook.sh # AAP Project push
    aap_run.py          # AAP helper (Job Template oriented, no ad-hoc)
  assets/
    playbook.yml        # Multi-task playbook with all modules
    requirements.yml    # Union of all collection dependencies
```

### The compose workflow

1. **Identify** the modules needed for the task (use `ansible_search` skill or `ansibleclaw search`)
2. **Compose**: `ansibleclaw compose --name "my-workflow" --modules mod1,mod2,mod3`
3. **Read**: Open the generated SKILL.md and follow the Execution Mode section
4. **Customize**: Edit `assets/playbook.yml` to fill in site-specific values
5. **Execute**: Use `scripts/run.sh` (CLI) or `scripts/aap_run.py` (AAP)

## Batch Generation

Generate multiple individual skills at once:

```bash
for module in community.general.redis community.docker.docker_container community.mysql.mysql_db; do
    ansibleclaw generate "$module"
done
```
