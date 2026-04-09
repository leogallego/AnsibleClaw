---
name: ansible-{{ skill_name | replace('_', '-') }}
description: >-
  {{ description }}
  Use when managing multiple related resources on remote hosts via Ansible.
---

# {{ skill_name | replace('_', ' ') | title }}

{{ description }}

This is a **composite skill** combining {{ modules | length }} Ansible module(s) into a single use-case-driven package.

## Execution Mode -- READ THIS FIRST
{% if aap_configured %}

**AAP mode is active.** You MUST use `scripts/aap_run.py` (located next to this
SKILL.md) for ALL execution. Do NOT run local `ansible-playbook` or
`scripts/run.sh` — that wrapper invokes the local CLI only, not AAP.

| Setting | Value |
|---------|-------|
| AAP Controller | `{{ aap_url }}` |
| Default AAP inventory | `{{ aap_inventory }}` |
| Default Credential | `{{ aap_credential }}` |
| Default Project | `{{ aap_project }}` |
{% if aap_ee %}| Default EE | `{{ aap_ee }}` |
{% endif %}

The **Default AAP inventory** value is a **Controller inventory** (name or numeric ID) defined and maintained in Ansible Automation Platform, not a path to a local file such as `inventory/hosts.yml`.

**IMPORTANT**: `AAP_CONTROLLER_TOKEN` is required only for Controller API calls
(`create-jt`, `launch`, `status`). You can still edit `assets/playbook.yml`
and push changes to the Project Git repo without the token.

### Quick Start (FOLLOW THESE STEPS EXACTLY)

**Preferred path: Job Templates** (repeatable, RBAC-friendly, typical production flow).

1. **Edit and push playbook changes first**:
   - Update `assets/playbook.yml` for the user request.
   - Run `bash scripts/publish_playbook.sh` to copy/update the skill under `skills/ansible_{{ skill_name }}/` in the AAP Project repo and push.

2. **Optional prerequisite check**:
   ```bash
   bash scripts/check.sh
   ```

3. **Create a Job Template** via helper script:
   ```bash
   python3 scripts/aap_run.py create-jt --name "{{ skill_name | replace('_', '-') }}"
   ```

4. **Launch** (after operator approval):
   ```bash
   python3 scripts/aap_run.py launch "{{ skill_name | replace('_', '-') }}"
   python3 scripts/aap_run.py status <job-id>
   ```
{% else %}

**CLI mode is active.** Use `ansible-playbook` to execute the bundled playbook.
To enable AAP mode, set `AAP_CONTROLLER_URL` and `AAP_CONTROLLER_TOKEN`.
{% endif %}
{% if collection_fqcns %}

## Collection Requirements

This skill requires the following collections:

{% for coll in collection_fqcns %}
- `{{ coll }}`
{% endfor %}
{% if aap_configured %}

In AAP mode, collections are bundled into Execution Environments (EEs).
Ensure your EE includes all required collections. If not, update your
`execution-environment.yml` and rebuild:

```yaml
dependencies:
  galaxy:
    collections:
{% for coll in collection_fqcns %}
      - name: {{ coll }}
{% endfor %}
```
{% else %}

Install them locally:

```bash
ansible-galaxy collection install -r assets/requirements.yml
```

Or individually:

{% for coll in collection_fqcns %}
```bash
ansible-galaxy collection install {{ coll }}
```
{% endfor %}
{% endif %}
{% endif %}

## When to Use This Skill

Use this composite skill when your task involves **multiple** coordinated Ansible modules working together. This skill bundles:

{% for m in modules %}
- **{{ m.module_name }}** -- {{ m.short_description }}
{% endfor %}

This is preferable to running modules individually when:

- Tasks must execute in a **specific order** (e.g., install package before starting service)
- You need a single **playbook** that covers the full workflow
- You want **idempotent**, repeatable automation for the entire use case

## Module Reference

{% for m in modules %}
### {{ m.module_name }}

{{ m.short_description }}

{% if m.params %}
**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
{% for p in m.params[:8] -%}
| `{{ p.name }}` | {{ p.type }} | {{ "yes" if p.required else "no" }} | {{ p.description | truncate(80) }} |
{% endfor %}
{% if m.params | length > 8 -%}
*...and {{ m.params | length - 8 }} more parameter(s). Run `ansible-doc {{ m.module_name }}` for the full reference.*
{% endif %}
{% endif %}
{% if m.examples %}

<details>
<summary>Examples from Ansible Documentation</summary>

```yaml
{{ m.examples }}
```

</details>
{% endif %}

{% endfor %}
{% if aap_configured %}
## How to Execute (AAP)

You MUST use `scripts/aap_run.py` for all commands below. The script
auto-detects the correct API path for both AAP 2.4 (`/api/v2`) and
AAP 2.5+ Gateway (`/api/controller/v2`).

**Do not use `scripts/run.sh` in AAP mode** — it is for local CLI execution only.

### Job Templates

Job Templates provide repeatable, RBAC-controlled execution in AAP.

**Create a Job Template** (if one does not exist yet):

```bash
python3 scripts/aap_run.py create-jt --name "{{ skill_name | replace('_', '-') }}"
```

**Launch** (typically **AAP administrators** or approved operators):

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

Run the bundled playbook using `ansible-playbook`:

```bash
ansible-playbook assets/playbook.yml -i /path/to/inventory.yml --check --diff
```

### Quick Examples

```bash
# ALWAYS dry-run first
ansible-playbook assets/playbook.yml -i /path/to/inventory.yml --check --diff

# Apply the changes after reviewing dry-run output
ansible-playbook assets/playbook.yml -i /path/to/inventory.yml --diff
```

Or use the wrapper script:

```bash
# Dry-run (default)
bash scripts/run.sh -i /path/to/inventory.yml

# Apply for real
bash scripts/run.sh -i /path/to/inventory.yml --apply
```

### Key Flags

| Flag | Purpose |
|------|---------|
| `--check` | Dry-run mode -- shows what **would** change without applying |
| `--diff` | Shows detailed before/after differences |
| `-i <path>` | Specify inventory file |
| `-l <pattern>` | Limit to specific hosts within a group |
| `-e <vars>` | Pass extra variables |

### Inventory

When running from inside the AnsibleClaw project, `ansible.cfg` typically sets the default inventory to `inventory/hosts.yml`. When using this skill from another location:

- Specify inventory explicitly: `-i /path/to/inventory.yml`
- Set environment variable: `export ANSIBLE_INVENTORY=/path/to/inventory.yml`
- Use Ansible's default: `/etc/ansible/hosts`
{% endif %}

## Safety

- **ALWAYS dry-run first**: Use `--check --diff` before applying changes
- **Become/sudo**: Most system-level modules require elevated privileges (`become: true` is set in the playbook)
- **Idempotency**: All modules in this skill are idempotent -- running the playbook multiple times produces the same result
- **Review the playbook**: Edit `assets/playbook.yml` to match your specific needs before running
