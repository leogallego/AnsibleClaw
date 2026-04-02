---
name: ansible-utils
description: >-
  Collection skill for ansible.utils.
  Use this skill to choose the right module from the ansible.utils collection
  when managing resources on remote hosts via Ansible.
---

# ansible.utils Collection

This skill provides a reference for all 4 modules in the `ansible.utils` collection.
Use it to identify which module to invoke, then refer to the module's individual skill (if generated) for detailed parameters and examples.

## Collection Requirement

This collection must be available before any of its modules can be used.

**CLI mode** (local execution):

```bash
ansible-galaxy collection install ansible.utils
```

**AAP mode** (Execution Environments):
Collections are bundled into Execution Environments (EEs). If this collection is unavailable
in your EE, update your `execution-environment.yml` and rebuild:

```yaml
dependencies:
  galaxy:
    collections:
      - name: ansible.utils
```

```bash
ansible-builder build -t my-ee:latest
```

## When to Use This Skill

Use this skill as a **router** to decide which module from `ansible.utils` best fits the task.
Once you identify the right module, either:

1. Use its dedicated per-module skill (if generated) for full parameter reference and execution scripts
2. Or use the quick-reference below to construct an ad-hoc command or playbook task directly

## Module Catalog

| Module | Description |
|--------|-------------|
| `ansible.utils.cli_parse` | Parse cli output or text using a variety of parsers |
| `ansible.utils.fact_diff` | Find the difference between currently set facts |
| `ansible.utils.update_fact` | Update currently set facts |
| `ansible.utils.validate` | Validate data with provided criteria |

### ansible.utils.cli_parse

Parse cli output or text using a variety of parsers

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `parser` | dict | yes | Parser specific parameters |
| `command` | str | no | The command to run on the host |
| `set_fact` | str | no | Set the resulting parsed data as a fact |
| `text` | str | no | Text to be parsed |

**Quick example:**

```bash
ansible <hosts> -m ansible.utils.cli_parse -a "parser=<parser>" -b --check --diff
```

### ansible.utils.fact_diff

Find the difference between currently set facts

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `after` | raw | yes | The second fact to be used in the comparison. |
| `before` | raw | yes | The first fact to be used in the comparison. |
| `plugin` | dict | no | Configure and specify the diff plugin to use |

**Quick example:**

```bash
ansible <hosts> -m ansible.utils.fact_diff -a "after=<after> before=<before>" -b --check --diff
```

### ansible.utils.update_fact

Update currently set facts

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `updates` | list | yes | A list of dictionaries, each a desired update to make. |

**Quick example:**

```bash
ansible <hosts> -m ansible.utils.update_fact -a "updates=<updates>" -b --check --diff
```

### ansible.utils.validate

Validate data with provided criteria

**Key parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `criteria` | raw | yes | The criteria used for validation of I(data). For the type of criteria refer... |
| `data` | raw | yes | Data that will be validated against I(criteria). For the type of data refer... |
| `engine` | str | no | The name of the validate plugin to use. The engine value should follow the... |

**Quick example:**

```bash
ansible <hosts> -m ansible.utils.validate -a "criteria=<criteria> data=<data>" -b --check --diff
```


## Execution Patterns

### CLI -- Ad-Hoc

```bash
ansible <host-pattern> -m ansible.utils.<module> -a "<key=value>" -b --check --diff
```

### CLI -- Playbook

```yaml
- hosts: all
  collections:
    - ansible.utils
  tasks:
    - name: Example task
      <module_short_name>:
        <param>: <value>
```

### AAP -- Ad-Hoc Command

```bash
curl -s -X POST "${AAP_CONTROLLER_URL}/api/v2/ad_hoc_commands/" \
  -H "Authorization: Bearer ${AAP_CONTROLLER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "inventory": 1,
    "credential": 1,
    "module_name": "ansible.utils.<module>",
    "module_args": "<key=value>",
    "become_enabled": true
  }'
```

### AAP -- Job Template

For production workloads, create a Job Template in AAP that references a playbook using modules from this collection. The Execution Environment must include `ansible.utils`.

## Safety

- **Always dry-run first**: Use `--check --diff` before applying destructive changes
- **Become/sudo**: Most system-level modules require `-b`
- **Idempotency**: All modules in this collection are idempotent -- running them multiple times with the same arguments produces the same result
