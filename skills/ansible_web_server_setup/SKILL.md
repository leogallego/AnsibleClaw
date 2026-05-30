---
name: ansible-web-server-setup
description: >-
  Deploy and secure an Nginx web server.
  Use when managing multiple related resources on remote hosts via Ansible.
---

# Web-Server-Setup

Deploy and secure an Nginx web server.

This is a **composite skill** combining 4 Ansible module(s) into a single use-case-driven package.

## Execution Mode -- READ THIS FIRST

**AAP mode is active.** You MUST use `scripts/aap_run.py` (located next to this
SKILL.md) for ALL execution. Do NOT run local `ansible-playbook` or
`scripts/run.sh` — that wrapper invokes the local CLI only, not AAP.

| Setting | Value |
|---------|-------|
| AAP Controller | `https://aap-aap.apps.cluster-74lbd-1.dynamic2.redhatworkshops.io` |
| Default AAP inventory | `` |
| Default Credential | `` |
| Default Project | `` |

The **Default AAP inventory** value is a **Controller inventory** (name or numeric ID) defined and maintained in Ansible Automation Platform, not a path to a local file such as `inventory/hosts.yml`.

**IMPORTANT**: `AAP_CONTROLLER_TOKEN` is required only for Controller API calls
(`create-jt`, `launch`, `status`). You can still edit `assets/playbook.yml`
and push changes to the Project Git repo without the token.

### Quick Start (FOLLOW THESE STEPS EXACTLY)

**Preferred path: Job Templates** (repeatable, RBAC-friendly, typical production flow).

1. **Edit and push playbook changes first**:
   - Update `assets/playbook.yml` for the user request.
   - Run `bash scripts/publish_playbook.sh` to copy/update the skill under `skills/ansible_web-server-setup/` in the AAP Project repo and push.

2. **Optional prerequisite check**:
   ```bash
   bash scripts/check.sh
   ```

3. **Create a Job Template** via helper script:
   ```bash
   python3 scripts/aap_run.py create-jt --name "web-server-setup"
   ```

4. **Launch** (after operator approval):
   ```bash
   python3 scripts/aap_run.py launch "web-server-setup"
   python3 scripts/aap_run.py status <job-id>
   ```

## Collection Requirements

This skill requires the following collections:

- `ansible.posix`

In AAP mode, collections are bundled into Execution Environments (EEs).
Ensure your EE includes all required collections. If not, update your
`execution-environment.yml` and rebuild:

```yaml
dependencies:
  galaxy:
    collections:
      - name: ansible.posix
```

## When to Use This Skill

Use this composite skill when your task involves **multiple** coordinated Ansible modules working together. This skill bundles:

- **ansible.builtin.package** -- Generic OS package manager
- **ansible.builtin.template** -- Template a file out to a target host
- **ansible.builtin.service** -- Manage services
- **ansible.posix.firewalld** -- Manage arbitrary ports/services with firewalld

This is preferable to running modules individually when:

- Tasks must execute in a **specific order** (e.g., install package before starting service)
- You need a single **playbook** that covers the full workflow
- You want **idempotent**, repeatable automation for the entire use case

## Module Reference

### ansible.builtin.package

Generic OS package manager

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | str | yes | Package name, or package specifier with version. Syntax varies with package... |
| `state` | str | yes | Whether to install (V(present)), or remove (V(absent)) a package. You can... |
| `use` | str | no | The required package manager module to use (V(dnf), V(apt), and so on). The... |

<details>
<summary>Examples from Ansible Documentation</summary>

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

</details>

### ansible.builtin.template

Template a file out to a target host

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `dest` | path | yes | Location to render the template to on the remote machine. |
| `src` | path | yes | Path of a Jinja2 formatted template on the Ansible controller. This can be a... |
| `attributes` | str | no | The attributes the resulting filesystem object should have. To get supported... |
| `backup` | bool | no | Create a backup file including the timestamp information so you can get the... |
| `block_end_string` | str | no | The string marking the end of a block. |
| `block_start_string` | str | no | The string marking the beginning of a block. |
| `comment_end_string` | str | no | The string marking the end of a comment statement. |
| `comment_start_string` | str | no | The string marking the beginning of a comment statement. |
*...and 17 more parameter(s). Run `ansible-doc ansible.builtin.template` for the full reference.*

<details>
<summary>Examples from Ansible Documentation</summary>

```yaml

- name: Template a file to /etc/file.conf
  ansible.builtin.template:
    src: /mytemplates/foo.j2
    dest: /etc/file.conf
    owner: bin
    group: wheel
    mode: '0644'

- name: Template a file, using symbolic modes (equivalent to 0644)
  ansible.builtin.template:
    src: /mytemplates/foo.j2
    dest: /etc/file.conf
    owner: bin
    group: wheel
    mode: u=rw,g=r,o=r

- name: Copy a version of named.conf that is dependent on the OS. setype obtained by doing ls -Z /etc/named.conf on original file
  ansible.builtin.template:
    src: named.conf_{{ ansible_os_family }}.j2
    dest: /etc/named.conf
    group: named
    setype: named_conf_t
    mode: '0640'

- name: Create a DOS-style text file from a template
  ansible.builtin.template:
    src: config.ini.j2
    dest: /share/windows/config.ini
    newline_sequence: '\r\n'

- name: Copy a new sudoers file into place, after passing validation with visudo
  ansible.builtin.template:
    src: /mine/sudoers
    dest: /etc/sudoers
    validate: /usr/sbin/visudo -cf %s

- name: Update sshd configuration safely, avoid locking yourself out
  ansible.builtin.template:
    src: etc/ssh/sshd_config.j2
    dest: /etc/ssh/sshd_config
    owner: root
    group: root
    mode: '0600'
    validate: /usr/sbin/sshd -t -f %s
    backup: yes

```

</details>

### ansible.builtin.service

Manage services

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | str | yes | Name of the service. |
| `arguments` | str | no | Additional arguments provided on the command line. While using remote hosts... |
| `enabled` | bool | no | Whether the service should start on boot. At least one of O(state) and... |
| `pattern` | str | no | If the service does not respond to the status command, name a substring to... |
| `runlevel` | str | no | For OpenRC init scripts (e.g. Gentoo) only. The runlevel that this service... |
| `sleep` | int | no | If the service is being V(restarted) then sleep this many seconds between... |
| `state` | str | no | V(started)/V(stopped) are idempotent actions that will not run commands... |
| `use` | str | no | The service module actually uses system specific modules, normally through... |

<details>
<summary>Examples from Ansible Documentation</summary>

```yaml

- name: Start service httpd, if not started
  ansible.builtin.service:
    name: httpd
    state: started

- name: Stop service httpd, if started
  ansible.builtin.service:
    name: httpd
    state: stopped

- name: Restart service httpd, in all cases
  ansible.builtin.service:
    name: httpd
    state: restarted

- name: Reload service httpd, in all cases
  ansible.builtin.service:
    name: httpd
    state: reloaded

- name: Enable service httpd, and not touch the state
  ansible.builtin.service:
    name: httpd
    enabled: yes

- name: Start service foo, based on running process /usr/bin/foo
  ansible.builtin.service:
    name: foo
    pattern: /usr/bin/foo
    state: started

- name: Restart network service for interface eth0
  ansible.builtin.service:
    name: network
    state: restarted
    args: eth0

```

</details>

### ansible.posix.firewalld

Manage arbitrary ports/services with firewalld

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `state` | str | yes | Enable or disable a setting. For ports: Should this port accept (V(enabled))... |
| `forward` | bool | no | The forward setting you would like to enable/disable to/from zones within... |
| `icmp_block` | str | no | The ICMP block you would like to add/remove to/from a zone in firewalld. |
| `icmp_block_inversion` | bool | no | Enable/Disable inversion of ICMP blocks for a zone in firewalld. Note that... |
| `immediate` | bool | no | Whether to apply this change to the runtime firewalld configuration.... |
| `interface` | str | no | The interface you would like to add/remove to/from a zone in firewalld. |
| `masquerade` | bool | no | The masquerade setting you would like to enable/disable to/from zones within... |
| `offline` | bool | no | Ignores O(immediate) if O(permanent=true) and firewalld is not running. |
*...and 10 more parameter(s). Run `ansible-doc ansible.posix.firewalld` for the full reference.*

<details>
<summary>Examples from Ansible Documentation</summary>

```yaml

- name: Permanently enable https service, also enable it immediately if possible
  ansible.posix.firewalld:
    service: https
    state: enabled
    permanent: true
    immediate: true
    offline: true

- name: Permit traffic in default zone for https service
  ansible.posix.firewalld:
    service: https
    permanent: true
    state: enabled

- name: Permit ospf traffic
  ansible.posix.firewalld:
    protocol: ospf
    permanent: true
    state: enabled

- name: Do not permit traffic in default zone on port 8081/tcp
  ansible.posix.firewalld:
    port: 8081/tcp
    permanent: true
    state: disabled

- name: Permit traffic in default zone on port 161-162/ucp
  ansible.posix.firewalld:
    port: 161-162/udp
    permanent: true
    state: enabled

- name: Permit traffic in dmz zone on http service
  ansible.posix.firewalld:
    zone: dmz
    service: http
    permanent: true
    state: enabled

- name: Enable FTP service with rate limiting using firewalld rich rule
  ansible.posix.firewalld:
    rich_rule: rule service name="ftp" audit limit value="1/m" accept
    permanent: true
    state: enabled

- name: Allow traffic from 192.0.2.0/24 in internal zone
  ansible.posix.firewalld:
    source: 192.0.2.0/24
    zone: internal
    state: enabled

- name: Assign eth2 interface to trusted zone
  ansible.posix.firewalld:
    zone: trusted
    interface: eth2
    permanent: true
    state: enabled

- name: Enable forwarding in internal zone
  ansible.posix.firewalld:
    forward: true
    state: enabled
    permanent: true
    zone: internal

- name: Enable masquerade in dmz zone
  ansible.posix.firewalld:
    masquerade: true
    state: enabled
    permanent: true
    zone: dmz

- name: Create custom zone if not already present
  ansible.posix.firewalld:
    zone: custom
    state: present
    permanent: true

- name: Enable ICMP block inversion in drop zone
  ansible.posix.firewalld:
    zone: drop
    state: enabled
    permanent: true
    icmp_block_inversion: true

- name: Block ICMP echo requests in drop zone
  ansible.posix.firewalld:
    zone: drop
    state: enabled
    permanent: true
    icmp_block: echo-request

- name: Set internal zone target to ACCEPT
  ansible.posix.firewalld:
    zone: internal
    state: present
    permanent: true
    target: ACCEPT

- name: Redirect port 443 to 8443 with Rich Rule
  ansible.posix.firewalld:
    rich_rule: rule family=ipv4 forward-port port=443 protocol=tcp to-port=8443
    zone: public
    permanent: true
    immediate: true
    state: enabled

```

</details>

## How to Execute (AAP)

You MUST use `scripts/aap_run.py` for all commands below. The script
auto-detects the correct API path for both AAP 2.4 (`/api/v2`) and
AAP 2.5+ Gateway (`/api/controller/v2`).

**Do not use `scripts/run.sh` in AAP mode** — it is for local CLI execution only.

### Job Templates

Job Templates provide repeatable, RBAC-controlled execution in AAP.

**Create a Job Template** (if one does not exist yet):

```bash
python3 scripts/aap_run.py create-jt --name "web-server-setup"
```

**Launch** (typically **AAP administrators** or approved operators):

```bash
python3 scripts/aap_run.py launch "web-server-setup"

# With extra variables
python3 scripts/aap_run.py launch "web-server-setup" --extra-vars '{"target_hosts": "webservers"}'

# Limit to specific hosts
python3 scripts/aap_run.py launch "web-server-setup" --limit "web1.example.com"
```

**Check job status**:

```bash
python3 scripts/aap_run.py status <job-id>
```

## Safety

- **ALWAYS dry-run first**: Use `--check --diff` before applying changes
- **Become/sudo**: Most system-level modules require elevated privileges (`become: true` is set in the playbook)
- **Idempotency**: All modules in this skill are idempotent -- running the playbook multiple times produces the same result
- **Review the playbook**: Edit `assets/playbook.yml` to match your specific needs before running
