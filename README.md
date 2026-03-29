# AnsibleClaw

A skill generation framework that converts Ansible modules into portable AI agent skill packages.

## Overview

AnsibleClaw bridges Ansible's 3000+ modules to AI agents (Cursor, Claude Code, etc.) by generating full skill packages from `ansible-doc` documentation. Each package includes a SKILL.md, wrapper scripts, prerequisite checks, and a ready-to-use playbook. Generated skills only depend on `ansible-core` at runtime -- no custom package needed.

**Build-time** -- Run `ansibleclaw` to scrape Ansible module docs and generate skill packages.
**Runtime** -- Generated skills teach AI agents standard `ansible` CLI commands. Only `ansible-core` required.

## Installation

```bash
# Install from PyPI
pip install ansible-claw

# Install with web dashboard
pip install "ansible-claw[ui]"

# Or install from source for development
pip install -e ".[ui,dev]"
```

## Quick Start

```bash

# Search for modules
ansibleclaw search "redis"
ansibleclaw search "container" --namespace community.docker

# Generate a skill package
ansibleclaw generate "ansible.builtin.apt"

# Generate and create a distributable ZIP
ansibleclaw generate "ansible.builtin.apt" --zip

# Generate and install directly into Cursor
ansibleclaw generate "community.general.redis" --install cursor

# Generate and install directly into Claude Code
ansibleclaw generate "community.docker.docker_container" --install claude

# Launch the web dashboard
ansibleclaw ui
```

## How It Works

1. **Search** -- Find the right Ansible module with `ansibleclaw search` or the `ansible_search` skill
2. **Generate** -- Convert a module into a full skill package with `ansibleclaw generate`
3. **Use** -- The AI agent reads the SKILL.md and runs standard `ansible` CLI commands
4. **Distribute** -- Download as ZIP from the web dashboard or use `--zip` on the CLI

Generated skills are portable: copy them into `~/.cursor/skills/`, `~/.claude/skills/`, or any agent's skill directory. ZIP packages can be uploaded directly to Claude.ai or shared via agentskill.sh. They work anywhere `ansible-core` is installed.

## Generated Skill Package

Each generated skill is a complete [Agent Skills](https://agentskill.sh/readme) package with dual-mode execution (CLI + AAP):

```
ansible_apt/
├── SKILL.md              # Main instructions (CLI + AAP dual-mode)
├── scripts/
│   ├── run.sh            # CLI wrapper (dry-run by default, --apply to execute)
│   ├── check.sh          # Prerequisite validator (CLI + AAP connectivity)
│   └── aap_run.py        # AAP Controller API helper (Python stdlib only)
└── assets/
    └── playbook.yml      # Ready-to-use Ansible playbook
```

| File | Purpose | Dependency |
|------|---------|------------|
| `SKILL.md` | Agent reads this to learn module parameters, CLI usage, and AAP API usage | None |
| `scripts/run.sh` | Wraps `ansible` CLI with sane defaults and safe dry-run mode | `ansible-core` |
| `scripts/check.sh` | Validates CLI and AAP prerequisites | `ansible-core`, `curl` |
| `scripts/aap_run.py` | Launches ad-hoc commands and job templates via AAP Controller API | Python 3 (stdlib) |
| `assets/playbook.yml` | Ansible playbook with example tasks for the module | `ansible-core` |

## CLI Reference

### `ansibleclaw generate`

Generate a full skill package for any Ansible module.

```bash
ansibleclaw generate <module> [--install PLATFORM] [--output DIR] [--zip]
```

| Option | Description |
|--------|-------------|
| `module` | Fully-qualified module name (e.g., `ansible.builtin.apt`) |
| `--install` | Install directly to `cursor` or `claude` |
| `--output` | Write to a custom directory |
| `--zip` | Also create a `.zip` archive for distribution |

```bash
# Default: writes full package to skills/ansible_apt/
ansibleclaw generate "ansible.builtin.apt"

# Generate + create distributable ZIP
ansibleclaw generate "ansible.builtin.apt" --zip

# Install to Cursor: writes to ~/.cursor/skills/ansible_redis/
ansibleclaw generate "community.general.redis" --install cursor

# Custom path
ansibleclaw generate "ansible.builtin.user" --output /tmp/my-skills/

# Batch generate with ZIP
for module in ansible.builtin.apt ansible.builtin.systemd community.docker.docker_container; do
    ansibleclaw generate "$module" --install cursor --zip
done
```

### `ansibleclaw search`

Search for Ansible modules by keyword.

```bash
ansibleclaw search [keyword] [--namespace NS] [--detail MODULE]
```

| Option | Description |
|--------|-------------|
| `keyword` | Search term to match against module names and descriptions |
| `--namespace`, `-n` | Filter to a namespace (e.g., `community.docker`) |
| `--detail` | Show full JSON documentation for a module |

```bash
ansibleclaw search "redis"
ansibleclaw search "container" -n community.docker
ansibleclaw search --namespace ansible.builtin
ansibleclaw search --detail "community.general.redis"
```

### `ansibleclaw ui`

Launch the web management dashboard.

```bash
ansibleclaw ui [--port PORT]
```

Starts at `http://localhost:8600` by default. Requires `pip install "ansible-claw[ui]"`.

## Web Dashboard

Start with `ansibleclaw ui` and open `http://localhost:8600`.

**Skills Library** (`/skills`) -- View all skills (built-in + generated), click to read SKILL.md content, download as ZIP, delete generated skills, or install to Cursor/Claude with one click.

**Module Search** (`/search`) -- Search Ansible modules by keyword and namespace. View module parameters and examples inline. Jump to the generator from any result.

**Skill Generator** (`/generate`) -- Enter a module name, preview the generated SKILL.md in real time, choose a target (project / Cursor / Claude / custom path), and generate a full skill package. Download as ZIP from the success message.

## Built-In Skills

These ship inside the `ansible-claw` package and are always available -- no repo checkout needed.

| Skill | Purpose | Runtime Dependency |
|-------|---------|-------------------|
| `ansible_manager` | Teaches AI to run any Ansible module via CLI or AAP | `ansible-core` |
| `ansible_search` | Teaches AI to discover modules via `ansible-doc` | `ansible-core` |
| `ansible_skills_factory` | Teaches AI to generate new dual-mode skills on-demand | `ansibleclaw` |
| `ansible_aap_guide` | Teaches AI how to use AAP as the production execution platform | Python 3 (stdlib) |

## Dependencies

| Context | Install command |
|---------|----------------|
| Core CLI | `pip install ansible-claw` |
| With web dashboard | `pip install "ansible-claw[ui]"` |
| With dev tools | `pip install "ansible-claw[dev]"` |
| Runtime (on target) | `ansible-core` only |

## AAP Integration (Production Execution)

Generated skills include dual-mode execution: local CLI for development/testing, and AAP Controller API for governed production runs. Set these environment variables to enable AAP mode:

| Variable | Required | Description |
|----------|----------|-------------|
| `AAP_CONTROLLER_URL` | yes | Base URL of the AAP/AWX controller |
| `AAP_CONTROLLER_TOKEN` | yes | OAuth2 bearer token |
| `AAP_VERIFY_SSL` | no | Set to `false` for self-signed certs (default: `true`) |
| `AAP_DEFAULT_INVENTORY` | no | Default inventory name or ID |
| `AAP_DEFAULT_CREDENTIAL` | no | Default credential name or ID |
| `AAP_DEFAULT_ORGANIZATION` | no | Organization name (default: `Default`) |

When these are set, each skill's `scripts/aap_run.py` can execute modules through AAP:

```bash
# Ad-hoc command via AAP
python3 scripts/aap_run.py adhoc "name=nginx state=present" --inventory Production --credential "SSH Key"

# Launch a job template
python3 scripts/aap_run.py launch "deploy-webservers" --extra-vars '{"version": "2.0"}'
```

Compatible with both AWX (free upstream) and Red Hat AAP Controller (commercial).

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `ANSIBLECLAW_SKILLS_DIR` | `./skills/` (CWD) | Where generated skills are written |

## Project Structure

```
AnsibleClaw/
├── src/ansibleclaw/           # Python package (pip install ansible-claw)
│   ├── cli.py                 # CLI: generate / search / ui
│   ├── config.py              # Configuration + paths
│   ├── core/
│   │   ├── parser.py          # ansible-doc scraping + extraction
│   │   └── packager.py        # ZIP packaging for skill distribution
│   ├── builtins/              # Built-in skills (shipped in wheel)
│   │   ├── ansible_manager/   # General-purpose Ansible executor (CLI + AAP)
│   │   ├── ansible_search/    # Module discovery via ansible-doc
│   │   ├── ansible_skills_factory/  # On-demand skill generation
│   │   └── ansible_aap_guide/ # AAP integration guide
│   ├── templates/             # Jinja2 skill blueprints (shipped in wheel)
│   │   ├── skill_template.md  # SKILL.md template (dual-mode: CLI + AAP)
│   │   ├── run.sh.j2          # CLI wrapper script template
│   │   ├── check.sh.j2        # Prerequisite checker template (CLI + AAP)
│   │   ├── aap_run.py.j2      # AAP Controller API helper template
│   │   └── playbook.yml.j2    # Ansible playbook template
│   └── web/                   # Optional web dashboard (FastAPI + HTMX)
│       ├── app.py             # Routes (including ZIP download)
│       ├── templates/         # Jinja2 HTML templates (Pico CSS)
│       └── static/            # CSS (dark/light themes)
├── skills/                    # Generated skills (user output, CWD-based)
├── tests/                     # Test suite
├── docs/                      # Documentation
│   └── user-guide.md          # Comprehensive user guide
├── pyproject.toml             # Package definition (ansible-claw on PyPI)
└── README.md
```

## Documentation

See [docs/user-guide.md](docs/user-guide.md) for the comprehensive user guide covering CLI usage, web dashboard walkthrough, end-to-end workflows, inventory setup, and troubleshooting.

## License

Apache License 2.0 -- see [LICENSE](LICENSE) for details.
