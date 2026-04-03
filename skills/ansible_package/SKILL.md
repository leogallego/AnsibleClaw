---
name: ansible-package
description: >-
  Generic OS package manager
  Use when managing package resources on remote hosts via Ansible.
---

# ansible.builtin.package

Generic OS package manager

## Execution Mode -- READ THIS FIRST

**AAP mode is active.** You MUST use `scripts/aap_run.py` (located next to this
SKILL.md) for ALL execution. Do NOT run local `ansible` CLI commands or
`scripts/run.sh` — that wrapper invokes the local `ansible` CLI only, not AAP.

| Setting | Value |
|---------|-------|
| AAP Controller | `https://aap-aap.apps.cluster-rmf2p-1.dynamic.redhatworkshops.io` |
| Default AAP inventory | `Demo Inventory` |
| Default Credential | `Demo Credential` |
| Default Project | `AnsibleClaw` |
| Default EE | `Default execution environment` |

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

2. **Prepare `assets/playbook.yml`** — edit tasks to use `ansible.builtin.package` with the parameters you need. The Job Template references this path **inside your AAP Project’s Git repo**; changes must be **pushed** and the project **synced** in AAP before launch (or use AnsibleClaw **Deploy to AAP** in the web UI).

3. **Create a Job Template** (skip if it already exists):
   ```bash
   python3 scripts/aap_run.py create-jt --name "package"
   ```
   Use your site’s Job Template naming convention if a prefix is configured (e.g. `AnsibleClaw: …`).

4. **Launch the Job Template**:
   ```bash
   python3 scripts/aap_run.py launch "package"
   ```
   Add `--limit`, `--inventory`, or `--extra-vars` as needed (see **How to Execute (AAP)** below).

5. **Check job status** (optional):
   ```bash
   python3 scripts/aap_run.py status <job-id>
   ```

#### Optional: ad-hoc (one-off, no playbook)

Use only for quick probes or debugging — **not** the default production path:

```bash
python3 scripts/aap_run.py adhoc "name=ntpdate state=present" --check
python3 scripts/aap_run.py adhoc "name=ntpdate state=present"
```

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
python3 scripts/aap_run.py create-jt --name "package"
```

**Launch a Job Template**:

```bash
python3 scripts/aap_run.py launch "package"

# With extra variables
python3 scripts/aap_run.py launch "package" --extra-vars '{"target_hosts": "webservers"}'

# Limit to specific hosts
python3 scripts/aap_run.py launch "package" --limit "web1.example.com"
```

**Check job status**:

```bash
python3 scripts/aap_run.py status <job-id>
```

### Optional: ad-hoc commands

One-off module runs without `assets/playbook.yml` (debugging or quick checks):

```bash
python3 scripts/aap_run.py adhoc "name=ntpdate state=present" --check
python3 scripts/aap_run.py adhoc "name=ntpdate state=present"
python3 scripts/aap_run.py adhoc "name=ntpdate state=present" --limit "web1.example.com"
```

## Examples from Ansible Documentation

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

## Safety

- **ALWAYS dry-run first**: In AAP mode, use optional **ad-hoc** `--check`, run the Job Template in **check mode** from the Controller UI when available, or validate in a non-production inventory first; in CLI mode use `--check --diff` before applying changes
- **Become/sudo**: Most system-level modules require elevated privileges. In AAP mode, this is configured in the credential.
- **Idempotency**: This module is idempotent -- running it multiple times with the same arguments produces the same result
