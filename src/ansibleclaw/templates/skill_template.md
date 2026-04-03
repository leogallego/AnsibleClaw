---
name: ansible-{{ skill_name | replace('_', '-') }}
description: >-
  {{ short_description }}
  Use when managing {{ skill_name | replace('_', ' ') }} resources on remote hosts via Ansible.
---

# {{ module_name }}

{{ short_description }}
{% if doc_warning is defined and doc_warning %}

> **Note**: {{ doc_warning }}
{% endif %}

## Execution Mode -- READ THIS FIRST
{% if aap_configured %}

**AAP mode is active.** You MUST use `scripts/aap_run.py` (located next to this
SKILL.md) for ALL execution. Do NOT run local `ansible` CLI commands or
`scripts/run.sh` — that wrapper invokes the local `ansible` CLI only, not AAP.

| Setting | Value |
|---------|-------|
| AAP Controller | `{{ aap_url }}` |
| Default AAP inventory | `{{ aap_inventory }}` |
| Default Credential | `{{ aap_credential }}` |
| Default Project | `{{ aap_project }}` |
{% if aap_ee %}| Default EE | `{{ aap_ee }}` |
{% endif %}

The **Default AAP inventory** value is a **Controller inventory** (name or numeric ID) defined and maintained in Ansible Automation Platform, not a path to a local file such as `inventory/hosts.yml`.

**IMPORTANT**: The environment variable `AAP_CONTROLLER_TOKEN` MUST be set
before running any command. All other AAP settings are pre-configured.

### Inventory (production)

Hosts and groups for AAP runs come from **inventories managed in AAP** (UI or API). Do not rely on the repo’s static `inventory/` files for production execution. The `--inventory` flag on `aap_run.py` selects **another AAP inventory** (name or ID), not a path on disk.

### Quick Start (FOLLOW THESE STEPS EXACTLY)

**Preferred path: Job Templates** (repeatable, RBAC-friendly, typical production flow).

1. **Check prerequisites**:
   ```bash
   bash scripts/check.sh
   ```

2. **Prepare `assets/playbook.yml`** — edit tasks to use `{{ module_name }}` with the parameters you need. The Job Template references this path **inside your AAP Project’s Git repo**; changes must be **pushed** and the project **synced** in AAP before launch (or use AnsibleClaw **Deploy to AAP** in the web UI).

3. **Create a Job Template** (skip if it already exists):
   ```bash
   python3 scripts/aap_run.py create-jt --name "{{ skill_name | replace('_', '-') }}"
   ```
   Use your site’s Job Template naming convention if a prefix is configured (e.g. `AnsibleClaw: …`).

4. **Launch the Job Template**:
   ```bash
   python3 scripts/aap_run.py launch "{{ skill_name | replace('_', '-') }}"
   ```
   Add `--limit`, `--inventory`, or `--extra-vars` as needed (see **How to Execute (AAP)** below).

5. **Check job status** (optional):
   ```bash
   python3 scripts/aap_run.py status <job-id>
   ```

#### Optional: ad-hoc (one-off, no playbook)

Use only for quick probes or debugging — **not** the default production path:

```bash
python3 scripts/aap_run.py adhoc "{{ example_args }}" --check
python3 scripts/aap_run.py adhoc "{{ example_args }}"
```
{% else %}

**CLI mode is active.** Use local `ansible` commands to execute this module.
To enable AAP mode, set `AAP_CONTROLLER_URL` and `AAP_CONTROLLER_TOKEN`.
{% endif %}
{% if collection_fqcn %}

## Collection Requirement

This module requires the `{{ collection_fqcn }}` collection.
{% if aap_configured %}

In AAP mode, collections are bundled into Execution Environments (EEs).
Ensure your EE includes `{{ collection_fqcn }}`. If not, update your
`execution-environment.yml` and rebuild:

```yaml
dependencies:
  galaxy:
    collections:
      - name: {{ collection_fqcn }}
```
{% else %}

Install it locally:

```bash
ansible-galaxy collection install {{ collection_fqcn }}
```
{% endif %}
{% endif %}

## When to Use This Skill

Use the `{{ module_name }}` Ansible module when you need to manage {{ skill_name | replace('_', ' ') }} on remote hosts. This is preferable to local CLI commands when:

- Targeting one or more **remote** hosts over SSH
- You need **idempotent** state management (ensure a desired state, not just run a command)
- You want **audit trails** and **dry-run** capability via `--check`

Do **not** use this for basic local file operations or CLI tasks that the agent can handle natively.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
{% for p in params -%}
| `{{ p.name }}` | {{ p.type }} | {{ "yes" if p.required else "no" }} | {{ p.default if p.default is not none else "-" }} | {{ p.description | truncate(120) }} |
{% endfor %}
{% if params | selectattr("choices") | list %}
### Parameter Choices

{% for p in params %}{% if p.choices %}
- **{{ p.name }}**: {{ p.choices | join(", ") }}
{% endif %}{% endfor %}
{% endif %}
{% if aap_configured %}
## How to Execute (AAP)

You MUST use `scripts/aap_run.py` for all commands below. The script
auto-detects the correct API path for both AAP 2.4 (`/api/v2`) and
AAP 2.5+ Gateway (`/api/controller/v2`).

**Do not use `scripts/run.sh` in AAP mode** — it is for local CLI execution only.

**Prefer Job Templates** for normal work. **Ad-hoc** is optional (one-off runs without a playbook).

All launches use **AAP-managed inventories**; Job Templates are created with a Controller inventory attached. Use baked defaults or `--inventory` to refer to an inventory object in AAP, not a local file.

### Job Templates

Job Templates provide repeatable, RBAC-controlled execution in AAP.

**Create a Job Template** (if one does not exist yet):

```bash
python3 scripts/aap_run.py create-jt --name "{{ skill_name | replace('_', '-') }}"
```

**Launch a Job Template**:

```bash
python3 scripts/aap_run.py launch "{{ skill_name | replace('_', '-') }}"

# With extra variables
python3 scripts/aap_run.py launch "{{ skill_name | replace('_', '-') }}" --extra-vars '{"target_hosts": "webservers"}'

# Limit to specific hosts
python3 scripts/aap_run.py launch "{{ skill_name | replace('_', '-') }}" --limit "web1.example.com"
```

**Check job status**:

```bash
python3 scripts/aap_run.py status <job-id>
```

### Optional: ad-hoc commands

One-off module runs without `assets/playbook.yml` (debugging or quick checks):

```bash
python3 scripts/aap_run.py adhoc "{{ example_args }}" --check
python3 scripts/aap_run.py adhoc "{{ example_args }}"
python3 scripts/aap_run.py adhoc "{{ example_args }}" --limit "web1.example.com"
```
{% else %}
## How to Execute (CLI)

Run this module using the `ansible` CLI (from `ansible-core`):

```bash
ansible <host-pattern> -m {{ module_name }} -a "<key=value arguments>" -b --check --diff
```

### Quick Examples

```bash
# ALWAYS dry-run first
ansible webservers -m {{ module_name }} -a "{{ example_args }}" -b --check --diff

# Apply the change after reviewing dry-run output
ansible webservers -m {{ module_name }} -a "{{ example_args }}" -b --diff
```

### Key Flags

| Flag | Purpose |
|------|---------|
| `-b` | Run with sudo/become (required for most system changes) |
| `--check` | Dry-run mode -- shows what **would** change without applying |
| `--diff` | Shows detailed before/after differences |
| `-i <path>` | Specify inventory file (see Inventory section below) |
| `-l <pattern>` | Limit to specific hosts within a group |

### Inventory

For **local / non-production** CLI runs, Ansible must resolve targets from a **reachable inventory** (file, directory, plugin, or ad hoc host list)—there is no default magic without one of these.

When running from inside the AnsibleClaw project, `ansible.cfg` typically sets the default inventory to `inventory/hosts.yml` when that layout exists. When using this skill from another location:

- Specify inventory explicitly: `-i /path/to/inventory.yml`
- Set environment variable: `export ANSIBLE_INVENTORY=/path/to/inventory.yml`
- Use Ansible's default: `/etc/ansible/hosts`
- Target a single host directly: `ansible <hostname>, -m {{ module_name }} -a "..."` (note the trailing comma)

### JSON Output

To get structured JSON output for programmatic parsing:

```bash
ANSIBLE_STDOUT_CALLBACK=json ansible <hosts> -m {{ module_name }} -a "<args>" -b
```
{% endif %}
{% if examples %}

## Examples from Ansible Documentation

```yaml
{{ examples }}
```
{% endif %}

## Safety

- **ALWAYS dry-run first**: In AAP mode, use optional **ad-hoc** `--check`, run the Job Template in **check mode** from the Controller UI when available, or validate in a non-production inventory first; in CLI mode use `--check --diff` before applying changes
- **Become/sudo**: Most system-level modules require elevated privileges. In AAP mode, this is configured in the credential.
- **Idempotency**: This module is idempotent -- running it multiple times with the same arguments produces the same result
