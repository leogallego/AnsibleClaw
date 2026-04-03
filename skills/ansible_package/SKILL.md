---
name: ansible-package
description: >-
  Generic OS package manager
  Use when managing package resources on remote hosts via Ansible.
---

# ansible.builtin.package

Generic OS package manager

## When to Use This Skill

Use the `ansible.builtin.package` Ansible module when you need to manage package on remote hosts. This is preferable to local CLI commands when:

- Targeting one or more **remote** hosts over SSH
- You need **idempotent** state management (ensure a desired state, not just run a command)
- You want **audit trails** and **dry-run** capability via `--check`

Do **not** use this for basic local file operations or CLI tasks that the agent can handle natively.

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | str | yes | - | Package name, or package specifier with version. Syntax varies with package manager. For example V(name-1.0) or... |
| `state` | str | yes | - | Whether to install (V(present)), or remove (V(absent)) a package. You can use other states like V(latest) ONLY if... |
| `use` | str | no | auto | The required package manager module to use (V(dnf), V(apt), and so on). The default V(auto) will use existing facts... |

## Local Execution (CLI)

Run this module using the `ansible` CLI (from `ansible-core`):

```bash
ansible <host-pattern> -m ansible.builtin.package -a "<key=value arguments>" -b --check --diff
```

### Quick Examples

```bash
# Dry-run first (always recommended for destructive operations)
ansible webservers -m ansible.builtin.package -a "name=ntpdate state=present" -b --check --diff

# Apply the change
ansible webservers -m ansible.builtin.package -a "name=ntpdate state=present" -b --diff
```

### Examples from Ansible Documentation

```yaml
- name: Install ntpdate
  ansible.builtin.package:
    name: ntpdate
    state: present

# This uses a variable as this changes per distribution.
- name: Remove the apache package
  ansible.builtin.package:
    name: "{{ apache }}"
    state: absent

- name: Install the latest version of Apache and MariaDB
  ansible.builtin.package:
    name:
      - httpd
      - mariadb-server
    state: latest

- name: Use the dnf package manager to install httpd
  ansible.builtin.package:
    name: httpd
    state: present
    use: dnf
```

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
ANSIBLE_STDOUT_CALLBACK=json ansible <hosts> -m ansible.builtin.package -a "<args>" -b
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
- Target a single host directly: `ansible <hostname>, -m ansible.builtin.package -a "..."` (note the trailing comma)

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

Use the generated helper script (`scripts/aap_run.py`). It auto-detects
the correct API path for both classic AAP/AWX (`/api/v2`) and AAP 2.5+
Gateway (`/api/controller/v2`), polls until completion, and prints JSON:

```bash
python3 scripts/aap_run.py adhoc "name=ntpdate state=present" --inventory "My Inventory" --credential "Machine Cred"

# Dry-run
python3 scripts/aap_run.py adhoc "name=ntpdate state=present" --inventory "My Inventory" --credential "Machine Cred" --check
```

### Job Template Launch via AAP

If a job template exists for this module's playbook (create one from the
AnsibleClaw web dashboard or the AAP UI):

```bash
python3 scripts/aap_run.py launch "package-deploy" --extra-vars '{"target_hosts": "webservers"}'

python3 scripts/aap_run.py launch "package-deploy" --limit "web1.example.com"
```

### Checking Job Status

The helper script polls automatically. To check a previously launched job:

```bash
python3 scripts/aap_run.py status <job-id>
```

### Choosing CLI vs AAP

- **Development/testing**: Use the CLI section above -- direct `ansible` commands with local inventory
- **Production**: Set `AAP_CONTROLLER_URL` and `AAP_CONTROLLER_TOKEN`, then use `scripts/aap_run.py` for governed, auditable execution
