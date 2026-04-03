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
SKILL.md) for ALL execution. Do NOT run local `ansible` CLI commands.

| Setting | Value |
|---------|-------|
| AAP Controller | `{{ aap_url }}` |
| Default Inventory | `{{ aap_inventory }}` |
| Default Credential | `{{ aap_credential }}` |
| Default Project | `{{ aap_project }}` |
{% if aap_ee %}| Default EE | `{{ aap_ee }}` |
{% endif %}

**IMPORTANT**: The environment variable `AAP_CONTROLLER_TOKEN` MUST be set
before running any command. All other AAP settings are pre-configured.

### Quick Start (FOLLOW THESE STEPS EXACTLY)

1. **Check prerequisites**:
   ```bash
   bash scripts/check.sh
   ```

2. **Run ad-hoc command** (dry-run first, ALWAYS):
   ```bash
   python3 scripts/aap_run.py adhoc "{{ example_args }}" --check
   ```

3. **Apply the change** (after reviewing dry-run output):
   ```bash
   python3 scripts/aap_run.py adhoc "{{ example_args }}"
   ```

4. **Or launch an existing Job Template**:
   ```bash
   python3 scripts/aap_run.py launch "{{ skill_name | replace('_', '-') }}"
   ```

5. **If no Job Template exists yet, create one first**:
   ```bash
   python3 scripts/aap_run.py create-jt --name "{{ skill_name | replace('_', '-') }}"
   ```
   Then launch it with step 4.
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

### Ad-Hoc Commands

Run the module directly on AAP-managed hosts:

```bash
# ALWAYS dry-run first
python3 scripts/aap_run.py adhoc "{{ example_args }}" --check

# Apply the change after reviewing dry-run output
python3 scripts/aap_run.py adhoc "{{ example_args }}"

# Target specific hosts
python3 scripts/aap_run.py adhoc "{{ example_args }}" --limit "web1.example.com"
```

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

When running from inside the AnsibleClaw project, `ansible.cfg` sets the default inventory automatically. When using this skill from another location:

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

- **ALWAYS dry-run first**: Use `--check` (AAP) or `--check --diff` (CLI) before applying changes
- **Become/sudo**: Most system-level modules require elevated privileges. In AAP mode, this is configured in the credential.
- **Idempotency**: This module is idempotent -- running it multiple times with the same arguments produces the same result
