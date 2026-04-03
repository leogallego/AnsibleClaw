---
name: ansible-{{ collection_name | replace('_', '-') }}
description: >-
  Collection skill for {{ collection_fqcn }}.
  Use this skill to choose the right module from the {{ collection_fqcn }} collection
  when managing resources on remote hosts via Ansible.
---

# {{ collection_fqcn }} Collection

This skill provides a reference for all {{ modules | length }} modules in the `{{ collection_fqcn }}` collection.
Use it to identify which module to invoke, then refer to the module's individual skill (if generated) for detailed parameters and examples.

## Collection Requirement

This collection must be available before any of its modules can be used.

**CLI mode** (local execution):

```bash
ansible-galaxy collection install {{ collection_fqcn }}
```

**AAP mode** (Execution Environments):
Collections are bundled into Execution Environments (EEs). If this collection is unavailable
in your EE, update your `execution-environment.yml` and rebuild:

```yaml
dependencies:
  galaxy:
    collections:
      - name: {{ collection_fqcn }}
```

```bash
ansible-builder build -t my-ee:latest
```

## When to Use This Skill

Use this skill as a **router** to decide which module from `{{ collection_fqcn }}` best fits the task.
Once you identify the right module, either:

1. Use its dedicated per-module skill (if generated) for full parameter reference and execution scripts
2. Or use the quick-reference below to construct an ad-hoc command or playbook task directly

## Module Catalog

| Module | Description |
|--------|-------------|
{% for m in modules -%}
| `{{ m.module_name }}` | {{ m.short_description | truncate(100) }} |
{% endfor %}

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
*...and {{ m.params | length - 8 }} more parameter(s). Generate the dedicated skill for the full reference.*
{% endif %}
{% endif %}

**Quick example:**

```bash
ansible <hosts> -m {{ m.module_name }} -a "{% for p in m.params if p.required %}{{ p.name }}=<{{ p.name }}>{{ " " if not loop.last }}{% endfor %}" -b --check --diff
```

{% endfor %}

## Execution Patterns

### CLI Mode -- Ad-Hoc

```bash
ansible <host-pattern> -m {{ collection_fqcn }}.<module> -a "<key=value>" -b --check --diff
```

### CLI Mode -- Playbook

```yaml
- hosts: all
  collections:
    - {{ collection_fqcn }}
  tasks:
    - name: Example task
      <module_short_name>:
        <param>: <value>
```

### AAP Mode -- Job Template (preferred)

For each generated per-module skill, use that skill’s `scripts/aap_run.py` for AAP runs; **do not** use `scripts/run.sh` there — it wraps the local `ansible` CLI only.

Create a Job Template for any module in this collection (after `assets/playbook.yml` exists in the AAP Project repo and is synced):

```bash
python3 scripts/aap_run.py create-jt --name "<module>-deploy"
```

Job Templates are bound to a **Controller inventory** when created; launches resolve hosts and groups from that AAP inventory.

Then launch it:

```bash
python3 scripts/aap_run.py launch "<module>-deploy"
```

The Execution Environment must include `{{ collection_fqcn }}`.

### AAP Mode -- Optional ad-hoc command

For one-off module runs without a playbook (not the default production path), use `aap_run.py` from the generated per-module skill:

```bash
python3 scripts/aap_run.py adhoc "<key=value>"
```

**Targets come from AAP-managed inventories**. When defaults are baked in, inventory and credential are auto-resolved. Use `--inventory` for a **different Controller inventory** (name or ID), not a local file path.

## Safety

- **Always dry-run first**: Use `--check --diff` before applying destructive changes
- **Become/sudo**: Most system-level modules require `-b`
- **Idempotency**: All modules in this collection are idempotent -- running them multiple times with the same arguments produces the same result
