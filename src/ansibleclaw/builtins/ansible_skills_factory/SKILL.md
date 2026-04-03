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

4. **Use**: Execute the module using the `ansible` CLI as documented in the new skill

## What Gets Generated

Each generated skill package contains:

```
skills/ansible_redis/
  SKILL.md              # Dual-mode: CLI + AAP sections
  scripts/
    run.sh              # Local CLI wrapper
    check.sh            # Prerequisite checks (CLI + AAP)
    aap_run.py          # AAP Controller API helper (Python stdlib only)
  assets/
    playbook.yml        # Playbook for ansible-playbook
```

The SKILL.md includes:

- **YAML frontmatter** with name and description for agent auto-discovery
- **Execution Mode** routing block (AAP or CLI) -- READ THIS FIRST section at the top
- **Parameters table** with type, required, default, choices, and description
- **How to Execute (AAP)** section with `aap_run.py` commands (adhoc, launch, create-jt, status) when AAP is configured, with pre-filled defaults
- **How to Execute (CLI)** section with `ansible` CLI examples, inventory options, and JSON output when in CLI mode
- **Safety guidance** (dry-run, become, idempotency)

### Execution Mode Routing

Generated skills have an **Execution Mode** section at the top that directs you to the correct path:

- **AAP mode** (when configured): The SKILL.md contains pre-filled AAP settings (URL, inventory, credential, project) and imperative instructions to use `scripts/aap_run.py`. The `aap_run.py` script ships with baked defaults -- only `AAP_CONTROLLER_TOKEN` env var is required.
- **CLI mode** (default): Direct `ansible` commands for development and testing

The `scripts/aap_run.py` helper uses only Python stdlib (`urllib` + `json`) -- no extra pip install needed. Subcommands: `adhoc`, `launch`, `create-jt`, `status`.
See the `ansible_aap_guide` skill for full AAP setup instructions.

## Batch Generation

Generate multiple skills at once:

```bash
for module in community.general.redis community.docker.docker_container community.mysql.mysql_db; do
    ansibleclaw generate "$module"
done
```
