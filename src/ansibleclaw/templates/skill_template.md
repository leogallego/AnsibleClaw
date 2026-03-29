---
name: ansible-{{ skill_name }}
description: >-
  {{ short_description }}
  Use when managing {{ skill_name | replace('_', ' ') }} resources on remote hosts via Ansible.
---

# {{ module_name }}

{{ short_description }}

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

## Local Execution (CLI)

Run this module using the `ansible` CLI (from `ansible-core`):

```bash
ansible <host-pattern> -m {{ module_name }} -a "<key=value arguments>" -b --check --diff
```

### Quick Examples

```bash
# Dry-run first (always recommended for destructive operations)
ansible webservers -m {{ module_name }} -a "{{ example_args }}" -b --check --diff

# Apply the change
ansible webservers -m {{ module_name }} -a "{{ example_args }}" -b --diff
```

{% if examples %}
### Examples from Ansible Documentation

```yaml
{{ examples }}
```
{% endif %}

## Key Flags

| Flag | Purpose |
|------|---------|
| `-b` | Run with sudo/become (required for most system changes) |
| `--check` | Dry-run mode -- shows what **would** change without applying |
| `--diff` | Shows detailed before/after differences |
| `-i <path>` | Specify inventory file (see Inventory section below) |
| `-l <pattern>` | Limit to specific hosts within a group |

## JSON Output

To get structured JSON output for programmatic parsing:

```bash
ANSIBLE_STDOUT_CALLBACK=json ansible <hosts> -m {{ module_name }} -a "<args>" -b
```

Or set `stdout_callback = json` in your `ansible.cfg` (AnsibleClaw projects include this by default).

## Safety

- **Always dry-run first**: Use `--check --diff` before applying destructive changes
- **Become/sudo**: Most system-level modules require `-b`. Check the parameters above for guidance.
- **Idempotency**: This module is idempotent -- running it multiple times with the same arguments produces the same result

## Inventory

When running from inside the AnsibleClaw project, `ansible.cfg` sets the default inventory automatically. When using this skill from another location:

- Specify inventory explicitly: `-i /path/to/inventory.yml`
- Set environment variable: `export ANSIBLE_INVENTORY=/path/to/inventory.yml`
- Use Ansible's default: `/etc/ansible/hosts`
- Target a single host directly: `ansible <hostname>, -m {{ module_name }} -a "..."` (note the trailing comma)

## Production Execution (AAP)

When `AAP_CONTROLLER_URL` is set, use Ansible Automation Platform for governed, auditable execution.
All jobs are tracked, RBAC-controlled, and run inside Execution Environments managed by AAP.

### Environment Setup

| Variable | Required | Description |
|----------|----------|-------------|
| `AAP_CONTROLLER_URL` | yes | Base URL of the AAP/AWX controller (e.g. `https://aap.example.com`) |
| `AAP_CONTROLLER_TOKEN` | yes | OAuth2 bearer token for authentication |
| `AAP_VERIFY_SSL` | no | Set to `false` to skip TLS verification (default: `true`) |
| `AAP_DEFAULT_INVENTORY` | no | Default inventory name or ID |
| `AAP_DEFAULT_CREDENTIAL` | no | Default credential name or ID |

### Ad-Hoc Command via AAP

Use the generated helper script:

```bash
python3 scripts/aap_run.py adhoc "{{ example_args }}" --inventory "My Inventory" --credential "Machine Cred"

python3 scripts/aap_run.py adhoc "{{ example_args }}" --inventory "My Inventory" --credential "Machine Cred" --check
```

Or call the API directly:

```bash
curl -s -X POST "${AAP_CONTROLLER_URL}/api/v2/ad_hoc_commands/" \
  -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "inventory": 1,
    "credential": 1,
    "module_name": "{{ module_name }}",
    "module_args": "{{ example_args }}",
    "become_enabled": true
  }'
```

### Job Template Launch via AAP

If a job template exists for this module's playbook:

```bash
python3 scripts/aap_run.py launch "{{ skill_name }}-deploy" --extra-vars '{"target_hosts": "webservers"}'

python3 scripts/aap_run.py launch "{{ skill_name }}-deploy" --limit "web1.example.com"
```

Or call the API directly:

```bash
curl -s -X POST "${AAP_CONTROLLER_URL}/api/v2/job_templates/42/launch/" \
  -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"extra_vars": {"target_hosts": "webservers"}}'
```

### Checking Job Status

The helper script polls automatically. To check manually:

```bash
python3 scripts/aap_run.py status <job-id>
```

### Choosing CLI vs AAP

- **Development/testing**: Use the CLI section above -- direct `ansible` commands with local inventory
- **Production**: Set `AAP_CONTROLLER_URL` and `AAP_CONTROLLER_TOKEN`, then use `scripts/aap_run.py` or the API directly for governed execution
